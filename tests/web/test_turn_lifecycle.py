from __future__ import annotations

from pathlib import Path
import tempfile

from fastapi.testclient import TestClient

from pydexpi_datalog.qa.grounded_qa_harness import FinalAnswer
from pydexpi_datalog.web.review_api import create_review_api_app
from pydexpi_datalog.web.turn_lifecycle import TurnLifecycleStore


REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete_with_tools(self, *, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        return FinalAnswer(answer_text="Persisted answer")


def test_duplicate_turn_request_executes_once_and_reconnect_replays_events() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        provider = CountingProvider()
        app = create_review_api_app(
            artifact_root=root, qa_provider_factory=lambda: provider
        )
        client = TestClient(app)
        session_id = "lifecycle-session"
        prepared = client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": E06_FIXTURE.name,
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        assert prepared.status_code == 200

        path = f"/api/review/sessions/{session_id}/turns"
        first = client.post(
            path, json={"request_id": "client-request-1", "question": "Hello"}
        ).json()
        duplicate = client.post(
            path, json={"request_id": "client-request-1", "question": "Hello"}
        ).json()

        assert duplicate == first
        assert provider.calls == 1
        assert first["status"] == "completed"
        assert [event["type"] for event in first["events"]] == [
            "tool-progress",
            "text",
            "evidence",
            "completion",
        ]

        # A fresh app instance represents browser/server reconnect. Turn state is
        # loaded from disk without re-running the provider.
        reconnected = TestClient(create_review_api_app(artifact_root=root))
        replay = reconnected.get(
            f"/api/review/sessions/{session_id}/turns/{first['turn_id']}"
        )
        assert replay.status_code == 200
        assert replay.json() == first

        stream = reconnected.get(
            f"/api/review/sessions/{session_id}/turns/{first['turn_id']}/events",
            params={"after": 1},
        )
        assert stream.headers["content-type"].startswith("application/x-ndjson")
        assert [
            __import__("json").loads(line)["type"]
            for line in stream.text.splitlines()
        ] == ["evidence", "completion"]


def test_active_turn_cancellation_is_terminal_persisted_and_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        store = TurnLifecycleStore(root)
        active = store.begin(
            session_id="cancel-session",
            request_id="request-1",
            question="A long-running question",
        )

        canceled = store.cancel(
            session_id="cancel-session", turn_id=str(active["turn_id"])
        )
        duplicate = store.cancel(
            session_id="cancel-session", turn_id=str(active["turn_id"])
        )
        reloaded = TurnLifecycleStore(root).get(
            session_id="cancel-session", turn_id=str(active["turn_id"])
        )

        assert canceled == duplicate == reloaded
        assert canceled is not None
        assert canceled["status"] == "canceled"
        assert [event["type"] for event in canceled["events"]] == [
            "tool-progress",
            "cancellation",
        ]


def test_execution_failure_is_persisted_as_typed_terminal_event() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TurnLifecycleStore(Path(tmp_dir) / "sessions")

        turn = store.start(
            session_id="failure-session",
            request_id="request-1",
            question="Fail safely",
            execute=lambda: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
        )

        assert turn["status"] == "failed"
        assert turn["events"][-1]["type"] == "failure"
        assert "provider unavailable" in turn["events"][-1]["data"]["message"]


def test_paused_review_can_reconnect_resume_once_or_cancel() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        client = TestClient(create_review_api_app(artifact_root=root))
        session_id = "paused-session"
        assert client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": E06_FIXTURE.name,
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        ).status_code == 200

        turns_path = f"/api/review/sessions/{session_id}/turns"
        paused = client.post(
            turns_path,
            json={
                "request_id": "review-request",
                "question": "What is downstream of the piping?",
            },
        ).json()
        assert paused["status"] == "paused"
        assert paused["events"][-1]["type"] == "review-required"
        review = paused["result"]["direction_review"]

        resume_path = f"{turns_path}/{paused['turn_id']}/direction-review"
        resumed = client.post(
            resume_path,
            json={"decision": "confirm", "review_key": review["review_key"]},
        ).json()
        duplicate = client.post(
            resume_path,
            json={"decision": "confirm", "review_key": review["review_key"]},
        ).json()
        assert duplicate == resumed
        assert resumed["status"] == "completed"
        assert [event["type"] for event in resumed["events"]].count("completion") == 1

        cancelable = client.post(
            turns_path,
            json={
                "request_id": "cancel-request",
                "question": "What is upstream of the piping?",
            },
        ).json()
        canceled = client.post(
            f"{turns_path}/{cancelable['turn_id']}/cancel"
        ).json()
        assert canceled["status"] == "canceled"
        assert canceled["events"][-1]["type"] == "cancellation"


class _DatalogProposalProvider:
    def __init__(self, answer_id: str) -> None:
        self._step = 0
        self._answer_id = answer_id

    def complete_with_tools(self, *, messages, tools):  # type: ignore[no-untyped-def]
        from pydexpi_datalog.qa.grounded_qa_harness import ToolCall

        if self._step == 0:
            self._step += 1
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every connected object satisfy the temporary topology rule?",
                    "generated_datalog": f'.decl answer(x:symbol)\n.output answer\nanswer("{self._answer_id}").',
                    "formal_restatement": "Return objects matching the temporary topology rule.",
                    "resolved_identity_ids": [self._answer_id],
                },
                tool_call_id="proposal-1",
            )
        return FinalAnswer(answer_text="Proposal ready for confirmation.")


def test_paused_datalog_confirmation_turn_resumes_and_executes_once() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        holder: dict[str, str] = {}
        client = TestClient(
            create_review_api_app(
                artifact_root=root,
                qa_provider_factory=lambda: _DatalogProposalProvider(holder["answer_id"]),
            )
        )
        session_id = "datalog-turn-session"
        prepared = client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": E06_FIXTURE.name,
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        assert prepared.status_code == 200
        holder["answer_id"] = prepared.json()["topology_view"]["nodes"][0]["id"]

        turns_path = f"/api/review/sessions/{session_id}/turns"
        paused = client.post(
            turns_path,
            json={
                "request_id": "datalog-request",
                "question": "Must every connected object satisfy the temporary topology rule?",
            },
        ).json()
        assert paused["status"] == "paused"
        assert paused["events"][-1]["type"] == "review-required"
        confirmation = paused["result"]["datalog_confirmation"]

        resume_path = f"{turns_path}/{paused['turn_id']}/datalog-review"
        resumed = client.post(
            resume_path,
            json={"decision": "confirm", "proposal_result": confirmation["proposal_result"]},
        ).json()
        duplicate = client.post(
            resume_path,
            json={"decision": "confirm", "proposal_result": confirmation["proposal_result"]},
        ).json()

        assert duplicate == resumed
        assert resumed["status"] == "completed"
        assert [event["type"] for event in resumed["events"]].count("completion") == 1
        assert resumed["result"]["evidence"]["items"][0]["id"] == holder["answer_id"]


def test_paused_datalog_confirmation_turn_can_be_canceled() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        holder: dict[str, str] = {}
        client = TestClient(
            create_review_api_app(
                artifact_root=root,
                qa_provider_factory=lambda: _DatalogProposalProvider(holder["answer_id"]),
            )
        )
        session_id = "datalog-cancel-session"
        prepared = client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": E06_FIXTURE.name,
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        assert prepared.status_code == 200
        holder["answer_id"] = prepared.json()["topology_view"]["nodes"][0]["id"]

        turns_path = f"/api/review/sessions/{session_id}/turns"
        paused = client.post(
            turns_path,
            json={
                "request_id": "datalog-cancel-request",
                "question": "Must every connected object satisfy the temporary topology rule?",
            },
        ).json()
        assert paused["status"] == "paused"

        canceled = client.post(
            f"{turns_path}/{paused['turn_id']}/cancel"
        ).json()
        assert canceled["status"] == "canceled"
        assert canceled["events"][-1]["type"] == "cancellation"
