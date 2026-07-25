from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..llm.logic_requests import (
    parse_model_draft_response,
    route_logic_request,
    route_without_model_access,
)
from ..llm.model_access import ModelProvider, require_native_tool_capable_model
from ..qa.datalog_audit import (
    append_datalog_audit_record,
    build_datalog_audit_record,
)
from ..qa.flow_direction import (
    classify_path_direction_basis,
    detect_directed_intent,
    direction_annotation_key,
    effective_direction,
    evaluation_boundary,
)
from ..qa.grounded_qa_harness import (
    DEFAULT_MAX_CONVERSATION_TURNS,
    ConversationTurn,
    QATurnProvider,
    RoundProgress,
    RunConstraints,
    Steering,
    compact_conversation,
    run_grounded_qa_turn,
)
from ..qa.topology_tools import TopologyTools
from ..verification.bundled_rule_pack import (
    bundled_rule_packs,
    evaluate_pack_rule,
)
from ..verification.pack_skill_context import (
    build_advisory_walkthrough,
    skill_context_entries,
)
from ..workflow.artifact_store import ArtifactStore, ArtifactStoreError
from ..workflow.review_session import (
    PreparationLimits,
    ReviewSessionService,
    build_evidence_highlight_payload,
    session_artifact_keys,
    session_artifact_paths,
)

ANSWER_FACT_RE = re.compile(r'^\s*answer\s*\(\s*"([^"]+)"\s*\)\s*\.\s*$')


def _answer_symbols(generated_datalog: str) -> list[str]:
    has_answer_decl = ".decl answer(x:symbol)" in generated_datalog
    has_answer_output = ".output answer" in generated_datalog
    if not has_answer_decl or not has_answer_output:
        return []
    symbols = []
    for line in generated_datalog.splitlines():
        match = ANSWER_FACT_RE.match(line)
        if match:
            symbols.append(match.group(1))
    return symbols


def _topology_ids_by_answer_symbol(topology: dict[str, object]) -> dict[str, str]:
    ids_by_symbol = {}
    for topology_id, evidence in topology["evidence_map"].items():
        ids_by_symbol[str(topology_id)] = str(topology_id)
        canonical_fact = evidence["canonical_fact"]
        if canonical_fact["fact_type"] == "node":
            ids_by_symbol[str(canonical_fact["node_id"])] = str(topology_id)

    for node in topology["nodes"]:
        topology_id = str(node["id"])
        for key in ["label", "tag_name", "proteus_id", "canonical_fact_id"]:
            value = node.get(key)
            if value:
                ids_by_symbol[str(value)] = topology_id
    return ids_by_symbol


def _topology_object_label(*, topology: dict[str, object], topology_id: str) -> str:
    for node in topology["nodes"]:
        if node["id"] == topology_id:
            label = node.get("tag_name") or node.get("label") or topology_id
            return str(label)
    for edge in topology["edges"]:
        if edge["id"] == topology_id:
            source_label = _topology_object_label(
                topology=topology, topology_id=str(edge["source_id"])
            )
            target_label = _topology_object_label(
                topology=topology, topology_id=str(edge["target_id"])
            )
            return f"{source_label} {edge['relationship']} {target_label}"
    return topology_id


def _topology_object_kind(*, topology: dict[str, object], topology_id: str) -> str:
    for node in topology["nodes"]:
        if node["id"] == topology_id:
            return "node"
    for edge in topology["edges"]:
        if edge["id"] == topology_id:
            return "edge"
    return "topology_object"


def _natural_logic_answer_summary(evidence_items: list[dict[str, object]]) -> str:
    if not evidence_items:
        return "The confirmed Datalog query did not match any topology evidence."

    names = [
        f"{item['label']} ({item['id']})"
        for item in evidence_items[:3]
    ]
    if len(evidence_items) == 1:
        return f"The confirmed Datalog query matched {names[0]}."

    remaining_count = len(evidence_items) - len(names)
    suffix = f", and {remaining_count} more" if remaining_count > 0 else ""
    return (
        "The confirmed Datalog query matched "
        f"{len(evidence_items)} topology objects: {', '.join(names)}{suffix}."
    )


def _parse_grounded_answer_response(response: str) -> str | None:
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        text = response.strip()
        return text or None

    if not isinstance(parsed, dict):
        return None
    answer_text = parsed.get("answer_text")
    if isinstance(answer_text, str) and answer_text.strip():
        return answer_text.strip()
    return None


class DatalogExecutionValidationError(ValueError):
    def __init__(self, diagnostics: list[dict[str, str]]) -> None:
        super().__init__(diagnostics[0]["message"])
        self.diagnostics = diagnostics


class ChainlitReviewFlow:
    """Chainlit-facing state model for the single-file review workflow."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        limits: PreparationLimits | None = None,
        clock: Callable[[], float] = time.perf_counter,
        max_conversation_turns: int = DEFAULT_MAX_CONVERSATION_TURNS,
    ) -> None:
        self._store = store
        self._service = ReviewSessionService(store=store, limits=limits)
        self._clock = clock
        self._max_conversation_turns = max_conversation_turns
        self._timing_records: list[dict[str, object]] = []
        self._artifacts_by_session: dict[str, dict[str, object]] = {}
        self._topology_by_session: dict[str, dict[str, object]] = {}
        self._evidence_highlight_by_session: dict[str, dict[str, object]] = {}
        self._visible_source_scope_by_session: dict[str, list[str]] = {}
        self._last_selected_by_session: dict[str, str] = {}
        self._provider_settings_by_session: dict[str, dict[str, object]] = {}
        self._credentials_by_session: dict[str, str] = {}
        self._rule_pack_results_by_session: dict[str, list[dict[str, object]]] = {}
        self._loaded_rule_packs_by_session: dict[str, set[str]] = {}
        self._loaded_rule_pack_data_by_session: dict[str, dict[str, dict[str, object]]] = (
            {}
        )
        self._missing_capabilities_by_session: dict[str, list[dict[str, object]]] = {}
        self._direction_annotations_by_session: dict[
            str, dict[str, dict[str, object]]
        ] = {}
        # Approval integrity: proposals raised for review are kept server-side,
        # keyed by proposal_id, and are the only thing a confirm may execute.
        self._pending_datalog_proposals_by_session: dict[
            str, dict[str, dict[str, object]]
        ] = {}

    def initial_state(self) -> dict[str, object]:
        return {
            "status": "awaiting_upload",
            "session_id": None,
            "query_controls": {
                "enabled": False,
                "disabled_reason": "Upload a DEXPI 1.3 XML file to prepare a review session.",
            },
            "prompt_composer": {
                "enabled": False,
                "disabled_reason": "Session preparation has not started.",
            },
            "timing": None,
            "diagnostics": [],
            "topology_view": None,
        }

    def preparing_state(self, *, session_id: str) -> dict[str, object]:
        disabled_reason = "Session preparation is still running."
        return {
            "status": "preparing",
            "session_id": session_id,
            "query_controls": {
                "enabled": False,
                "disabled_reason": disabled_reason,
            },
            "prompt_composer": {
                "enabled": False,
                "disabled_reason": disabled_reason,
            },
            "timing": None,
            "diagnostics": [],
            "topology_view": None,
        }

    def prepare_upload(
        self, *, dexpi_xml_path: Path, session_id: str
    ) -> dict[str, object]:
        started_at = self._clock()
        result = self._service.start_preparation(
            dexpi_xml_path=dexpi_xml_path,
            session_id=session_id,
        )
        elapsed_seconds = self._clock() - started_at
        return self._state_from_preparation_result(
            result=result,
            document_id=session_id,
            elapsed_seconds=elapsed_seconds,
        )

    def retry_upload(self, *, session_id: str) -> dict[str, object]:
        started_at = self._clock()
        result = self._service.retry_preparation(session_id=session_id)
        elapsed_seconds = self._clock() - started_at
        return self._state_from_preparation_result(
            result=result,
            document_id=session_id,
            elapsed_seconds=elapsed_seconds,
        )

    def timing_records(self) -> list[dict[str, object]]:
        return list(self._timing_records)

    def topology_panel_state(self, *, session_id: str) -> dict[str, object]:
        topology = self._topology_for_session(session_id)
        graph_objects = [
            {
                "id": node["id"],
                "kind": "node",
                # Engineer-facing identifier (tag/line/qualified nozzle) when known.
                "label": node.get("display_name") or node.get("label"),
                "node_class": node.get("class_name") or node.get("label"),
                "category": node.get("category", "other"),
                "description": node.get("description", ""),
                "selectable": True,
            }
            for node in topology["nodes"]
        ]
        graph_objects.extend(
            {
                "id": edge["id"],
                "kind": "edge",
                "label": edge["relationship"],
                "selectable": False,
            }
            for edge in topology["edges"]
        )
        return {
            "session_id": session_id,
            "graph_objects": graph_objects,
            # Compressed P&ID-like view (equipment units + collapsed lines).
            "pid_view": topology.get("pid_view", {"units": [], "lines": [], "hidden_topology_ids": []}),
            # Drawing-faithful tier-1 scene (ADR 0004/0005); None when the
            # source carries no geometry, or fails the geometry sanity gate.
            "schematic_scene": topology.get("schematic_scene"),
            # "as-drawn" | "auto-layout" | "none" (bead pydexpi-datalog-1-2ki.5).
            "schematic_scene_kind": topology.get("schematic_scene_kind", "none"),
            "geometry_report": topology.get("geometry_report"),
            "visible_source_scope": self._visible_source_scope(session_id),
            "evidence_highlight": self._evidence_highlight(session_id),
        }

    def select_topology_object(
        self,
        *,
        session_id: str,
        topology_id: str,
        latency_target_seconds: float,
    ) -> dict[str, object]:
        started_at = self._clock()
        self._ensure_known_topology_id(session_id=session_id, topology_id=topology_id)
        self._last_selected_by_session[session_id] = topology_id
        self._visible_source_scope_by_session[session_id] = [topology_id]
        elapsed_seconds = self._clock() - started_at
        return {
            "session_id": session_id,
            "selected_topology_id": topology_id,
            "visible_source_scope": self._visible_source_scope(session_id),
            "selection_latency_seconds": elapsed_seconds,
            "latency_target_seconds": latency_target_seconds,
        }

    def edit_visible_source_scope(
        self, *, session_id: str, source_scope_ids: list[str]
    ) -> dict[str, object]:
        for topology_id in source_scope_ids:
            self._ensure_known_topology_id(
                session_id=session_id,
                topology_id=topology_id,
            )
        self._visible_source_scope_by_session[session_id] = list(source_scope_ids)
        return {
            "session_id": session_id,
            "visible_source_scope": self._visible_source_scope(session_id),
        }

    def remove_visible_source_scope(
        self, *, session_id: str, topology_id: str
    ) -> dict[str, object]:
        current_scope = self._visible_source_scope_by_session.get(session_id, [])
        self._visible_source_scope_by_session[session_id] = [
            item for item in current_scope if item != topology_id
        ]
        return {
            "session_id": session_id,
            "visible_source_scope": self._visible_source_scope(session_id),
        }

    def build_logic_request_submission(
        self, *, session_id: str, prompt: str
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        return {
            "session_id": session_id,
            "prompt": prompt,
            "source_scope_ids": list(
                self._visible_source_scope_by_session.get(session_id, [])
            ),
        }

    def improve_logic_request(
        self, *, session_id: str, prompt: str
    ) -> dict[str, object]:
        submission = self.build_logic_request_submission(
            session_id=session_id,
            prompt=prompt,
        )
        route = route_logic_request(prompt)
        if route["kind"] != "topology_logic":
            routed = route_without_model_access(route)
            result = {
                "session_id": session_id,
                "prompt": prompt,
                "source_scope_ids": submission["source_scope_ids"],
                "route": route,
                **routed,
            }
            if route["kind"] == "missing_capability":
                missing_capability = self._missing_capability_artifact(
                    session_id=session_id,
                    prompt=prompt,
                    diagnostics=list(routed["diagnostics"]),
                )
                result["missing_capability"] = missing_capability
                self._missing_capabilities_by_session.setdefault(session_id, []).append(
                    missing_capability
                )
            return result

        source_scope_ids = list(submission["source_scope_ids"])
        scope_kind = "visible_source_scope" if source_scope_ids else "whole_pid"
        return {
            "session_id": session_id,
            "status": "refinement_ready",
            "route": route,
            "refinement": {
                "original_prompt": prompt,
                "refined_prompt": prompt.strip(),
                "scope": {"kind": scope_kind},
                "source_scope_ids": source_scope_ids,
                "provider": self.provider_settings_state(session_id),
                "review_notes": [
                    "Review the restated topology request before Datalog generation.",
                    "Only visible source-scope identifiers are included when selected.",
                ],
            },
            "diagnostics": [],
        }

    def accept_logic_request_refinement(
        self,
        *,
        session_id: str,
        improvement: dict[str, object],
        provider: ModelProvider,
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        if improvement.get("status") != "refinement_ready":
            raise ValueError("only refinement_ready logic requests can be accepted")

        refinement = improvement["refinement"]
        if not isinstance(refinement, dict):
            raise ValueError("accepted improvement is missing a refinement")

        provider_settings = self.provider_settings_state(session_id)
        if not provider_settings["configured"]:
            return {
                "artifact_type": "logic_request_confirmation",
                "status": "failed",
                "session_id": session_id,
                "request": self._confirmation_request(
                    improvement=improvement,
                    refinement=refinement,
                    provider_settings=provider_settings,
                ),
                "diagnostics": [
                    {
                        "code": "model_access.missing_byok_credentials",
                        "message": "Configure a provider credential before accepting a refinement.",
                    }
                ],
            }

        topology = self._topology_for_session(session_id)
        response = provider.complete(
            request=str(refinement["refined_prompt"]),
            context={
                "route": improvement["route"],
                "provider": provider_settings,
                "scope": refinement["scope"],
                "source_scope_ids": list(refinement["source_scope_ids"]),
                "topology_nodes": [
                    {
                        "id": node["id"],
                        "label": node.get("tag_name") or node.get("label") or node["id"],
                        "class": node.get("label") or node["id"],
                    }
                    for node in topology["nodes"]
                ],
                "topology_edges": [
                    {
                        "source_id": edge["source_id"],
                        "target_id": edge["target_id"],
                        "relationship": edge["relationship"],
                    }
                    for edge in topology["edges"]
                ],
            },
        )
        draft = parse_model_draft_response(response)
        generated_datalog = draft.get("generated_datalog")
        formal_restatement = draft.get("formal_restatement")
        if not isinstance(generated_datalog, str) or not isinstance(
            formal_restatement, str
        ):
            return {
                "artifact_type": "logic_request_confirmation",
                "status": "failed",
                "session_id": session_id,
                "request": self._confirmation_request(
                    improvement=improvement,
                    refinement=refinement,
                    provider_settings=provider_settings,
                ),
                "diagnostics": [
                    {
                        "code": "logic_request.confirmation_incomplete",
                        "message": "The model draft must include generated_datalog and formal_restatement.",
                    }
                ],
            }

        return {
            "artifact_type": "logic_request_confirmation",
            "status": "confirmation_ready",
            "session_id": session_id,
            "request": self._confirmation_request(
                improvement=improvement,
                refinement=refinement,
                provider_settings=provider_settings,
            ),
            "primary_confirmation": "restatement",
            "restatement": {
                "kind": "datalog_grounded_restatement",
                "text": formal_restatement,
                "grounded_by": "generated_logic",
            },
            "generated_logic": {
                "kind": "generated_datalog",
                "language": "souffle_datalog",
                "content": generated_datalog,
                "inspectable": True,
                "editable": False,
            },
            "validation": {
                "status": "pending_safety_validation",
                "message": "Execution safety validation runs before the confirmed query can execute.",
            },
            "allowed_actions": ["run", "revise", "cancel"],
            "direct_datalog_edit": self._direct_datalog_edit_unavailable(),
            "diagnostics": [],
        }

    def execute_confirmed_logic_request(
        self,
        *,
        session_id: str,
        confirmation: dict[str, object],
        provider: ModelProvider | None = None,
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        if confirmation.get("session_id") != session_id:
            raise ValueError("confirmed logic request is not part of this active session")
        if confirmation.get("status") != "confirmation_ready":
            raise ValueError("only confirmation_ready logic requests can be executed")

        generated_logic = confirmation["generated_logic"]
        if not isinstance(generated_logic, dict):
            raise ValueError("confirmed logic request is missing generated logic")

        request = confirmation["request"]
        if not isinstance(request, dict):
            raise ValueError("confirmed logic request is missing request metadata")

        try:
            evidence_items = self._deterministic_evidence_items(
                session_id=session_id,
                request=request,
                generated_logic=generated_logic,
            )
        except DatalogExecutionValidationError as error:
            return {
                "status": "execution_failed",
                "session_id": session_id,
                "request": request,
                "summary": {
                    "position": "first",
                    "text": error.diagnostics[0]["message"],
                },
                "evidence": {
                    "display": "expandable",
                    "items": [],
                },
                "evidence_highlight": build_evidence_highlight_payload(
                    topology_view=self._topology_for_session(session_id),
                    source_scope_ids=list(request["source_scope_ids"]),
                    matched_object_ids=[],
                    paths=[],
                ),
                "diagnostics": error.diagnostics,
            }
        evidence_highlight = build_evidence_highlight_payload(
            topology_view=self._topology_for_session(session_id),
            source_scope_ids=list(request["source_scope_ids"]),
            matched_object_ids=[str(item["id"]) for item in evidence_items],
            paths=[],
        )
        self._evidence_highlight_by_session[session_id] = evidence_highlight
        result_artifact = {
            "artifact_type": "deterministic_logic_request_result",
            "session_id": session_id,
            "request": request,
            "generated_logic": generated_logic,
            "deterministic_inputs": self._artifacts_by_session[session_id],
            "evidence": evidence_items,
            "evidence_highlight": evidence_highlight,
            "diagnostics": [],
        }
        result_path = self._write_logic_request_result_artifact(
            session_id=session_id,
            result_artifact=result_artifact,
        )
        answer_text = self._grounded_answer_text(
            provider=provider,
            request=request,
            generated_logic=generated_logic,
            evidence_items=evidence_items,
        )
        return {
            "status": "answered",
            "session_id": session_id,
            "request": request,
            "summary": {
                "position": "first",
                "text": answer_text,
            },
            "result_artifact": {
                "kind": "deterministic_logic_request_result",
                "path": str(result_path),
            },
            "evidence": {
                "display": "expandable",
                "items": evidence_items,
            },
            "evidence_highlight": evidence_highlight,
            "diagnostics": [],
        }

    def _grounded_answer_text(
        self,
        *,
        provider: ModelProvider | None,
        request: dict[str, object],
        generated_logic: dict[str, object],
        evidence_items: list[dict[str, object]],
    ) -> str:
        fallback = _natural_logic_answer_summary(evidence_items)
        if provider is None:
            return fallback

        response = provider.complete(
            request=str(request.get("prompt", "")),
            context={
                "task": "grounded_logic_answer",
                "instructions": (
                    "Answer the user's topology question directly using only the "
                    "provided deterministic evidence. Do not mention raw JSON unless "
                    "the user asks for it."
                ),
                "generated_logic": generated_logic,
                "evidence_items": evidence_items,
            },
        )
        return _parse_grounded_answer_response(response) or fallback

    def apply_deterministic_evidence_highlight(
        self,
        *,
        session_id: str,
        source_scope_ids: list[str],
        matched_object_ids: list[str],
        paths: list[dict[str, object]],
    ) -> dict[str, object]:
        highlight = build_evidence_highlight_payload(
            topology_view=self._topology_for_session(session_id),
            source_scope_ids=source_scope_ids,
            matched_object_ids=matched_object_ids,
            paths=paths,
        )
        self._evidence_highlight_by_session[session_id] = highlight
        return {
            "session_id": session_id,
            "evidence_highlight": self._evidence_highlight(session_id),
        }

    def rule_pack_results_state(self, *, session_id: str) -> dict[str, object]:
        self._topology_for_session(session_id)
        return {
            "session_id": session_id,
            "results": list(self._rule_pack_results_by_session.get(session_id, [])),
        }

    def execute_selected_rule_pack_query(
        self,
        *,
        session_id: str,
        rule_id: str,
        pack_id: str = "demo-process-safety",
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        return self._execute_bundled_rule(
            session_id=session_id, pack_id=pack_id, rule_id=rule_id
        )

    def _execute_bundled_rule(
        self,
        *,
        session_id: str,
        pack_id: str,
        rule_id: str,
        authored_packs: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        graph_facts = self._store.read_json(
            session_artifact_keys(session_id)["graph_facts_json"]
        )
        pack = self._resolve_pack(pack_id, authored_packs=authored_packs)
        rule_result = evaluate_pack_rule(
            graph_facts,
            pack=pack,
            rule_id=rule_id,
        )
        evidence_items = self._rule_pack_evidence_items(
            session_id=session_id,
            rule_result=rule_result,
        )
        matched_ids = [str(item["id"]) for item in evidence_items]
        evidence_highlight = build_evidence_highlight_payload(
            topology_view=self._topology_for_session(session_id),
            source_scope_ids=[],
            matched_object_ids=matched_ids,
            paths=[],
        )
        self._evidence_highlight_by_session[session_id] = evidence_highlight

        result_artifact = {
            "artifact_type": "rule_pack_result",
            "session_id": session_id,
            "rule_id": rule_id,
            "pack": rule_result["pack"],
            "rule_result": rule_result,
            "deterministic_inputs": self._artifacts_by_session[session_id],
            "evidence": evidence_items,
            "evidence_highlight": evidence_highlight,
            "diagnostics": [],
        }
        result_path = self._write_result_artifact(
            session_id=session_id,
            result_artifact=result_artifact,
            dirname="rule_pack_results",
            filename_prefix="rule_pack_result",
        )
        result = {
            "status": "answered",
            "session_id": session_id,
            "rule_id": rule_id,
            "pack": rule_result["pack"],
            "outcome": str(rule_result["outcome"]),
            "confirmation": {"required": False},
            "summary": {
                "position": "first",
                "text": f"{rule_id}: {rule_result['outcome']}. {rule_result['message']}",
            },
            "result_artifact": {
                "kind": "rule_pack_result",
                "path": str(result_path),
            },
            "evidence": {
                "display": "expandable",
                "items": evidence_items,
            },
            "evidence_highlight": evidence_highlight,
            "diagnostics": [],
        }
        self._rule_pack_results_by_session.setdefault(session_id, []).append(result)
        return result

    def list_bundled_rule_packs(self, *, session_id: str) -> dict[str, object]:
        return self.list_rule_packs(session_id=session_id, authored_packs=[])

    def list_rule_packs(
        self,
        *,
        session_id: str,
        authored_packs: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        loaded = self._loaded_rule_packs_by_session.get(session_id, set())
        packs = [
            {
                "pack_id": pack["pack_id"],
                "version": pack["version"],
                "title": pack["title"],
                "authoritative": pack["authoritative"],
                "trust_notice": pack["trust_notice"],
                "source": "system",
                "loaded": pack["pack_id"] in loaded,
                "advisory_guidance": pack.get("advisory_guidance", []),
                "rules": [
                    {
                        "rule_id": rule["rule_id"],
                        "title": rule["title"],
                        "outcomes": rule["outcomes"],
                        "restatement": rule["restatement"],
                        "executable_logic": rule["executable_logic"],
                    }
                    for rule in pack["rules"]
                ],
            }
            for pack in bundled_rule_packs()
        ]
        for pack in authored_packs or []:
            packs.append(
                {
                    "pack_id": pack["pack_id"],
                    "version": pack["version"],
                    "title": pack["title"],
                    "authoritative": False,
                    "trust_notice": pack["trust_notice"],
                    "source": "user",
                    "loaded": pack["pack_id"] in loaded,
                    "advisory_guidance": pack.get("advisory_guidance", []),
                    "rules": [
                        {
                            "rule_id": rule["rule_id"],
                            "title": rule["title"],
                            "outcomes": rule["outcomes"],
                            "restatement": rule["restatement"],
                            "executable_logic": rule["executable_logic"],
                        }
                        for rule in pack["rules"]
                    ],
                }
            )
        return {"session_id": session_id, "packs": packs}

    def load_rule_pack(
        self,
        *,
        session_id: str,
        pack_id: str,
        authored_packs: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        pack = self._resolve_pack(pack_id, authored_packs=authored_packs)
        self._loaded_rule_packs_by_session.setdefault(session_id, set()).add(pack_id)
        self._loaded_rule_pack_data_by_session.setdefault(session_id, {})[pack_id] = pack
        return {
            "session_id": session_id,
            "pack_id": pack_id,
            "loaded": True,
            "pack": {
                "pack_id": pack["pack_id"],
                "version": pack["version"],
                "title": pack["title"],
                "authoritative": pack["authoritative"],
                "trust_notice": pack["trust_notice"],
                "source": pack.get("source", "system"),
            },
            "skill_context": self.attached_pack_skill_context(session_id=session_id),
        }

    def unload_rule_pack(
        self,
        *,
        session_id: str,
        pack_id: str,
        authored_packs: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        # Validate the pack exists even when detaching an already-unloaded id.
        self._resolve_pack(pack_id, authored_packs=authored_packs)
        loaded = self._loaded_rule_packs_by_session.setdefault(session_id, set())
        loaded.discard(pack_id)
        self._loaded_rule_pack_data_by_session.get(session_id, {}).pop(pack_id, None)
        return {
            "session_id": session_id,
            "pack_id": pack_id,
            "loaded": False,
            "skill_context": self.attached_pack_skill_context(session_id=session_id),
        }

    def attached_pack_skill_context(
        self,
        *,
        session_id: str,
        authored_packs: list[dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        loaded_ids = self._loaded_rule_packs_by_session.get(session_id, set())
        cached = self._loaded_rule_pack_data_by_session.get(session_id, {})
        packs: list[dict[str, object]] = []
        for pack_id in sorted(loaded_ids):
            if pack_id in cached:
                packs.append(cached[pack_id])
            else:
                packs.append(
                    self._resolve_pack(pack_id, authored_packs=authored_packs)
                )
        return skill_context_entries(packs)

    def run_rule_pack(
        self,
        *,
        session_id: str,
        pack_id: str = "demo-process-safety",
        authored_packs: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        pack = self._resolve_pack(pack_id, authored_packs=authored_packs)
        # Ensure the pack is attached so skill context stays aligned with run.
        self._loaded_rule_packs_by_session.setdefault(session_id, set()).add(pack_id)
        self._loaded_rule_pack_data_by_session.setdefault(session_id, {})[pack_id] = pack

        rules = list(pack.get("rules") or [])
        if not rules:
            walkthrough = build_advisory_walkthrough(pack)
            return {
                "status": "answered",
                "session_id": session_id,
                "pack_id": pack_id,
                "mode": "advisory_walkthrough",
                "confirmation": {"required": False},
                "results": [],
                "walkthrough": walkthrough,
                "skill_context": self.attached_pack_skill_context(
                    session_id=session_id, authored_packs=authored_packs
                ),
            }

        results = [
            self._execute_bundled_rule(
                session_id=session_id,
                pack_id=pack_id,
                rule_id=str(rule["rule_id"]),
                authored_packs=authored_packs,
            )
            for rule in rules
        ]
        response: dict[str, object] = {
            "status": "answered",
            "session_id": session_id,
            "pack_id": pack_id,
            "mode": "rule_evaluation",
            "confirmation": {"required": False},
            "results": results,
        }
        if pack.get("advisory_guidance"):
            response["walkthrough"] = build_advisory_walkthrough(pack)
        return response

    def _resolve_pack(
        self,
        pack_id: str,
        *,
        authored_packs: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        for pack in bundled_rule_packs():
            if pack["pack_id"] == pack_id:
                resolved = dict(pack)
                resolved["source"] = "system"
                return resolved
        for pack in authored_packs or []:
            if pack["pack_id"] == pack_id:
                resolved = dict(pack)
                resolved["authoritative"] = False
                resolved["source"] = "user"
                return resolved
        raise ValueError(f"unknown rule pack: {pack_id}")

    def configure_provider_settings(
        self,
        *,
        session_id: str,
        provider: str,
        model: str,
        credential: str,
        base_url: str | None = None,
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        require_native_tool_capable_model(provider=provider, model=model)
        self._credentials_by_session[session_id] = credential
        settings: dict[str, object] = {
            "provider": provider,
            "model": model,
            "configured": provider == "ollama" or bool(credential),
        }
        if base_url is not None:
            settings["base_url"] = base_url
        self._provider_settings_by_session[session_id] = settings
        return {
            "session_id": session_id,
            **self.provider_settings_state(session_id),
        }

    def provider_settings_state(self, session_id: str) -> dict[str, object]:
        settings = self._provider_settings_by_session.get(session_id)
        if settings is None:
            return {
                "provider": "openai",
                "model": "gpt-4.1",
                "configured": False,
            }
        return dict(settings)

    def build_logic_request_audit_record(
        self, *, submission: dict[str, object]
    ) -> dict[str, object]:
        session_id = str(submission["session_id"])
        return {
            "session_id": session_id,
            "prompt": submission["prompt"],
            "source_scope_ids": list(submission["source_scope_ids"]),
            "provider": self.provider_settings_state(session_id),
        }

    def export_session_state(self, *, session_id: str) -> dict[str, object]:
        self._topology_for_session(session_id)
        return {
            "session_id": session_id,
            "provider": self.provider_settings_state(session_id),
            "visible_source_scope": self._visible_source_scope(session_id),
            "timing": [
                item
                for item in self._timing_records
                if item["session_id"] == session_id
            ],
        }

    def export_session_artifacts(
        self, *, session_id: str, export_prefix: str
    ) -> dict[str, object]:
        self._topology_for_session(session_id)

        prepared_artifacts = self._copy_prepared_artifacts(
            session_id=session_id,
            export_prefix=f"{export_prefix}/prepared",
        )
        logic_request_results = self._copy_artifact_directory(
            session_id=session_id,
            source_dirname="logic_request_results",
            export_prefix=f"{export_prefix}/logic_request_results",
        )
        rule_pack_results = self._copy_artifact_directory(
            session_id=session_id,
            source_dirname="rule_pack_results",
            export_prefix=f"{export_prefix}/rule_pack_results",
        )
        missing_capabilities = self._write_missing_capability_exports(
            session_id=session_id,
            export_prefix=f"{export_prefix}/missing_capabilities",
        )
        manifest = {
            "artifact_type": "explicit_session_export",
            "session_id": session_id,
            "provider": self.provider_settings_state(session_id),
            "visible_source_scope": self._visible_source_scope(session_id),
            "evidence_highlight": self._evidence_highlight(session_id),
            "timing": [
                item
                for item in self._timing_records
                if item["session_id"] == session_id
            ],
            "prepared_artifacts": prepared_artifacts,
            "logic_request_results": logic_request_results,
            "rule_pack_results": rule_pack_results,
            "missing_capabilities": missing_capabilities,
        }
        manifest_key = f"{export_prefix}/manifest.json"
        self._store.write_json(manifest_key, manifest)
        return {
            "status": "exported",
            "session_id": session_id,
            "export_dir": str(self._local_path_for(export_prefix)),
            "manifest_path": str(self._local_path_for(manifest_key)),
            "manifest": manifest,
        }

    def run_qa_turn(
        self,
        *,
        session_id: str,
        question: str,
        qa_provider: QATurnProvider,
        conversation: list[dict[str, object]] | None = None,
        on_round: RoundProgress | None = None,
        steering: Steering | None = None,
        constraints: RunConstraints | None = None,
    ) -> dict[str, object]:
        topology = self._topology_for_session(session_id)
        answer = self._compute_qa_answer(
            topology=topology,
            session_id=session_id,
            question=question,
            qa_provider=qa_provider,
            conversation=conversation,
            on_round=on_round,
            steering=steering,
            constraints=constraints,
        )
        # Temporary generated-query confirmation retired after cutover (3qo.9.9);
        # validated proposals execute inside the harness. Direction review remains.

        directed = detect_directed_intent(question)
        review_paths = self._direction_review_paths(
            answer["valid_paths"], batch=self._is_universal_direction_question(question)
        )
        if directed is None or not review_paths:
            return self._answered_payload(session_id, answer)

        edge_relationships = {
            str(edge["id"]): str(edge["relationship"]) for edge in topology["edges"]
        }
        boundary = evaluation_boundary(directed)
        source_id = topology.get("source_id")
        pending_reviews: list[dict[str, object]] = []
        resolved_directions: list[dict[str, object]] = []
        annotations = self._direction_annotations_by_session.get(session_id, {})

        for path in review_paths:
            basis = classify_path_direction_basis(
                [edge_relationships.get(eid, "") for eid in path["edge_ids"]]
            )
            review_key = direction_annotation_key(
                source_id=str(source_id) if source_id else None,
                evaluation_boundary=boundary,
                node_ids=path["node_ids"],
                edge_ids=path["edge_ids"],
            )
            if basis == "explicit":
                resolved_directions.append(
                    {
                        "proposed_direction": directed,
                        "effective_direction": directed,
                        "direction_basis": "explicit",
                        "review_status": "confirmed",
                        "evaluation_boundary": boundary,
                        "review_key": review_key,
                        "review_required": False,
                        "object_id": str(path["id"]),
                    }
                )
                continue
            annotation = annotations.get(review_key)
            if annotation is None:
                pending_reviews.append(
                    self._direction_review_item(
                        topology=topology,
                        proposed_direction=directed,
                        basis=basis,
                        boundary=boundary,
                        source_id=source_id,
                        review_key=review_key,
                        primary=path,
                    )
                )
                continue
            review_status = str(annotation["review_status"])
            resolved_directions.append(
                {
                    "proposed_direction": directed,
                    "effective_direction": effective_direction(
                        proposed_direction=directed, review_status=review_status
                    ),
                    "direction_basis": basis,
                    "review_status": review_status,
                    "evaluation_boundary": boundary,
                    "review_key": review_key,
                    "review_required": False,
                    "object_id": str(path["id"]),
                }
            )

        if pending_reviews:
            return self._needs_direction_reviews_payload(
                session_id=session_id,
                question=question,
                reviews=pending_reviews,
            )

        if len(resolved_directions) == 1:
            return self._answered_payload(
                session_id, answer, direction=resolved_directions[0]
            )
        return self._answered_payload(
            session_id, answer, direction_batch=resolved_directions
        )

    def submit_direction_review(
        self,
        *,
        session_id: str,
        question: str,
        decision: str | None = None,
        review_key: str | None = None,
        qa_provider: QATurnProvider,
        conversation: list[dict[str, object]] | None = None,
        decisions: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        review_decisions = decisions or [
            {"decision": decision, "review_key": review_key}
        ]
        # Ensure the session is ready before recording the annotation.
        self._topology_for_session(session_id)

        annotations = self._direction_annotations_by_session.setdefault(session_id, {})
        for item in review_decisions:
            item_decision = str(item.get("decision") or "")
            item_review_key = str(item.get("review_key") or "")
            review_status = {
                "confirm": "confirmed",
                "reverse": "reversed",
                "unknown": "unknown",
            }.get(item_decision)
            if review_status is None or not item_review_key:
                raise ValueError(
                    "direction review decision must include review_key and decision confirm, reverse, or unknown"
                )
            # Persist the reviewer's judgement keyed to the exact witness identity the
            # review card was raised for. The session annotation never mutates the graph.
            annotations[item_review_key] = {"review_status": review_status}

        # Resume the original question; run_qa_turn recomputes the same keys from
        # the (source, path, evaluation boundary) and applies the stored annotations.
        return self.run_qa_turn(
            session_id=session_id,
            question=question,
            qa_provider=qa_provider,
            conversation=conversation,
        )

    def submit_temporary_datalog_review(
        self,
        *,
        session_id: str,
        question: str,
        decision: str,
        proposal_result: dict[str, object],
    ) -> dict[str, object]:
        topology = self._topology_for_session(session_id)
        claimed_raw = proposal_result.get("proposal")
        claimed_proposal = claimed_raw if isinstance(claimed_raw, dict) else {}
        proposal_id = str(claimed_proposal.get("proposal_id", ""))
        pending = self._pending_datalog_proposals_by_session.get(session_id, {})
        if decision == "cancel":
            stored_result = pending.pop(proposal_id, None)
            stored_proposal = (
                stored_result.get("proposal") if stored_result is not None else None
            )
            self._append_datalog_audit(
                session_id=session_id,
                question=question,
                proposal=stored_proposal
                if isinstance(stored_proposal, dict)
                else claimed_proposal,
                decision="canceled",
                executed=False,
                execution_status="not_executed",
            )
            return {
                "status": "canceled",
                "session_id": session_id,
                "question": question,
                "executed": False,
                "diagnostics": [],
            }
        if decision != "confirm":
            raise ValueError("temporary Datalog decision must be confirm or cancel")

        # Only a proposal the server itself raised for review may execute; the
        # client payload contributes nothing beyond the proposal_id lookup key.
        stored_result = pending.pop(proposal_id, None)
        if stored_result is None:
            self._append_datalog_audit(
                session_id=session_id,
                question=question,
                proposal=claimed_proposal,
                decision="approved",
                executed=False,
                execution_status="execution_failed",
            )
            return {
                "status": "execution_failed",
                "session_id": session_id,
                "question": question,
                "executed": False,
                "diagnostics": [
                    {
                        "code": "temporary_datalog.proposal_unknown",
                        "message": "Temporary Datalog execution requires a proposal the server raised for review in this session.",
                    }
                ],
            }
        stored_proposal_raw = stored_result.get("proposal")
        proposal = (
            stored_proposal_raw if isinstance(stored_proposal_raw, dict) else {}
        )

        graph_facts = self._store.read_json(
            session_artifact_keys(session_id)["graph_facts_json"]
        )
        tools = TopologyTools(
            topology_view=topology,
            session_id=session_id,
            graph_facts=graph_facts,
            loaded_rule_pack_ids=self._loaded_rule_packs_by_session.get(
                session_id, set()
            ),
            attached_pack_skill_context=self.attached_pack_skill_context(
                session_id=session_id
            ),
        )
        execution = tools.execute_confirmed_temporary_datalog(stored_result)
        executed = execution.get("status") == "answered"
        self._append_datalog_audit(
            session_id=session_id,
            question=question,
            proposal=proposal,
            decision="approved",
            executed=executed,
            execution_status="answered" if executed else "execution_failed",
        )
        if not executed:
            return {
                "status": "execution_failed",
                "session_id": session_id,
                "question": question,
                "executed": False,
                "diagnostics": list(execution.get("diagnostics", [])),
            }
        evidence = execution.get("evidence", {})
        items = evidence.get("items", []) if isinstance(evidence, dict) else []
        matched_ids = [
            str(item.get("id"))
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        evidence_highlight = build_evidence_highlight_payload(
            topology_view=topology,
            source_scope_ids=[],
            matched_object_ids=matched_ids,
            paths=[],
        )
        self._evidence_highlight_by_session[session_id] = evidence_highlight
        summary = execution.get("summary", {})
        return {
            "status": "answered",
            "session_id": session_id,
            "question": question,
            "answer_text": str(summary.get("text", "Temporary Datalog executed."))
            if isinstance(summary, dict)
            else "Temporary Datalog executed.",
            "evidence_references": matched_ids,
            "rejected_references": [],
            "interpreted_object_ids": [],
            "evidence": evidence,
            "evidence_highlight": evidence_highlight,
            "tool_call_trace": [],
            "diagnostics": [],
        }

    def _store_pending_datalog_proposal(
        self, session_id: str, confirmation_payload: dict[str, object]
    ) -> None:
        confirmation = confirmation_payload.get("datalog_confirmation")
        if not isinstance(confirmation, dict):
            return
        proposal_result = confirmation.get("proposal_result")
        if not isinstance(proposal_result, dict):
            return
        proposal = proposal_result.get("proposal")
        if not isinstance(proposal, dict):
            return
        proposal_id = str(proposal.get("proposal_id", ""))
        if not proposal_id:
            return
        self._pending_datalog_proposals_by_session.setdefault(session_id, {})[
            proposal_id
        ] = proposal_result

    def _append_datalog_audit(
        self,
        *,
        session_id: str,
        question: str,
        proposal: dict[str, object],
        decision: str,
        executed: bool,
        execution_status: str,
    ) -> None:
        record = build_datalog_audit_record(
            session_id=session_id,
            question=question,
            proposal=proposal,
            decision=decision,
            executed=executed,
            execution_status=execution_status,
        )
        append_datalog_audit_record(self._store, session_id, record)

    def _persist_automatic_datalog_audits(
        self,
        *,
        session_id: str,
        qa_provider: QATurnProvider,
        tool_call_trace: list[dict[str, object]],
    ) -> None:
        """Durably record every automatic temporary-Datalog execution
        (3qo.9.7): the backend-built audit skeleton from the tool result is
        enriched with provider attribution and usage, which only this layer
        knows, then appended to the same per-session audit trail as manual
        confirm/cancel decisions."""
        settings = self._provider_settings_by_session.get(session_id, {})
        provider_attribution = {
            "provider": str(settings.get("provider", "")) or None,
            "model": str(settings.get("model", "")) or None,
            "configured": bool(settings.get("configured", False)),
        }
        raw_usage = getattr(qa_provider, "usage", None)
        provider_usage = dict(raw_usage) if isinstance(raw_usage, dict) else {}
        for trace_entry in tool_call_trace:
            if trace_entry.get("tool_name") != "propose_temporary_datalog":
                continue
            tool_result = trace_entry.get("tool_result")
            if not isinstance(tool_result, dict):
                continue
            audit_record = tool_result.get("audit_record")
            if not isinstance(audit_record, dict):
                continue
            record = {
                **audit_record,
                "provider_attribution": provider_attribution,
                "provider_usage": provider_usage,
                "decided_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            append_datalog_audit_record(self._store, session_id, record)

    @staticmethod
    def _temporary_datalog_confirmation_payload(
        *,
        session_id: str,
        question: str,
        answer: dict[str, object],
    ) -> dict[str, object] | None:
        result = answer["result"]
        for trace_entry in result.tool_call_trace:
            if trace_entry.get("tool_name") != "propose_temporary_datalog":
                continue
            proposal_result = trace_entry.get("tool_result")
            if not isinstance(proposal_result, dict):
                continue
            # Only an actual confirmation pause raises the review payload. An
            # automatically executed proposal (3qo.9.7) shares the tool name
            # but carries no confirmation state and must never re-pause.
            if proposal_result.get("status") != "confirmation_required":
                continue
            proposal = proposal_result.get("proposal")
            validation = proposal_result.get("validation")
            confirmation = proposal_result.get("confirmation")
            if not isinstance(proposal, dict):
                continue
            return {
                "status": "needs_datalog_confirmation",
                "session_id": session_id,
                "question": question,
                "datalog_confirmation": {
                    "review_status": "pending",
                    "allowed_actions": [
                        "run",
                        "revise_interpretation",
                        "revise_query",
                        "cancel",
                    ],
                    "plain_language_meaning": str(
                        proposal.get("formal_restatement", question)
                    ),
                    "interpretation": str(
                        proposal.get("interpretation")
                        or proposal.get("formal_restatement", question)
                    ),
                    "scope": proposal.get("scope")
                    if isinstance(proposal.get("scope"), dict)
                    else {},
                    "assumptions": proposal.get("assumptions")
                    if isinstance(proposal.get("assumptions"), dict)
                    else {},
                    "effect": str(proposal.get("effect", "")),
                    "exact_datalog": str(
                        proposal.get("exact_datalog")
                        or proposal.get("generated_datalog", "")
                    ),
                    "generated_datalog": str(proposal.get("generated_datalog", "")),
                    "proposal_result": proposal_result,
                    "proposal": proposal,
                    "validation": validation if isinstance(validation, dict) else {},
                    "confirmation": confirmation
                    if isinstance(confirmation, dict)
                    else {},
                },
                "diagnostics": [],
            }
        return None

    def _compute_qa_answer(
        self,
        *,
        topology: dict[str, object],
        session_id: str,
        question: str,
        qa_provider: QATurnProvider,
        conversation: list[dict[str, object]] | None,
        on_round: RoundProgress | None = None,
        steering: Steering | None = None,
        constraints: RunConstraints | None = None,
    ) -> dict[str, object]:
        graph_facts = self._store.read_json(
            session_artifact_keys(session_id)["graph_facts_json"]
        )
        tools = TopologyTools(
            topology_view=topology,
            session_id=session_id,
            graph_facts=graph_facts,
            loaded_rule_pack_ids=self._loaded_rule_packs_by_session.get(
                session_id, set()
            ),
            attached_pack_skill_context=self.attached_pack_skill_context(
                session_id=session_id
            ),
        )
        prior_turns = [
            ConversationTurn(
                question=str(turn.get("question", "")),
                answer_text=str(turn.get("answer_text", "")),
                evidence_references=[
                    str(ref)
                    for ref in turn.get("evidence_references", [])
                    if isinstance(ref, str)
                ],
            )
            for turn in (conversation or [])
            if isinstance(turn, dict)
        ]

        def _provider_cost() -> float:
            usage = getattr(qa_provider, "usage", None)
            if isinstance(usage, dict):
                value = usage.get("cost_usd")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
            return 0.0

        result = run_grounded_qa_turn(
            question=question,
            topology_tools=tools,
            provider=qa_provider,
            conversation=prior_turns,
            max_conversation_turns=self._max_conversation_turns,
            on_round=on_round,
            steering=steering,
            constraints=constraints,
            provider_cost=_provider_cost,
        )
        self._persist_automatic_datalog_audits(
            session_id=session_id,
            qa_provider=qa_provider,
            tool_call_trace=result.tool_call_trace,
        )
        conversation_state = self._compacted_conversation_state(
            prior_turns, question=question, result=result
        )

        paths = []
        for trace_entry in result.tool_call_trace:
            if trace_entry["tool_name"] == "get_reachable_equipment":
                tool_result = trace_entry["tool_result"]
                for reachable in tool_result.get("reachable", []):
                    witness = reachable.get("witness", {})
                    if witness.get("node_ids") or witness.get("edge_ids"):
                        paths.append(
                            {
                                "id": reachable["evidence_id"],
                                "node_ids": list(witness.get("node_ids", [])),
                                "edge_ids": list(witness.get("edge_ids", [])),
                            }
                        )

        known_ids = set(topology["evidence_map"].keys())
        matched_object_ids = list(result.evidence_references)
        valid_paths = [
            p
            for p in paths
            if all(nid in known_ids for nid in p["node_ids"])
            and all(eid in known_ids for eid in p["edge_ids"])
            and p["id"] in known_ids
            and p["id"] in matched_object_ids
        ]
        return {
            "result": result,
            "matched_object_ids": matched_object_ids,
            "valid_paths": valid_paths,
            "conversation_state": conversation_state,
        }

    def _compacted_conversation_state(
        self,
        prior_turns: list[ConversationTurn],
        *,
        question: str,
        result: object,
    ) -> list[dict[str, object]]:
        """Return backend-authored conversation state the stateless client echoes
        on the next turn. The new grounded turn is appended and the whole history
        is compacted so it stays bounded while preserving evidence identities.

        Only validated evidence identities are carried forward; prior prose (the
        answer text) is context only and is re-validated on the next turn.
        """
        new_turn = ConversationTurn(
            question=question,
            answer_text=str(getattr(result, "answer_text", "")),
            evidence_references=list(getattr(result, "evidence_references", [])),
        )
        carried = compact_conversation(
            [*prior_turns, new_turn], max_turns=self._max_conversation_turns
        )
        return [
            {
                "question": turn.question,
                "answer_text": turn.answer_text,
                "evidence_references": list(turn.evidence_references),
            }
            for turn in carried
        ]

    @staticmethod
    def _primary_witness_path(
        valid_paths: list[dict[str, object]],
    ) -> dict[str, object] | None:
        # The most complete witness (most intervening structure) reviews best;
        # tie-break on id for determinism across runs.
        if not valid_paths:
            return None
        return sorted(
            valid_paths,
            key=lambda p: (-len(p["edge_ids"]), str(p["id"])),
        )[0]

    def _direction_review_paths(
        self, valid_paths: list[dict[str, object]], *, batch: bool
    ) -> list[dict[str, object]]:
        if not batch:
            primary = self._primary_witness_path(valid_paths)
            return [primary] if primary is not None else []
        return sorted(valid_paths, key=lambda p: (str(p["id"]), tuple(p["edge_ids"])))

    @staticmethod
    def _is_universal_direction_question(question: str) -> bool:
        return re.search(r"\b(all|each|every)\b", question.lower()) is not None

    def _answered_payload(
        self,
        session_id: str,
        answer: dict[str, object],
        *,
        direction: dict[str, object] | None = None,
        direction_batch: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        topology = self._topology_for_session(session_id)
        result = answer["result"]
        evidence_highlight = build_evidence_highlight_payload(
            topology_view=topology,
            source_scope_ids=[],
            matched_object_ids=answer["matched_object_ids"],
            paths=answer["valid_paths"],
        )
        self._evidence_highlight_by_session[session_id] = evidence_highlight

        answer_text = result.answer_text
        if result.disclosure:
            answer_text = f"{result.disclosure} {answer_text}"
        if direction is not None:
            answer_text = self._direction_prefixed_answer(answer_text, direction)
        if direction_batch is not None:
            answer_text = self._batched_direction_prefixed_answer(
                answer_text, direction_batch
            )

        payload = {
            "status": "answered",
            "session_id": session_id,
            "answer_text": answer_text,
            "evidence_references": list(result.evidence_references),
            "rejected_references": list(result.rejected_references),
            "interpreted_object_ids": list(result.interpreted_object_ids),
            "grounding_posture": result.grounding_posture,
            "source_grounded": result.source_grounded,
            "disclosure": result.disclosure,
            "evidence_highlight": evidence_highlight,
            "conversation_state": list(answer.get("conversation_state", [])),
        }
        # A deterministic route (bundled template) discloses its artifact --
        # including the executed logic program -- so clients can show the user
        # the answer is provably derived. Never fabricated for other turns.
        route_artifact = getattr(result, "route_artifact", None)
        if isinstance(route_artifact, dict):
            payload["route_artifact"] = dict(route_artifact)
        if direction is not None:
            payload["direction"] = direction
        if direction_batch is not None:
            payload["direction_reviews"] = direction_batch
            payload["per_object_outcomes"] = [
                self._direction_outcome_item(item) for item in direction_batch
            ]
        return payload

    @staticmethod
    def _direction_prefixed_answer(
        answer_text: str, direction: dict[str, object]
    ) -> str:
        status = direction["review_status"]
        effective = direction["effective_direction"]
        if status == "confirmed" and direction["direction_basis"] == "explicit":
            prefix = f"Flow direction is explicit ({effective})."
        elif status == "confirmed":
            prefix = f"Confirmed {effective} flow direction."
        elif status == "reversed":
            prefix = f"Using reviewer-reversed flow direction ({effective})."
        else:
            prefix = "Flow direction marked unknown by reviewer."
        return f"{prefix} {answer_text}"

    def _batched_direction_prefixed_answer(
        self, answer_text: str, directions: list[dict[str, object]]
    ) -> str:
        outcomes = [self._direction_outcome_item(item) for item in directions]
        summary = "; ".join(
            f"{item['object_id']}: {item['outcome']}" for item in outcomes
        )
        return f"Per-object direction outcomes: {summary}. {answer_text}"

    @staticmethod
    def _direction_outcome_item(direction: dict[str, object]) -> dict[str, object]:
        status = str(direction.get("review_status") or "")
        if status == "unknown":
            outcome = "indeterminate"
        elif status == "reversed":
            outcome = "violated"
        else:
            outcome = "satisfied"
        return {
            "object_id": str(direction.get("object_id") or ""),
            "outcome": outcome,
            "review_key": str(direction.get("review_key") or ""),
            "effective_direction": str(direction.get("effective_direction") or ""),
        }

    def _direction_review_item(
        self,
        *,
        topology: dict[str, object],
        proposed_direction: str,
        basis: str,
        boundary: str,
        source_id: object,
        review_key: str,
        primary: dict[str, object],
    ) -> dict[str, object]:
        witness_highlight = build_evidence_highlight_payload(
            topology_view=topology,
            source_scope_ids=[],
            matched_object_ids=[str(primary["id"])],
            paths=[primary],
        )
        return {
            "review_key": review_key,
            "object_id": str(primary["id"]),
            "proposed_direction": proposed_direction,
            "direction_basis": basis,
            "review_status": "pending",
            "evaluation_boundary": boundary,
            "source_id": source_id,
            "basis_explanation": (
                "Flow direction along this witness is "
                f"{basis}; confirm, reverse, or mark it unknown."
            ),
            "witness": {
                "node_ids": list(primary["node_ids"]),
                "edge_ids": list(primary["edge_ids"]),
            },
            "evidence_highlight": witness_highlight,
            "actions": ["confirm", "reverse", "unknown"],
        }

    def _needs_direction_reviews_payload(
        self,
        *,
        session_id: str,
        question: str,
        reviews: list[dict[str, object]],
    ) -> dict[str, object]:
        paths = []
        matched_object_ids = []
        for review in reviews:
            matched_object_ids.append(str(review.get("object_id") or ""))
            witness = review.get("witness")
            if isinstance(witness, dict):
                paths.append(
                    {
                        "id": str(review.get("object_id") or ""),
                        "node_ids": list(witness.get("node_ids", [])),
                        "edge_ids": list(witness.get("edge_ids", [])),
                    }
                )
        topology = self._topology_for_session(session_id)
        batch_highlight = build_evidence_highlight_payload(
            topology_view=topology,
            source_scope_ids=[],
            matched_object_ids=matched_object_ids,
            paths=paths,
        )
        self._evidence_highlight_by_session[session_id] = batch_highlight
        return {
            "status": "needs_direction_review",
            "session_id": session_id,
            "question": question,
            "direction_reviews": reviews,
            # Back-compat: legacy clients/tests read the first pending item here.
            "direction_review": reviews[0] if reviews else {},
            "answer_text": (
                "Before answering, please review the inferred flow direction for "
                f"{len(reviews)} highlighted witness"
                f"{'es' if len(reviews) != 1 else ''}."
            ),
        }

    def local_credential_for_test(self, session_id: str) -> str | None:
        return self._credentials_by_session.get(session_id)

    def _state_from_preparation_result(
        self,
        *,
        result: dict[str, object],
        document_id: str,
        elapsed_seconds: float,
    ) -> dict[str, object]:
        status = result["readiness"]["state"]
        is_ready = status == "ready"
        timing = {
            "document_id": document_id,
            "session_id": result["session_id"],
            "upload_to_ready_seconds": elapsed_seconds,
        }
        if is_ready:
            self._timing_records.append(timing)
            self._activate_ready_session(
                session_id=str(result["session_id"]),
                topology_view=result["topology_view"],
                artifacts=dict(result["artifacts"]),
            )

        disabled_reason = None
        if not is_ready:
            disabled_reason = "Session preparation has not completed successfully."

        query_controls: dict[str, object] = {"enabled": is_ready}
        prompt_composer: dict[str, object] = {"enabled": is_ready}
        if disabled_reason is not None:
            query_controls["disabled_reason"] = disabled_reason
            prompt_composer["disabled_reason"] = disabled_reason

        return {
            "status": status,
            "session_id": result["session_id"],
            "source_id": result.get("source_id"),
            "job": result["job"],
            "readiness": result["readiness"],
            "query_controls": query_controls,
            "prompt_composer": prompt_composer,
            "timing": timing,
            "diagnostics": result["diagnostics"],
            "topology_view": result["topology_view"],
        }

    def _activate_ready_session(
        self,
        *,
        session_id: str,
        topology_view: dict[str, object],
        artifacts: dict[str, object],
    ) -> None:
        """Make a ready session answerable in this process."""

        self._topology_by_session[session_id] = topology_view
        self._artifacts_by_session[session_id] = artifacts
        self._evidence_highlight_by_session[session_id] = dict(
            topology_view["evidence_highlight"]
        )
        self._visible_source_scope_by_session[session_id] = []
        self._rule_pack_results_by_session[session_id] = []
        self._loaded_rule_packs_by_session[session_id] = set()
        self._loaded_rule_pack_data_by_session[session_id] = {}
        self._missing_capabilities_by_session[session_id] = []

    def _topology_for_session(self, session_id: str) -> dict[str, object]:
        topology = self._topology_by_session.get(session_id)
        if topology is None:
            # A session prepared before this process started is still on disk.
            # Reload it rather than telling the reviewer their review is gone.
            topology = self._rehydrate_ready_session(session_id)
        if topology is None:
            raise ValueError(f"No ready topology is known for session: {session_id}")
        return topology

    def _rehydrate_ready_session(
        self, session_id: str
    ) -> dict[str, object] | None:
        """Reload a previously ready session from its persisted artifacts.

        Returns None when the session was never prepared, never became ready,
        or its artifacts are unreadable: callers then report it as unknown.
        """

        # session_id arrives from the request path; the store refuses a key
        # that would leave this workspace, so a traversal attempt reads as an
        # unknown session rather than someone else's artifacts.
        keys = session_artifact_keys(session_id)
        try:
            readiness = self._store.read_json(keys["readiness_metadata"])
            topology_view = self._store.read_json(keys["topology_view_model"])
        except (ArtifactStoreError, ValueError):
            return None
        if not isinstance(readiness, dict) or readiness.get("state") != "ready":
            return None
        if not isinstance(topology_view, dict):
            return None

        self._activate_ready_session(
            session_id=session_id,
            topology_view=topology_view,
            artifacts=dict(session_artifact_paths(self._store, session_id)),
        )
        return topology_view

    def _ensure_known_topology_id(self, *, session_id: str, topology_id: str) -> None:
        topology = self._topology_for_session(session_id)
        if topology_id not in topology["evidence_map"]:
            raise ValueError(f"unknown topology id for visible source scope: {topology_id}")

    def _missing_capability_artifact(
        self,
        *,
        session_id: str,
        prompt: str,
        diagnostics: list[object],
    ) -> dict[str, object]:
        diagnostic = diagnostics[0]
        message = ""
        code = "logic_request.missing_capability"
        if isinstance(diagnostic, dict):
            code = str(diagnostic.get("code", code))
            message = str(diagnostic.get("message", ""))
        copyable_text = "\n".join(
            [
                f"Session: {session_id}",
                f"Request: {prompt}",
                f"Unsupported capability: {message}",
            ]
        )
        return {
            "code": code,
            "message": message,
            "copyable_text": copyable_text,
            "download": {
                "filename": f"{session_id}-missing-capability.txt",
                "content_type": "text/plain",
                "content": copyable_text,
            },
        }

    def _confirmation_request(
        self,
        *,
        improvement: dict[str, object],
        refinement: dict[str, object],
        provider_settings: dict[str, object],
    ) -> dict[str, object]:
        return {
            "prompt": refinement["original_prompt"],
            "route": improvement["route"],
            "provider": provider_settings,
            "scope": refinement["scope"],
            "source_scope_ids": list(refinement["source_scope_ids"]),
        }

    def _direct_datalog_edit_unavailable(self) -> dict[str, object]:
        return {
            "available": False,
            "rejection": {
                "code": "generated_datalog.direct_edit_unavailable",
                "message": "Generated Datalog is inspectable but direct editing is unavailable in OSS v1.",
            },
        }

    def _deterministic_evidence_items(
        self,
        *,
        session_id: str,
        request: dict[str, object],
        generated_logic: dict[str, object],
    ) -> list[dict[str, object]]:
        topology = self._topology_for_session(session_id)
        evidence_map = topology["evidence_map"]
        matched_ids, diagnostics = self._resolve_generated_answer_ids(
            topology=topology,
            generated_logic=generated_logic,
        )
        if diagnostics:
            raise DatalogExecutionValidationError(diagnostics)
        return [
            {
                "id": topology_id,
                "kind": _topology_object_kind(topology=topology, topology_id=topology_id),
                "label": _topology_object_label(topology=topology, topology_id=topology_id),
                "source": "derived_graph_semantics",
                "generated_logic_excerpt": str(generated_logic["content"]).splitlines()[:3],
                "topology_evidence": evidence_map[topology_id],
            }
            for topology_id in matched_ids
        ]

    def _resolve_generated_answer_ids(
        self,
        *,
        topology: dict[str, object],
        generated_logic: dict[str, object],
    ) -> tuple[list[str], list[dict[str, str]]]:
        answer_symbols = _answer_symbols(str(generated_logic.get("content", "")))
        if not answer_symbols:
            return [], [
                {
                    "code": "generated_datalog.answer_shape_invalid",
                    "message": "Generated Datalog must declare, output, and populate answer(x:symbol).",
                }
            ]

        topology_ids_by_symbol = _topology_ids_by_answer_symbol(topology)
        matched_ids = []
        unresolved_symbols = []
        for symbol in answer_symbols:
            topology_id = topology_ids_by_symbol.get(symbol)
            if topology_id is None:
                unresolved_symbols.append(symbol)
                continue
            if topology_id not in matched_ids:
                matched_ids.append(topology_id)

        if unresolved_symbols:
            return [], [
                {
                    "code": "generated_datalog.answer_unresolved",
                    "message": (
                        "Generated Datalog answered unknown topology object(s): "
                        + ", ".join(unresolved_symbols)
                    ),
                }
            ]
        return matched_ids, []

    def _write_logic_request_result_artifact(
        self,
        *,
        session_id: str,
        result_artifact: dict[str, object],
    ) -> Path:
        return self._write_result_artifact(
            session_id=session_id,
            result_artifact=result_artifact,
            dirname="logic_request_results",
            filename_prefix="logic_request_result",
        )

    def _rule_pack_evidence_items(
        self,
        *,
        session_id: str,
        rule_result: dict[str, object],
    ) -> list[dict[str, object]]:
        topology = self._topology_for_session(session_id)
        topology_ids_by_node_id = self._topology_ids_by_source_node_id(topology)
        evidence = rule_result["evidence"]
        if not isinstance(evidence, dict):
            return []

        raw_objects = []
        for item in evidence.get("matched_objects", []):
            if isinstance(item, dict):
                raw_objects.append(item)
        for item in evidence.get("traversed_objects", []):
            if isinstance(item, dict):
                raw_objects.append(item)

        evidence_items = []
        seen_topology_ids = set()
        for item in raw_objects:
            topology_id = topology_ids_by_node_id.get(str(item["object_id"]))
            if topology_id is None or topology_id in seen_topology_ids:
                continue
            seen_topology_ids.add(topology_id)
            evidence_items.append(
                {
                    "id": topology_id,
                    "source": "rule_pack_result",
                    "rule_id": rule_result["rule_id"],
                    "class": item.get("class"),
                    "topology_evidence": topology["evidence_map"][topology_id],
                }
            )
        return evidence_items

    def _topology_ids_by_source_node_id(
        self, topology: dict[str, object]
    ) -> dict[str, str]:
        ids_by_source_node_id = {}
        for topology_id, evidence in topology["evidence_map"].items():
            canonical_fact = evidence["canonical_fact"]
            if canonical_fact["fact_type"] == "node":
                ids_by_source_node_id[str(canonical_fact["node_id"])] = str(topology_id)
        return ids_by_source_node_id

    def _write_result_artifact(
        self,
        *,
        session_id: str,
        result_artifact: dict[str, object],
        dirname: str,
        filename_prefix: str,
    ) -> Path:
        prefix = f"{session_id}/{dirname}"
        result_index = len(self._store.list(prefix, suffix=".json")) + 1
        key = f"{prefix}/{filename_prefix}_{result_index}.json"
        self._store.write_json(key, result_artifact)
        return self._local_path_for(key)

    def _local_path_for(self, key: str) -> Path:
        """Project a key to an absolute local path for the API contract.

        Preparation results and export manifests advertise absolute paths,
        which only a local store can honour. Bead 2afe.8 (hosted artifacts on
        object storage) has to revisit what those responses advertise; this is
        the one place in the flow that assumes a local backing.
        """

        root = getattr(self._store, "root", None)
        if root is None:
            raise TypeError("absolute artifact paths need a local-backed store")
        return root / key

    def _copy_prepared_artifacts(
        self, *, session_id: str, export_prefix: str
    ) -> list[dict[str, object]]:
        exported = []
        public_kinds = {
            "readiness_metadata": "readiness",
            "topology_view_model": "topology_view",
        }
        for kind, key in sorted(session_artifact_keys(session_id).items()):
            if not self._store.exists(key):
                continue
            public_kind = public_kinds.get(kind, kind)
            suffix = Path(key).suffix
            target_key = f"{export_prefix}/{public_kind}{suffix}"
            self._store.copy(key, target_key)
            exported.append(
                {
                    "kind": public_kind,
                    "path": str(self._local_path_for(target_key)),
                }
            )
        return exported

    def _copy_artifact_directory(
        self,
        *,
        session_id: str,
        source_dirname: str,
        export_prefix: str,
    ) -> list[dict[str, object]]:
        exported: list[dict[str, object]] = []
        for source_key in self._store.list(
            f"{session_id}/{source_dirname}", suffix=".json"
        ):
            name = source_key.rsplit("/", 1)[-1]
            target_key = f"{export_prefix}/{name}"
            self._store.copy(source_key, target_key)
            exported.append(
                {
                    "kind": source_dirname[:-1],
                    "path": str(self._local_path_for(target_key)),
                }
            )
        return exported

    def _write_missing_capability_exports(
        self, *, session_id: str, export_prefix: str
    ) -> list[dict[str, object]]:
        exported: list[dict[str, object]] = []
        for artifact in self._missing_capabilities_by_session.get(session_id, []):
            download = artifact["download"]
            if not isinstance(download, dict):
                continue
            filename = Path(str(download["filename"])).name
            target_key = f"{export_prefix}/{filename}"
            self._store.write_text(target_key, str(download["content"]))
            exported.append(
                {
                    "kind": "missing_capability",
                    "code": artifact["code"],
                    "message": artifact["message"],
                    "path": str(self._local_path_for(target_key)),
                }
            )
        return exported

    def _visible_source_scope(self, session_id: str) -> dict[str, object]:
        ids = self._visible_source_scope_by_session.get(session_id, [])
        topology = self._topology_for_session(session_id)
        evidence_map = topology["evidence_map"]
        return {
            "ids": list(ids),
            "items": [
                {
                    "id": topology_id,
                    "evidence": evidence_map[topology_id],
                }
                for topology_id in ids
            ],
        }

    def _evidence_highlight(self, session_id: str) -> dict[str, object]:
        highlight = self._evidence_highlight_by_session.get(session_id)
        if highlight is None:
            return {
                "source_scope_ids": [],
                "matched_object_ids": [],
                "paths": [],
            }
        return {
            "source_scope_ids": list(highlight["source_scope_ids"]),
            "matched_object_ids": list(highlight["matched_object_ids"]),
            "paths": [
                {
                    "id": path["id"],
                    "node_ids": list(path["node_ids"]),
                    "edge_ids": list(path["edge_ids"]),
                }
                for path in highlight["paths"]
            ],
        }
