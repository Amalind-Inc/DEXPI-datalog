from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ..llm.byok_provider import create_byok_provider
from ..llm.model_access import ModelProvider
from ..qa.grounded_qa_harness import QATurnProvider, ScriptedQATurnProvider
from ..qa.ollama_qa_provider import OllamaQATurnProvider
from ..workflow.review_session import PreparationLimits
from .chainlit_review_flow import ChainlitReviewFlow
from .turn_lifecycle import TurnLifecycleStore


class TopologyAwareFakeModelProvider:
    provider = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def complete(self, *, request: str, context: dict[str, object]) -> str:
        self.requests.append({"request": request, "context": context})
        if context.get("task") == "grounded_logic_answer":
            evidence_items = context.get("evidence_items")
            if isinstance(evidence_items, list) and evidence_items:
                item = evidence_items[0]
                if isinstance(item, dict):
                    label = str(item.get("label") or item.get("id"))
                    topology_id = str(item.get("id"))
                    return json.dumps(
                        {
                            "answer_text": (
                                "The deterministic Datalog result matches "
                                f"{label} ({topology_id}) for this request."
                            )
                        }
                    )
            return json.dumps(
                {
                    "answer_text": "The deterministic Datalog result did not match any topology evidence."
                }
            )

        answer_id = self._answer_id(context)
        return json.dumps(
            {
                "generated_datalog": (
                    ".decl answer(x:symbol)\n"
                    ".output answer\n"
                    f"answer({json.dumps(answer_id)})."
                ),
                "formal_restatement": (
                    "Return deterministic topology evidence for the confirmed request."
                ),
            }
        )

    def _answer_id(self, context: dict[str, object]) -> str:
        source_scope_ids = context.get("source_scope_ids")
        if isinstance(source_scope_ids, list):
            for item in source_scope_ids:
                if isinstance(item, str) and item:
                    return item

        topology_nodes = context.get("topology_nodes")
        if isinstance(topology_nodes, list):
            for item in topology_nodes:
                if isinstance(item, dict):
                    node_id = item.get("id")
                    if isinstance(node_id, str) and node_id:
                        return node_id

        return "__missing_topology_answer__"


def create_review_api_app(
    *,
    artifact_root: Path,
    model_provider_factory: Callable[[], ModelProvider] | None = None,
    qa_provider_factory: Callable[[], QATurnProvider] | None = None,
    preparation_limits: PreparationLimits | None = None,
) -> FastAPI:
    """Create the OSS v1 review workflow API."""

    app = FastAPI(title="pyDEXPI Datalog Review API")
    flow = ChainlitReviewFlow(artifact_root=artifact_root, limits=preparation_limits)
    turns = TurnLifecycleStore(artifact_root)

    def _resolve_provider(session_id: str) -> ModelProvider:
        if model_provider_factory is not None:
            return model_provider_factory()
        settings = flow.provider_settings_state(session_id)
        credential = flow.local_credential_for_test(session_id)
        if credential and settings.get("configured"):
            return create_byok_provider(
                provider=str(settings["provider"]),
                model=str(settings["model"]),
                credential=credential,
            )
        return TopologyAwareFakeModelProvider()

    def _resolve_qa_provider(session_id: str) -> QATurnProvider:
        if qa_provider_factory is not None:
            return qa_provider_factory()
        settings = flow.provider_settings_state(session_id)
        if settings.get("provider") == "ollama" and settings.get("configured"):
            return OllamaQATurnProvider(
                model=str(settings["model"]),
                base_url=str(settings.get("base_url", "http://localhost:11434/v1")),
            )
        return ScriptedQATurnProvider()

    @app.exception_handler(HTTPException)
    def http_exception_handler(
        _request: object, exception: HTTPException
    ) -> JSONResponse:
        content = exception.detail
        if not isinstance(content, dict):
            content = {"error": {"code": "request.invalid", "message": str(content)}}
        return JSONResponse(status_code=exception.status_code, content=content)

    @app.post("/api/review/sessions/{session_id}/prepare")
    def prepare_session(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        filename = _filename(body, "filename")
        content = _required_string(body, "content")
        upload_dir = artifact_root / "_uploads" / session_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / filename
        upload_path.write_text(content, encoding="utf-8")
        return flow.prepare_upload(dexpi_xml_path=upload_path, session_id=session_id)

    @app.get("/api/review/sessions/{session_id}/topology")
    def topology(session_id: str) -> dict[str, object]:
        return _call_ready(lambda: flow.topology_panel_state(session_id=session_id))

    @app.put("/api/review/sessions/{session_id}/source-scope")
    def update_source_scope(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        return _call_ready(
            lambda: flow.edit_visible_source_scope(
                session_id=session_id,
                source_scope_ids=_string_list(body, "source_scope_ids"),
            )
        )

    @app.put("/api/review/sessions/{session_id}/provider-settings")
    def configure_provider(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        return _call_ready(
            lambda: flow.configure_provider_settings(
                session_id=session_id,
                provider=_required_string(body, "provider"),
                model=_required_string(body, "model"),
                credential=body.get("credential", ""),
                base_url=body.get("base_url") if isinstance(body.get("base_url"), str) else None,
            )
        )

    @app.post("/api/review/sessions/{session_id}/logic-requests/improve")
    def improve_logic_request(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        return _call_ready(
            lambda: flow.improve_logic_request(
                session_id=session_id,
                prompt=_required_string(body, "prompt"),
            )
        )

    @app.post("/api/review/sessions/{session_id}/logic-requests/confirm")
    def confirm_logic_request(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        improvement = body.get("improvement")
        if not isinstance(improvement, dict):
            raise _bad_request("request body must include an improvement object")
        return _call_ready(
            lambda: flow.accept_logic_request_refinement(
                session_id=session_id,
                improvement=improvement,
                provider=_resolve_provider(session_id),
            )
        )

    @app.post("/api/review/sessions/{session_id}/logic-requests/execute")
    def execute_logic_request(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        confirmation = body.get("confirmation")
        if not isinstance(confirmation, dict):
            raise _bad_request("request body must include a confirmation object")
        return _call_ready(
            lambda: flow.execute_confirmed_logic_request(
                session_id=session_id,
                confirmation=confirmation,
                provider=_resolve_provider(session_id),
            )
        )

    @app.post("/api/review/sessions/{session_id}/rule-pack-results")
    def execute_rule_pack_result(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        return _call_ready(
            lambda: flow.execute_selected_rule_pack_query(
                session_id=session_id,
                pack_id=str(body.get("pack_id", "demo-process-safety")),
                rule_id=_required_string(body, "rule_id"),
            )
        )

    @app.post("/api/review/sessions/{session_id}/qa-turns")
    def run_qa_turn(session_id: str, body: dict[str, object]) -> dict[str, object]:
        question = _required_string(body, "question")
        conversation = body.get("conversation")
        conversation_turns = (
            [turn for turn in conversation if isinstance(turn, dict)]
            if isinstance(conversation, list)
            else None
        )
        return _call_ready(
            lambda: flow.run_qa_turn(
                session_id=session_id,
                question=question,
                qa_provider=_resolve_qa_provider(session_id),
                conversation=conversation_turns,
            )
        )

    @app.post("/api/review/sessions/{session_id}/turns")
    def start_turn(session_id: str, body: dict[str, object]) -> dict[str, object]:
        question = _required_string(body, "question")
        request_id = _required_string(body, "request_id")
        conversation = body.get("conversation")
        conversation_turns = (
            [turn for turn in conversation if isinstance(turn, dict)]
            if isinstance(conversation, list)
            else None
        )
        return _call_ready(
            lambda: turns.start(
                session_id=session_id,
                request_id=request_id,
                question=question,
                execute=lambda: flow.run_qa_turn(
                    session_id=session_id,
                    question=question,
                    qa_provider=_resolve_qa_provider(session_id),
                    conversation=conversation_turns,
                ),
            )
        )

    @app.get("/api/review/sessions/{session_id}/turns/{turn_id}")
    def get_turn(session_id: str, turn_id: str) -> dict[str, object]:
        turn = turns.get(session_id=session_id, turn_id=turn_id)
        if turn is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "turn.not_found", "message": "Turn not found."}})
        return turn

    @app.get("/api/review/sessions/{session_id}/turns/{turn_id}/events")
    def stream_turn_events(
        session_id: str, turn_id: str, after: int = -1
    ) -> StreamingResponse:
        turn = turns.get(session_id=session_id, turn_id=turn_id)
        if turn is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "turn.not_found", "message": "Turn not found."}})
        events = turn.get("events", [])
        selected = [event for event in events if isinstance(event, dict) and int(event.get("sequence", -1)) > after] if isinstance(events, list) else []
        return StreamingResponse(
            (json.dumps(event, sort_keys=True) + "\n" for event in selected),
            media_type="application/x-ndjson",
        )

    @app.post("/api/review/sessions/{session_id}/turns/{turn_id}/cancel")
    def cancel_turn(session_id: str, turn_id: str) -> dict[str, object]:
        turn = turns.cancel(session_id=session_id, turn_id=turn_id)
        if turn is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "turn.not_found", "message": "Turn not found."}})
        return turn

    @app.post("/api/review/sessions/{session_id}/turns/{turn_id}/direction-review")
    def resume_direction_review(
        session_id: str, turn_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        decision = _required_string(body, "decision")
        review_key = _required_string(body, "review_key")
        existing = turns.get(session_id=session_id, turn_id=turn_id)
        if existing is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "turn.not_found", "message": "Turn not found."}})
        resumed = turns.resume(
            session_id=session_id,
            turn_id=turn_id,
            execute=lambda: flow.submit_direction_review(
                session_id=session_id,
                question=str(existing["question"]),
                decision=decision,
                review_key=review_key,
                qa_provider=_resolve_qa_provider(session_id),
            ),
        )
        assert resumed is not None
        return resumed

    @app.post("/api/review/sessions/{session_id}/turns/{turn_id}/datalog-review")
    def resume_datalog_review(
        session_id: str, turn_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        decision = _required_string(body, "decision")
        proposal_result = body.get("proposal_result")
        if not isinstance(proposal_result, dict):
            raise _bad_request("request body must include a proposal_result object")
        existing = turns.get(session_id=session_id, turn_id=turn_id)
        if existing is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "turn.not_found", "message": "Turn not found."}})
        resumed = turns.resume(
            session_id=session_id,
            turn_id=turn_id,
            execute=lambda: flow.submit_temporary_datalog_review(
                session_id=session_id,
                question=str(existing["question"]),
                decision=decision,
                proposal_result=proposal_result,
            ),
        )
        assert resumed is not None
        return resumed

    @app.post("/api/review/sessions/{session_id}/direction-reviews")
    def submit_direction_review(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        question = _required_string(body, "question")
        decision = _required_string(body, "decision")
        review_key = _required_string(body, "review_key")
        conversation = body.get("conversation")
        conversation_turns = (
            [turn for turn in conversation if isinstance(turn, dict)]
            if isinstance(conversation, list)
            else None
        )
        return _call_ready(
            lambda: flow.submit_direction_review(
                session_id=session_id,
                question=question,
                decision=decision,
                review_key=review_key,
                qa_provider=_resolve_qa_provider(session_id),
                conversation=conversation_turns,
            )
        )

    @app.post("/api/review/sessions/{session_id}/temporary-datalog-reviews")
    def submit_temporary_datalog_review(
        session_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        question = _required_string(body, "question")
        decision = _required_string(body, "decision")
        proposal_result = body.get("proposal_result")
        if not isinstance(proposal_result, dict):
            raise _bad_request("request body must include a proposal_result object")
        return _call_ready(
            lambda: flow.submit_temporary_datalog_review(
                session_id=session_id,
                question=question,
                decision=decision,
                proposal_result=proposal_result,
            )
        )

    @app.post("/api/review/sessions/{session_id}/exports")
    def export_session(session_id: str) -> dict[str, object]:
        export_dir = (
            artifact_root / "_exports" / session_id / f"export-{time.time_ns()}"
        )
        return _call_ready(
            lambda: flow.export_session_artifacts(
                session_id=session_id,
                export_dir=export_dir,
            )
        )

    return app


def _call_ready(action: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return action()
    except ValueError as error:
        message = str(error)
        if message.startswith("No ready topology is known"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "session.not_ready",
                        "message": message,
                    }
                },
            ) from error
        raise _bad_request(message) from error


def _required_string(body: dict[str, object], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or value == "":
        raise _bad_request(f"request body must include a non-empty {key}")
    return value


def _filename(body: dict[str, object], key: str) -> str:
    value = Path(_required_string(body, key)).name
    if value == "":
        raise _bad_request(f"request body must include a filename for {key}")
    return value


def _string_list(body: dict[str, object], key: str) -> list[str]:
    value = body.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _bad_request(f"request body must include {key} as a list of strings")
    return list(value)


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "request.invalid",
                "message": message,
            }
        },
    )
