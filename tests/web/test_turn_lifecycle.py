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


def test_review_required_event_preserves_batched_direction_review_items() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TurnLifecycleStore(Path(tmp_dir))
        turn = store.start(
            session_id="session-batch",
            request_id="request-batch",
            question="Do all pumps have downstream valves?",
            execute=lambda: {
                "status": "needs_direction_review",
                "direction_reviews": [
                    {"review_key": "review-a", "object_id": "pump-a"},
                    {"review_key": "review-b", "object_id": "pump-b"},
                ],
                "direction_review": {"review_key": "review-a", "object_id": "pump-a"},
            },
        )

        assert turn["status"] == "paused"
        review_event = turn["events"][-1]
        assert review_event["type"] == "review-required"
        review = review_event["data"]["review"]
        assert [item["review_key"] for item in review["direction_reviews"]] == [
            "review-a",
            "review-b",
        ]


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


def test_execution_failed_result_surfaces_diagnostics_in_failure_message() -> None:
    """
    Bead 3cq: a confirmed Datalog execution that fails must carry its
    diagnostics through the failure event's `message` -- the frontend renders
    event.data.message and otherwise falls back to a bare "Turn failed",
    hiding the actual reason from the user.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TurnLifecycleStore(Path(tmp_dir) / "sessions")
        turn = store.start(
            session_id="failure-session",
            request_id="request-1",
            question="Do all pumps have a check valve?",
            execute=lambda: {"status": "needs_datalog_confirmation"},
        )

        resumed = store.resume(
            session_id="failure-session",
            turn_id=str(turn["turn_id"]),
            execute=lambda: {
                "status": "execution_failed",
                "executed": False,
                "diagnostics": [
                    {
                        "code": "temporary_datalog.predicate_not_approved",
                        "message": "Temporary Datalog used unapproved predicate(s): pump",
                    }
                ],
            },
        )

        assert resumed is not None
        assert resumed["status"] == "failed"
        failure = resumed["events"][-1]
        assert failure["type"] == "failure"
        assert "unapproved predicate" in failure["data"]["message"]
        assert failure["data"]["result"]["status"] == "execution_failed"


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
                "question": "What is downstream of the segment?",
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
                "question": "What is upstream of the segment?",
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


def test_default_provider_rule_question_pauses_and_confirms_without_trust_escalation() -> None:
    """The OSS default (scripted) provider reaches the confirmation gate live:
    a rule-like chat question pauses with needs_datalog_confirmation, Run
    resumes to a real executed answer, and a later proposal in the same
    session pauses again -- there is no skip-confirmation mechanism."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        client = TestClient(create_review_api_app(artifact_root=root))
        session_id = "default-gate-session"
        assert client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": E06_FIXTURE.name,
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        ).status_code == 200

        turns_path = f"/api/review/sessions/{session_id}/turns"
        question = "Must every connected object satisfy the temporary topology rule?"
        paused = client.post(
            turns_path,
            json={"request_id": "gate-first", "question": question},
        ).json()
        assert paused["status"] == "paused"
        assert paused["events"][-1]["type"] == "review-required"
        confirmation = paused["result"]["datalog_confirmation"]
        assert confirmation["review_status"] == "pending"
        assert confirmation["plain_language_meaning"]
        assert confirmation["generated_datalog"]
        assert confirmation["scope"]

        resumed = client.post(
            f"{turns_path}/{paused['turn_id']}/datalog-review",
            json={
                "decision": "confirm",
                "proposal_result": confirmation["proposal_result"],
            },
        ).json()
        assert resumed["status"] == "completed"
        assert resumed["result"]["status"] == "answered"
        assert resumed["result"]["evidence"]["items"]

        second = client.post(
            turns_path,
            json={"request_id": "gate-second", "question": question},
        ).json()
        assert second["turn_id"] != paused["turn_id"]
        assert second["status"] == "paused", (
            "a later propose_temporary_datalog call must require its own "
            "confirmation; no session-level skip may exist"
        )


def test_cancel_during_active_execution_is_not_overwritten() -> None:
    """A cancel that arrives while execute() is still running must leave the turn
    permanently canceled; start() must not overwrite it with the result on return.

    Race window: begin() saves status=active, then execute() blocks.  cancel()
    reads active, writes canceled.  When execute() returns, start() must re-read
    the disk state and respect the terminal cancellation rather than saving the
    result on top of it.
    """
    import hashlib
    import threading

    session_id = "race-session"
    request_id = "race-request"
    # Pre-compute the turn_id using the same formula as TurnLifecycleStore.start()
    turn_id = hashlib.sha256(
        f"{session_id}\n{request_id}".encode("utf-8")
    ).hexdigest()[:20]

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        store = TurnLifecycleStore(root)

        execute_started = threading.Event()
        cancel_done = threading.Event()

        def slow_execute() -> dict[str, object]:
            execute_started.set()
            cancel_done.wait(timeout=5.0)  # block until cancel has been written
            return {
                "status": "answered",
                "answer_text": "Too late — should be discarded.",
                "evidence_references": [],
                "evidence_highlight": {},
                "conversation_state": [],
            }

        errors: list[Exception] = []

        def do_cancel() -> None:
            execute_started.wait(timeout=5.0)
            try:
                store.cancel(session_id=session_id, turn_id=turn_id)
            except Exception as exc:
                errors.append(exc)
            finally:
                cancel_done.set()

        cancel_thread = threading.Thread(target=do_cancel, daemon=True)
        cancel_thread.start()

        final = store.start(
            session_id=session_id,
            request_id=request_id,
            question="A slow question",
            execute=slow_execute,
        )
        cancel_thread.join(timeout=5.0)

        assert not errors, errors
        # start() must return the canceled state, not the result
        assert final["status"] == "canceled", f"expected canceled, got {final['status']}"
        # Disk state must also be canceled — not overwritten
        reloaded = TurnLifecycleStore(root).get(session_id=session_id, turn_id=turn_id)
        assert reloaded is not None
        assert reloaded["status"] == "canceled"
        assert reloaded["events"][-1]["type"] == "cancellation"
        assert "answer_text" not in str(reloaded.get("result", ""))


def test_cancel_during_resumed_execution_is_not_overwritten() -> None:
    """A cancel that arrives while a resumed execute() is still running must leave
    the turn permanently canceled; resume() must not overwrite it with the result.

    Race window: resume() saves status=active and releases the lock, then
    execute() blocks.  cancel() reads active, writes canceled.  When execute()
    returns, resume() must re-read the disk state and respect the terminal
    cancellation rather than saving completion on top of it.
    """
    import hashlib
    import threading

    session_id = "resume-race-session"
    request_id = "resume-race-request"
    turn_id = hashlib.sha256(
        f"{session_id}\n{request_id}".encode("utf-8")
    ).hexdigest()[:20]

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        store = TurnLifecycleStore(root)

        paused = store.start(
            session_id=session_id,
            request_id=request_id,
            question="Needs confirmation",
            execute=lambda: {
                "status": "needs_datalog_confirmation",
                "datalog_confirmation": {},
                "evidence_references": [],
                "evidence_highlight": {},
            },
        )
        assert paused["status"] == "paused"

        execute_started = threading.Event()
        cancel_done = threading.Event()

        def slow_execute() -> dict[str, object]:
            execute_started.set()
            cancel_done.wait(timeout=5.0)
            return {
                "status": "answered",
                "answer_text": "Too late — should be discarded.",
                "evidence_references": [],
                "evidence_highlight": {},
            }

        errors: list[Exception] = []

        def do_cancel() -> None:
            execute_started.wait(timeout=5.0)
            try:
                store.cancel(session_id=session_id, turn_id=turn_id)
            except Exception as exc:
                errors.append(exc)
            finally:
                cancel_done.set()

        cancel_thread = threading.Thread(target=do_cancel, daemon=True)
        cancel_thread.start()

        final = store.resume(
            session_id=session_id,
            turn_id=turn_id,
            execute=slow_execute,
        )
        cancel_thread.join(timeout=5.0)

        assert not errors, errors
        assert final is not None
        assert final["status"] == "canceled", f"expected canceled, got {final['status']}"
        reloaded = TurnLifecycleStore(root).get(session_id=session_id, turn_id=turn_id)
        assert reloaded is not None
        assert reloaded["status"] == "canceled"
        assert reloaded["events"][-1]["type"] == "cancellation"
        assert "answer_text" not in str(reloaded.get("result", ""))


def test_bundled_pump_check_command_runs_rule_pack_inside_turn() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        provider = CountingProvider()
        app = create_review_api_app(
            artifact_root=root, qa_provider_factory=lambda: provider
        )
        client = TestClient(app)
        session_id = "pump-check-session"
        prepared = client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": E06_FIXTURE.name,
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        assert prepared.status_code == 200

        path = f"/api/review/sessions/{session_id}/turns"
        body = {
            "request_id": "pump-check-1",
            "question": "Run the bundled pump discharge check.",
        }
        first = client.post(path, json=body).json()

        # The command executes the trusted rule pack, not the QA provider.
        assert provider.calls == 0
        assert first["status"] == "completed"
        assert first["result"]["result_artifact"]["kind"] == "rule_pack_result"
        assert first["result"]["rule_id"] == "pump_discharge_check_valve"

        # Duplicate request replays the persisted turn without re-execution.
        duplicate = client.post(path, json=body).json()
        assert duplicate == first


class _MultiRoundProvider:
    """Calls a tool twice before answering, to exercise round-progress events."""

    def __init__(self) -> None:
        self.calls = 0

    def complete_with_tools(self, *, messages, tools):  # type: ignore[no-untyped-def]
        from pydexpi_datalog.qa.grounded_qa_harness import ToolCall

        self.calls += 1
        if self.calls <= 2:
            return ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": "pump"},
                tool_call_id=f"call-{self.calls}",
            )
        return FinalAnswer(answer_text="Found it after two rounds.")


def test_multi_round_turn_persists_live_round_progress_events() -> None:
    """Regression: the tool-calling loop used to report nothing while running,
    leaving the frontend's poll-while-waiting loop with a static placeholder
    for the whole (potentially long, multi-round) turn. Each round with an
    active tool call must now append its own progress event as it happens."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        provider = _MultiRoundProvider()
        app = create_review_api_app(
            artifact_root=root, qa_provider_factory=lambda: provider
        )
        client = TestClient(app)
        session_id = "multi-round-session"
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
            path, json={"request_id": "multi-round-1", "question": "Hello"}
        ).json()

        assert first["status"] == "completed"
        round_events = [
            event
            for event in first["events"]
            if event["type"] == "tool-progress" and event["data"].get("status") == "round"
        ]
        assert [event["data"]["round"] for event in round_events] == [1, 2]
        assert [event["data"]["tool_name"] for event in round_events] == [
            "find_equipment",
            "find_equipment",
        ]
        assert all(event["data"]["max_rounds"] == 20 for event in round_events)
