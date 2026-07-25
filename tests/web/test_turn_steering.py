"""
Behavioral contract tests for steering a run through the public web lifecycle.

Boundary: the FastAPI review API (POST /turns, POST /turns/{id}/answer-now,
POST /turns/{id}/cancel) + TurnLifecycleStore. A scripted provider triggers the
steering directive mid-run by writing it to the shared disk-backed store, which
the running turn polls between rounds -- mirroring a concurrent user click
without threads (bead pydexpi-datalog-1-3qo.9.8).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from pydexpi_datalog.qa.grounded_qa_harness import ToolCall

# These tests reach past the API into a hand-built `LocalArtifactStore` --
# a steering directive written directly to storage, a trace artifact read
# back off disk. That makes them tests of the local implementation, so the
# app is pinned to the local profile rather than following the ambient one:
# under hosted the app reads a bucket and would never see what the test
# wrote (bead 2afe.8).
from pydexpi_datalog.web.deployment import DeploymentProfile
from pydexpi_datalog.web.review_api import create_review_api_app
from pydexpi_datalog.web.turn_lifecycle import TurnLifecycleStore, compute_turn_id
from pydexpi_datalog.workflow.artifact_store import LocalArtifactStore
from pydexpi_datalog.workflow.principal import LOCAL_PRINCIPAL

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


def _prepare(client: TestClient, session_id: str) -> None:
    prepared = client.post(
        f"/api/review/sessions/{session_id}/prepare",
        json={
            "filename": E06_FIXTURE.name,
            "content": E06_FIXTURE.read_text(encoding="utf-8"),
        },
    )
    assert prepared.status_code == 200


class SteersMidRunProvider:
    """Explores with a read-only tool each round and records a steering directive
    in the store during the ``steer_on_call``-th round. The directive is caught
    at the next round's poll, so exploration after that point must never run."""

    def __init__(
        self,
        *,
        root: Path,
        session_id: str,
        turn_id: str,
        directive: str,
        steer_on_call: int = 1,
    ):
        # The API scopes storage by the default local workspace, so a store
        # built directly here must write where the running turn will read.
        self._store = TurnLifecycleStore(LocalArtifactStore(root / LOCAL_PRINCIPAL.workspace))
        self._session_id = session_id
        self._turn_id = turn_id
        self._directive = directive
        self._steer_on_call = steer_on_call
        self.calls = 0

    def complete_with_tools(self, *, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == self._steer_on_call:
            if self._directive == "answer_now":
                self._store.request_answer_now(
                    session_id=self._session_id, turn_id=self._turn_id
                )
            else:
                self._store.cancel(session_id=self._session_id, turn_id=self._turn_id)
        return ToolCall(
            tool_name="find_equipment",
            tool_input={"pattern": "P"},
            tool_call_id=f"explore-{self.calls}",
        )


def test_answer_now_endpoint_returns_completed_synthesized_answer() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        session_id = "answer-now-session"
        request_id = "answer-now-request"
        turn_id = compute_turn_id(session_id, request_id)
        provider = SteersMidRunProvider(
            root=root,
            session_id=session_id,
            turn_id=turn_id,
            directive="answer_now",
        )
        client = TestClient(
            create_review_api_app(
            profile=DeploymentProfile.LOCAL,
                artifact_root=root, qa_provider_factory=lambda: provider
            )
        )
        _prepare(client, session_id)

        turn = client.post(
            f"/api/review/sessions/{session_id}/turns",
            json={"request_id": request_id, "question": "Which equipment exists?"},
        ).json()

        # Interrupted after exactly one exploratory round.
        assert provider.calls == 1
        assert turn["status"] == "completed"
        answer = next(e for e in turn["events"] if e["type"] == "text")["data"]["text"]
        lowered = answer.lower()
        assert "answer now" in lowered or "no validated verdict" in lowered


def test_answer_now_endpoint_reports_404_for_a_missing_turn() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        client = TestClient(create_review_api_app(
            profile=DeploymentProfile.LOCAL,artifact_root=root))
        _prepare(client, "missing-turn-session")
        response = client.post(
            "/api/review/sessions/missing-turn-session/turns/"
            "0000000000000000abcd/answer-now"
        )
        assert response.status_code == 404


def test_store_request_answer_now_records_directive_without_ending_turn() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir) / "sessions"))
        active = store.begin(
            session_id="steer-session",
            request_id="req-1",
            question="A long-running question",
        )
        turn_id = str(active["turn_id"])

        steered = store.request_answer_now(session_id="steer-session", turn_id=turn_id)

        assert steered is not None
        # The directive is recorded; the turn is NOT terminated (unlike cancel).
        assert steered["status"] == "active"
        assert steered["steering"] == "answer_now"
        reloaded = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir) / "sessions")).get(
            session_id="steer-session", turn_id=turn_id
        )
        assert reloaded is not None
        assert reloaded["steering"] == "answer_now"


def test_stop_via_cancel_interrupts_exploration_and_preserves_trace() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        session_id = "stop-session"
        request_id = "stop-request"
        turn_id = compute_turn_id(session_id, request_id)
        provider = SteersMidRunProvider(
            root=root,
            session_id=session_id,
            turn_id=turn_id,
            directive="stop",
            steer_on_call=2,
        )
        client = TestClient(
            create_review_api_app(
            profile=DeploymentProfile.LOCAL,
                artifact_root=root, qa_provider_factory=lambda: provider
            )
        )
        _prepare(client, session_id)

        turn = client.post(
            f"/api/review/sessions/{session_id}/turns",
            json={"request_id": request_id, "question": "Which equipment exists?"},
        ).json()

        # Stop was issued after one clean round; exploration halted at that round
        # rather than running the provider's unbounded further calls.
        assert provider.calls == 2
        assert turn["status"] == "canceled"
        event_types = [event["type"] for event in turn["events"]]
        # The completed live trace (the first round's progress) is preserved,
        # and the cancellation is terminal.
        assert event_types[-1] == "cancellation"
        assert any(
            event["type"] == "tool-progress" and event["data"].get("status") == "round"
            for event in turn["events"]
        )


class RepeatedExplorerProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete_with_tools(self, *, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ToolCall(
            tool_name="find_equipment",
            tool_input={"pattern": "P"},
            tool_call_id=f"explore-{self.calls}",
        )


def test_user_turn_constraint_from_body_clamps_the_run() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        provider = RepeatedExplorerProvider()
        client = TestClient(
            create_review_api_app(
            profile=DeploymentProfile.LOCAL,
                artifact_root=root, qa_provider_factory=lambda: provider
            )
        )
        session_id = "turn-cap-session"
        _prepare(client, session_id)

        turn = client.post(
            f"/api/review/sessions/{session_id}/turns",
            json={
                "request_id": "turn-cap-request",
                "question": "Which equipment exists?",
                "constraints": {"turns": 1},
            },
        ).json()

        # The user turn cap (1) bound the run below the operational ceiling (20).
        assert provider.calls == 1
        assert turn["status"] == "completed"
