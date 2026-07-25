from __future__ import annotations

from pathlib import Path
import tempfile

from fastapi.testclient import TestClient

from pydexpi_datalog.qa.grounded_qa_harness import FinalAnswer
from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.web.review_api import create_review_api_app
from pydexpi_datalog.workflow.artifact_store import LocalArtifactStore
from pydexpi_datalog.web.turn_lifecycle import TurnLifecycleStore, compute_turn_id
from pydexpi_datalog.workflow.principal import LOCAL_PRINCIPAL


STRUCTURED_INTENT = {
    "source_classes": ["TopologyObject"],
    "target_classes": ["TopologyObject"],
    "source_role": "connected_object",
    "target_role": "answer_object",
    "graph_scope": "all_topology",
    "direction": "undirected",
    "quantifier": "all",
    "negated": False,
    "output_obligations": ["answer_ids"],
}


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
        store = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir)))
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


def test_template_trace_is_rendered_as_structured_lifecycle_events() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        # The API scopes storage by the default local workspace, so a store
        # built directly here must write where the API will read.
        workspace_root = root / LOCAL_PRINCIPAL.workspace
        store = TurnLifecycleStore(LocalArtifactStore(workspace_root))

        turn = store.start(
            session_id="trace-session",
            request_id="trace-request",
            question="Which equipment lacks a path to a pump?",
            execute=lambda: {
                "status": "answered",
                "answer_text": "Tank T-101 lacks a path to a pump.",
                "evidence_references": ["tank-t101"],
                "trace_events": [
                    {
                        "event": "template_proposed",
                        "template_id": "equipment_without_pump_path",
                    },
                    {
                        "event": "template_validated",
                        "template_id": "equipment_without_pump_path",
                        "outcome": "accepted",
                    },
                    {
                        "event": "template_executed",
                        "template_id": "equipment_without_pump_path",
                        "engine": "souffle",
                    },
                    {
                        "event": "result_observed",
                        "verdict": "violation_found",
                        "witness_count": 1,
                    },
                ],
            },
        )

        trace = [
            event["data"]
            for event in turn["events"]
            if event["type"] == "execution-trace"
        ]
        assert [event["kind"] for event in trace] == [
            "grounded_qa.routing.template_proposed",
            "grounded_qa.validation.template",
            "grounded_qa.execution.template",
            "grounded_qa.evidence.result_observed",
        ]
        assert all(event["schema_version"] == 1 for event in trace)
        assert all(len(event["summary"]) <= 160 for event in trace)
        assert trace[-1]["evidence_references"] == ["tank-t101"]
        assert all(event["detail"]["artifact"]["path"] for event in trace)
        for event in trace:
            artifact = workspace_root / "trace-session" / event["detail"]["artifact"]["path"]
            assert artifact.is_file()
        client = TestClient(create_review_api_app(artifact_root=root))
        detail_response = client.get(
            "/api/review/sessions/trace-session/turns/"
            f"{turn['turn_id']}/trace/{trace[-1]['event_id']}"
        )
        assert detail_response.status_code == 200
        assert detail_response.json()["kind"] == (
            "grounded_qa.evidence.result_observed"
        )
        invalid_response = client.get(
            "/api/review/sessions/trace-session/turns/"
            f"{turn['turn_id']}/trace/not-an-event-id"
        )
        assert invalid_response.status_code == 404


def test_unknown_trace_activity_is_grouped_bounded_and_redacted() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        store = TurnLifecycleStore(LocalArtifactStore(root))
        repeated = [
            {
                "event": "vendor.widget.inspected",
                "status": "completed",
                "evidence_references": [f"node-{index}"],
                "system_prompt": "private instructions",
                "chain_of_thought": "private reasoning",
                "authorization": "Bearer secret-value",
                "tool_output": "x" * 10_000,
                "safe_note": "bounded extension metadata",
            }
            for index in range(30)
        ]

        turn = store.start(
            session_id="extension-trace-session",
            request_id="extension-trace-request",
            question="Inspect extension activity",
            execute=lambda: {
                "status": "answered",
                "answer_text": "Inspection complete.",
                "trace_events": repeated,
            },
        )

        trace = [
            event["data"]
            for event in turn["events"]
            if event["type"] == "execution-trace"
        ]
        assert len(trace) == 1
        assert trace[0]["kind"] == "vendor.widget.inspected"
        assert trace[0]["category"] == "activity"
        assert trace[0]["occurrence_count"] == 30
        assert trace[0]["summary"] == (
            "Recorded extension activity: vendor.widget.inspected (30 occurrences)."
        )
        assert (
            trace[0]["evidence_references"]
            == sorted(f"node-{index}" for index in range(30))[:25]
        )
        artifact_path = (
            root / "extension-trace-session" / trace[0]["detail"]["artifact"]["path"]
        )
        artifact_text = artifact_path.read_text(encoding="utf-8")
        assert len(__import__("json").loads(artifact_text)["occurrences"]) == 20
        for private_field in (
            "system_prompt",
            "chain_of_thought",
            "authorization",
            "tool_output",
            "safe_note",
        ):
            assert private_field not in artifact_text


def test_trace_preserves_supported_status_and_ignores_malformed_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir) / "sessions"))
        turn = store.start(
            session_id="status-trace-session",
            request_id="status-trace-request",
            question="Show blocked extension activity",
            execute=lambda: {
                "status": "answered",
                "answer_text": "Activity recorded.",
                "trace_events": [
                    {
                        "event": "vendor.widget.blocked",
                        "status": "running",
                        "outcome": ["malformed"],
                        "template_id": "unsafe secret value",
                    },
                    {
                        "event": "vendor.widget.blocked",
                        "status": "blocked",
                        "outcome": ["malformed"],
                        "template_id": "unsafe secret value",
                    },
                ],
            },
        )

        trace = next(
            event["data"]
            for event in turn["events"]
            if event["type"] == "execution-trace"
        )
        assert trace["status"] == "blocked"
        assert trace["occurrence_count"] == 2
        assert trace["summary"] == (
            "Recorded extension activity: vendor.widget.blocked (2 occurrences)."
        )


def test_trace_rendering_is_independent_of_capability_review_state() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir) / "sessions"))
        turn = store.start(
            session_id="review-trace-session",
            request_id="review-trace-request",
            question="Run a capability requiring review",
            execute=lambda: {
                "status": "needs_datalog_confirmation",
                "trace_events": [
                    {
                        "event": "vendor.capability.blocked",
                        "status": "blocked",
                    }
                ],
            },
        )

        assert turn["status"] == "paused"
        event_types = [event["type"] for event in turn["events"]]
        assert "execution-trace" in event_types
        assert event_types.index("execution-trace") < event_types.index(
            "review-required"
        )


def test_progress_events_carry_sanitized_tool_arguments_and_bounded_reasoning() -> None:
    """The live progress channel surfaces what the model is doing (tool
    arguments) and why (reasoning) -- bounded and redacted with the same
    discipline as the governed execution trace, and omitted entirely when a
    provider supplies nothing (no fabrication)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir) / "sessions"))
        session_id = "progress-session"
        request_id = "progress-request"
        turn_id = compute_turn_id(session_id, request_id)

        def execute() -> dict[str, object]:
            store.append_progress(
                session_id=session_id,
                turn_id=turn_id,
                round_index=1,
                max_rounds=20,
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every tank reach a pump?",
                    "credential": "sk-secret-value",
                    "authorization": "Bearer secret-value",
                    "generated_datalog": "x" * 10_000,
                },
                reasoning="r" * 10_000,
            )
            store.append_progress(
                session_id=session_id,
                turn_id=turn_id,
                round_index=2,
                max_rounds=20,
                tool_name="find_equipment",
            )
            return {"status": "answered", "answer_text": "Done."}

        turn = store.start(
            session_id=session_id,
            request_id=request_id,
            question="Must every tank reach a pump?",
            execute=execute,
        )

        progress = [
            event["data"]
            for event in turn["events"]
            if event["type"] == "tool-progress"
            and event["data"].get("status") == "round"
        ]
        assert len(progress) == 2
        enriched, bare = progress

        tool_input = enriched["tool_input"]
        assert tool_input["request"] == "Must every tank reach a pump?"
        assert "credential" not in tool_input
        assert "authorization" not in tool_input
        assert len(tool_input["generated_datalog"]) <= 400
        assert "sk-secret-value" not in str(enriched)
        assert "Bearer secret-value" not in str(enriched)
        assert 0 < len(enriched["reasoning"]) <= 2_000

        assert "tool_input" not in bare
        assert "reasoning" not in bare


def test_progress_events_preserve_scalars_inside_nested_tool_arguments() -> None:
    """The depth cap bounds container nesting, not leaf scalars: class-name
    strings inside lists inside the bindings mapping must survive into the
    persisted progress event, or the live channel misleads the reviewer with
    empty lists while the real tool call carried the full bindings."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir) / "sessions"))
        session_id = "nested-progress-session"
        request_id = "nested-progress-request"
        turn_id = compute_turn_id(session_id, request_id)

        def execute() -> dict[str, object]:
            store.append_progress(
                session_id=session_id,
                turn_id=turn_id,
                round_index=1,
                max_rounds=20,
                tool_name="execute_bundled_query_template",
                tool_input={
                    "request": "Find equipment without a pump path.",
                    "template_id": "equipment_without_pump_path",
                    "bindings": {
                        "pump_classes": ["CentrifugalPump", "ReciprocatingPump"],
                        "equipment_classes": ["PlateHeatExchanger", "Tank"],
                        "scope": "piping",
                        "negated": True,
                    },
                },
            )
            return {"status": "answered", "answer_text": "Done."}

        turn = store.start(
            session_id=session_id,
            request_id=request_id,
            question="Find equipment without a pump path.",
            execute=execute,
        )

        progress = [
            event["data"]
            for event in turn["events"]
            if event["type"] == "tool-progress"
            and event["data"].get("status") == "round"
        ]
        assert len(progress) == 1
        bindings = progress[0]["tool_input"]["bindings"]
        assert bindings["pump_classes"] == ["CentrifugalPump", "ReciprocatingPump"]
        assert bindings["equipment_classes"] == ["PlateHeatExchanger", "Tank"]
        assert bindings["scope"] == "piping"
        assert bindings["negated"] is True


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
            __import__("json").loads(line)["type"] for line in stream.text.splitlines()
        ] == ["evidence", "completion"]


def test_active_turn_cancellation_is_terminal_persisted_and_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        store = TurnLifecycleStore(LocalArtifactStore(root))
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
        reloaded = TurnLifecycleStore(LocalArtifactStore(root)).get(
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
        store = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir) / "sessions"))

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
        store = TurnLifecycleStore(LocalArtifactStore(Path(tmp_dir) / "sessions"))
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
        assert (
            client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": E06_FIXTURE.name,
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            ).status_code
            == 200
        )

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
        canceled = client.post(f"{turns_path}/{cancelable['turn_id']}/cancel").json()
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
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template covers this rule.",
                    "structured_intent": STRUCTURED_INTENT,
                },
                tool_call_id="no-fit-1",
            )
        if self._step == 1:
            self._step += 1
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every connected object satisfy the temporary topology rule?",
                    "generated_datalog": encode_structured_intent_program(
                        (
                            ".decl answer(x:symbol)\n.output answer\n"
                            f'answer("{self._answer_id}").'
                        ),
                        STRUCTURED_INTENT,
                    ),
                    "formal_restatement": "Return objects matching the temporary topology rule.",
                    "faithfulness_review": {
                        "status": "faithful",
                        "back_translated_intent": STRUCTURED_INTENT,
                        "diagnostics": [],
                    },
                    "resolved_identity_ids": [self._answer_id],
                },
                tool_call_id="proposal-1",
            )
        return FinalAnswer(
            answer_text="Every connected object satisfies the temporary topology rule."
        )


def test_temporary_datalog_turn_completes_automatically_without_confirmation() -> None:
    """Released lifecycle: gate-passing temporary Datalog answers the turn
    without a confirmation pause or review-required event."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        holder: dict[str, str] = {}
        client = TestClient(
            create_review_api_app(
                artifact_root=root,
                qa_provider_factory=lambda: _DatalogProposalProvider(
                    holder["answer_id"]
                ),
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
        completed = client.post(
            turns_path,
            json={
                "request_id": "datalog-request",
                "question": "Must every connected object satisfy the temporary topology rule?",
            },
        ).json()

        assert completed["status"] == "completed"
        assert "datalog_confirmation" not in completed.get("result", {})
        assert [event["type"] for event in completed["events"]].count("completion") == 1
        assert "review-required" not in {
            event["type"] for event in completed["events"]
        }
        assert completed["result"]["status"] == "answered"
        assert "temporary topology rule" in completed["result"]["answer_text"].lower()


def test_temporary_datalog_completed_turn_cancel_is_idempotent() -> None:
    """Canceling an already-completed automatic temporary-Datalog turn keeps
    the turn terminal without inventing a confirmation pause."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        holder: dict[str, str] = {}
        client = TestClient(
            create_review_api_app(
                artifact_root=root,
                qa_provider_factory=lambda: _DatalogProposalProvider(
                    holder["answer_id"]
                ),
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
        completed = client.post(
            turns_path,
            json={
                "request_id": "datalog-cancel-request",
                "question": "Must every connected object satisfy the temporary topology rule?",
            },
        ).json()
        assert completed["status"] == "completed"
        canceled = client.post(f"{turns_path}/{completed['turn_id']}/cancel").json()
        assert canceled["status"] == "completed"
        assert "datalog_confirmation" not in canceled.get("result", {})


def test_default_provider_rule_question_executes_automatically_without_trust_escalation() -> (
    None
):
    """Released default provider: a rule-like question completes with automatic
    temporary Datalog execution and never grants reusable-rule trust."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        client = TestClient(create_review_api_app(artifact_root=root))
        session_id = "default-gate-session"
        assert (
            client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": E06_FIXTURE.name,
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            ).status_code
            == 200
        )

        turns_path = f"/api/review/sessions/{session_id}/turns"
        question = "Must every connected object satisfy the temporary topology rule?"
        first = client.post(
            turns_path,
            json={"request_id": "gate-first", "question": question},
        ).json()
        assert first["status"] == "completed"
        assert first["result"]["status"] == "answered"
        assert "datalog_confirmation" not in first["result"]
        route_artifact = first["result"].get("route_artifact")
        if isinstance(route_artifact, dict):
            assert route_artifact.get("trust") == {
                "temporary": True,
                "reusable_rule_trust": False,
                "promotion": "separate_explicit_authoring_action",
            }

        second = client.post(
            turns_path,
            json={"request_id": "gate-second", "question": question},
        ).json()
        assert second["turn_id"] != first["turn_id"]
        assert second["status"] == "completed"
        assert "datalog_confirmation" not in second["result"]


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
    turn_id = hashlib.sha256(f"{session_id}\n{request_id}".encode("utf-8")).hexdigest()[
        :20
    ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        store = TurnLifecycleStore(LocalArtifactStore(root))

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
        assert final["status"] == "canceled", (
            f"expected canceled, got {final['status']}"
        )
        # Disk state must also be canceled — not overwritten
        reloaded = TurnLifecycleStore(LocalArtifactStore(root)).get(session_id=session_id, turn_id=turn_id)
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
    turn_id = hashlib.sha256(f"{session_id}\n{request_id}".encode("utf-8")).hexdigest()[
        :20
    ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "sessions"
        store = TurnLifecycleStore(LocalArtifactStore(root))

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
        assert final["status"] == "canceled", (
            f"expected canceled, got {final['status']}"
        )
        reloaded = TurnLifecycleStore(LocalArtifactStore(root)).get(session_id=session_id, turn_id=turn_id)
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
            if event["type"] == "tool-progress"
            and event["data"].get("status") == "round"
        ]
        assert [event["data"]["round"] for event in round_events] == [1, 2]
        assert [event["data"]["tool_name"] for event in round_events] == [
            "find_equipment",
            "find_equipment",
        ]
        assert all(event["data"]["max_rounds"] == 20 for event in round_events)
