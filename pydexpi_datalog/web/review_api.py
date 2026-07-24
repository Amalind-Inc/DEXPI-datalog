from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ..llm.byok_provider import OPENAI_COMPATIBLE_BASE_URLS, create_byok_provider
from ..llm.model_access import ModelProvider
from ..qa.grounded_qa_harness import (
    DEFAULT_MAX_CONVERSATION_TURNS,
    QATurnProvider,
    RunConstraints,
    ScriptedQATurnProvider,
)
from ..qa.ollama_qa_provider import OllamaQATurnProvider
from ..qa.openai_compatible_qa_provider import OpenAICompatibleQATurnProvider
from ..verification.authored_rule_pack import AuthoredRulePackError, AuthoredRulePackStore
from ..verification.bundled_rule_pack import bundled_rule_packs
from ..workflow.review_session import PreparationLimits
from .chainlit_review_flow import ChainlitReviewFlow
from .turn_lifecycle import TurnLifecycleStore, compute_turn_id


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
    max_conversation_turns: int = DEFAULT_MAX_CONVERSATION_TURNS,
) -> FastAPI:
    """Create the OSS v1 review workflow API."""

    app = FastAPI(title="pyDEXPI Datalog Review API")
    flow = ChainlitReviewFlow(
        artifact_root=artifact_root,
        limits=preparation_limits,
        max_conversation_turns=max_conversation_turns,
    )
    turns = TurnLifecycleStore(artifact_root)
    authored_packs = AuthoredRulePackStore(artifact_root / "authored_rule_packs")

    # Test hermeticity: PYDEXPI_QA_PROVIDER=scripted forces the deterministic,
    # zero-LLM providers regardless of session provider-settings. This lets the
    # e2e stack exercise the real turn transport without any real model call,
    # while a developer's .env.local can still drive a live LLM manually.
    force_scripted = os.environ.get("PYDEXPI_QA_PROVIDER", "").lower() == "scripted"

    def _resolve_provider(session_id: str) -> ModelProvider:
        if model_provider_factory is not None:
            return model_provider_factory()
        if force_scripted:
            return TopologyAwareFakeModelProvider()
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
        if force_scripted:
            step_delay_ms = float(os.environ.get("PYDEXPI_QA_SCRIPTED_STEP_DELAY_MS", "0"))
            return ScriptedQATurnProvider(step_delay_seconds=step_delay_ms / 1000)
        settings = flow.provider_settings_state(session_id)
        provider = str(settings.get("provider", ""))
        if not settings.get("configured") or provider not in OPENAI_COMPATIBLE_BASE_URLS:
            # Providers outside the OpenAI-compatible tool-calling family (e.g.
            # anthropic, gemini) have no QATurnProvider implementation yet and
            # fall back to the deterministic stub rather than silently
            # mismatching a different wire format.
            return ScriptedQATurnProvider()
        base_url = str(settings.get("base_url") or OPENAI_COMPATIBLE_BASE_URLS[provider])
        if provider == "ollama":
            return OllamaQATurnProvider(model=str(settings["model"]), base_url=base_url)
        return OpenAICompatibleQATurnProvider(
            provider=provider,
            model=str(settings["model"]),
            base_url=base_url,
            credential=flow.local_credential_for_test(session_id),
        )

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

    @app.get("/api/review/sessions/{session_id}/rule-packs")
    def list_rule_packs(session_id: str) -> dict[str, object]:
        return flow.list_rule_packs(
            session_id=session_id, authored_packs=authored_packs.list_packs()
        )

    @app.get("/api/rule-packs")
    def list_all_rule_packs() -> dict[str, object]:
        return {
            "packs": [
                *[_serialize_pack(pack, source="system") for pack in bundled_rule_packs()],
                *[
                    _serialize_pack(pack, source="user")
                    for pack in authored_packs.list_packs()
                ],
            ]
        }

    @app.post("/api/rule-packs")
    def create_rule_pack(body: dict[str, object]) -> dict[str, object]:
        markdown = _required_string(body, "markdown")
        try:
            pack = authored_packs.ingest(markdown)
        except AuthoredRulePackError as error:
            status = 409 if error.code.endswith("collision") or error.code.endswith(
                "already_exists"
            ) else 400
            raise HTTPException(
                status_code=status,
                detail={"error": {"code": error.code, "message": error.message}},
            ) from error
        return {"pack": _serialize_pack(pack, source="user")}

    @app.post("/api/rule-packs/{pack_id}/promote")
    def promote_advisory_clause(
        pack_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        advisory_title = _required_string(body, "advisory_title")
        try:
            proposal = authored_packs.propose_promotion(
                pack_id=pack_id, advisory_title=advisory_title
            )
        except AuthoredRulePackError as error:
            status = 404 if error.code.endswith("not_found") else 400
            raise HTTPException(
                status_code=status,
                detail={"error": {"code": error.code, "message": error.message}},
            ) from error
        except ValueError as error:
            raise _bad_request(str(error)) from error
        return proposal

    @app.post("/api/rule-packs/{pack_id}/promote/confirm")
    def confirm_promoted_rule(
        pack_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        draft = body.get("draft")
        if not isinstance(draft, dict):
            raise _bad_request("request body must include a draft object")
        try:
            pack = authored_packs.confirm_promotion(pack_id=pack_id, draft=draft)
        except AuthoredRulePackError as error:
            if error.code.endswith("not_found"):
                status = 404
            elif error.code.endswith("already_exists"):
                status = 409
            else:
                status = 400
            raise HTTPException(
                status_code=status,
                detail={"error": {"code": error.code, "message": error.message}},
            ) from error
        return {"pack": _serialize_pack(pack, source="user")}

    @app.post("/api/review/sessions/{session_id}/rule-packs/{pack_id}/load")
    def load_rule_pack(session_id: str, pack_id: str) -> dict[str, object]:
        return _call_ready(
            lambda: flow.load_rule_pack(
                session_id=session_id,
                pack_id=pack_id,
                authored_packs=authored_packs.list_packs(),
            )
        )

    @app.post("/api/review/sessions/{session_id}/rule-packs/{pack_id}/unload")
    def unload_rule_pack(session_id: str, pack_id: str) -> dict[str, object]:
        return _call_ready(
            lambda: flow.unload_rule_pack(
                session_id=session_id,
                pack_id=pack_id,
                authored_packs=authored_packs.list_packs(),
            )
        )

    @app.get("/api/review/sessions/{session_id}/rule-pack-results")
    def list_rule_pack_results(session_id: str) -> dict[str, object]:
        return _call_ready(
            lambda: flow.rule_pack_results_state(session_id=session_id)
        )

    @app.post("/api/review/sessions/{session_id}/rule-packs/{pack_id}/run")
    def run_rule_pack(session_id: str, pack_id: str) -> dict[str, object]:
        return _call_ready(
            lambda: flow.run_rule_pack(
                session_id=session_id,
                pack_id=pack_id,
                authored_packs=authored_packs.list_packs(),
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

    BUNDLED_PUMP_CHECK_COMMAND = "run the bundled pump discharge check."

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

        turn_id = compute_turn_id(session_id, request_id)

        def _report_round(
            round_index: int,
            max_rounds: int,
            tool_name: str | None,
            tool_input: dict[str, object] | None = None,
            reasoning: str | None = None,
        ) -> None:
            turns.append_progress(
                session_id=session_id,
                turn_id=turn_id,
                round_index=round_index,
                max_rounds=max_rounds,
                tool_name=tool_name,
                tool_input=tool_input,
                reasoning=reasoning,
            )

        steering_constraints = _parse_run_constraints(body.get("constraints"))

        def _steering() -> str | None:
            return turns.steering_directive(session_id=session_id, turn_id=turn_id)

        def _execute() -> dict[str, object]:
            # The bundled pump check is a trusted rule-pack execution command,
            # not a QA question; run it inside the turn so dedupe, replay, and
            # cancellation apply uniformly.
            if question.strip().lower() == BUNDLED_PUMP_CHECK_COMMAND:
                return flow.execute_selected_rule_pack_query(
                    session_id=session_id,
                    rule_id="pump_discharge_check_valve",
                )
            return flow.run_qa_turn(
                session_id=session_id,
                question=question,
                qa_provider=_resolve_qa_provider(session_id),
                conversation=conversation_turns,
                on_round=_report_round,
                steering=_steering,
                constraints=steering_constraints,
            )

        return _call_ready(
            lambda: turns.start(
                session_id=session_id,
                request_id=request_id,
                question=question,
                execute=_execute,
            )
        )

    @app.get("/api/review/sessions/{session_id}/turns/{turn_id}")
    def get_turn(session_id: str, turn_id: str) -> dict[str, object]:
        turn = turns.get(session_id=session_id, turn_id=turn_id)
        if turn is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "turn.not_found", "message": "Turn not found."}})
        return turn

    @app.get(
        "/api/review/sessions/{session_id}/turns/{turn_id}/trace/{event_id}"
    )
    def get_turn_trace_detail(
        session_id: str, turn_id: str, event_id: str
    ) -> dict[str, object]:
        detail = turns.get_trace_detail(
            session_id=session_id,
            turn_id=turn_id,
            event_id=event_id,
        )
        if detail is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "trace_detail_not_found",
                        "message": "Turn trace detail not found.",
                    }
                },
            )
        return detail

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

    @app.post("/api/review/sessions/{session_id}/turns/{turn_id}/answer-now")
    def answer_now_turn(session_id: str, turn_id: str) -> dict[str, object]:
        turn = turns.request_answer_now(session_id=session_id, turn_id=turn_id)
        if turn is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "turn.not_found", "message": "Turn not found."}
                },
            )
        return turn

    @app.post("/api/review/sessions/{session_id}/turns/{turn_id}/direction-review")
    def resume_direction_review(
        session_id: str, turn_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        decisions = _direction_review_decisions(body)
        decision = _optional_string(body, "decision")
        review_key = _optional_string(body, "review_key")
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
                decisions=decisions,
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
        decisions = _direction_review_decisions(body)
        decision = _optional_string(body, "decision")
        review_key = _optional_string(body, "review_key")
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
                decisions=decisions,
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


def _serialize_pack(pack: dict[str, object], *, source: str) -> dict[str, object]:
    return {
        "pack_id": pack["pack_id"],
        "version": pack["version"],
        "title": pack["title"],
        "authoritative": bool(pack["authoritative"]) and source == "system",
        "trust_notice": pack["trust_notice"],
        "source": source,
        "markdown": pack["markdown"],
        "advisory_guidance": pack.get("advisory_guidance", []),
        "rules": [
            {
                "rule_id": rule["rule_id"],
                "title": rule["title"],
                "outcomes": rule["outcomes"],
                "restatement": rule["restatement"],
                "executable_logic": rule["executable_logic"],
                "trust": rule.get(
                    "trust",
                    "author_confirmed" if source == "user" else "bundled",
                ),
            }
            for rule in pack["rules"]  # type: ignore[union-attr]
        ],
    }


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


def _optional_string(body: dict[str, object], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise _bad_request(f"request body {key} must be a non-empty string")
    return value


def _direction_review_decisions(body: dict[str, object]) -> list[dict[str, object]] | None:
    raw = body.get("direction_reviews")
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise _bad_request("request body direction_reviews must be a non-empty list")
    decisions: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise _bad_request("each direction_reviews item must be an object")
        review_key = item.get("review_key")
        decision = item.get("decision")
        if not isinstance(review_key, str) or not review_key:
            raise _bad_request("each direction_reviews item must include review_key")
        if decision not in {"confirm", "reverse", "unknown"}:
            raise _bad_request("each direction_reviews item must include decision confirm, reverse, or unknown")
        decisions.append({"review_key": review_key, "decision": decision})
    return decisions


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


def _positive_number(raw: dict[str, object], key: str) -> float | None:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def _parse_run_constraints(raw: object) -> RunConstraints | None:
    """Parse optional user answer-constraints from a turn request body. Values
    are advisory tightenings only; the harness clamps them against operational
    ceilings and never widens (bead 3qo.9.8). Returns None when none are set."""
    if not isinstance(raw, dict):
        return None
    turns_value = _positive_number(raw, "turns")
    max_rounds = int(turns_value) if turns_value is not None else None
    capabilities_raw = raw.get("capabilities")
    capabilities = (
        frozenset(item for item in capabilities_raw if isinstance(item, str))
        if isinstance(capabilities_raw, list)
        else None
    )
    constraints = RunConstraints(
        max_rounds=max_rounds,
        max_duration_seconds=_positive_number(raw, "duration_seconds"),
        max_provider_cost=_positive_number(raw, "provider_cost"),
        allowed_capabilities=capabilities,
    )
    if (
        constraints.max_rounds is None
        and constraints.max_duration_seconds is None
        and constraints.max_provider_cost is None
        and constraints.allowed_capabilities is None
    ):
        return None
    return constraints


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
