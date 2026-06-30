from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import time
from typing import Callable

from ..llm.logic_requests import (
    parse_model_draft_response,
    route_logic_request,
    route_without_model_access,
)
from ..llm.model_access import ModelProvider, require_native_tool_capable_model
from ..qa.flow_direction import (
    classify_path_direction_basis,
    detect_directed_intent,
    direction_annotation_key,
    effective_direction,
    evaluation_boundary,
)
from ..qa.grounded_qa_harness import (
    ConversationTurn,
    QATurnProvider,
    run_grounded_qa_turn,
)
from ..qa.topology_tools import TopologyTools
from ..workflow.review_session import (
    PreparationLimits,
    ReviewSessionService,
    build_evidence_highlight_payload,
)
from ..verification.verify_suite import evaluate_graph_fixture


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
        artifact_root: Path,
        limits: PreparationLimits | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._service = ReviewSessionService(
            artifact_root=artifact_root, limits=limits
        )
        self._clock = clock
        self._timing_records: list[dict[str, object]] = []
        self._artifacts_by_session: dict[str, dict[str, object]] = {}
        self._topology_by_session: dict[str, dict[str, object]] = {}
        self._evidence_highlight_by_session: dict[str, dict[str, object]] = {}
        self._visible_source_scope_by_session: dict[str, list[str]] = {}
        self._last_selected_by_session: dict[str, str] = {}
        self._provider_settings_by_session: dict[str, dict[str, object]] = {}
        self._credentials_by_session: dict[str, str] = {}
        self._rule_pack_results_by_session: dict[str, list[dict[str, object]]] = {}
        self._missing_capabilities_by_session: dict[str, list[dict[str, object]]] = {}
        self._direction_annotations_by_session: dict[
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
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        graph_facts_path = Path(
            str(self._artifacts_by_session[session_id]["graph_facts_json"])
        )
        graph_facts = json.loads(graph_facts_path.read_text(encoding="utf-8"))
        rule_result = evaluate_graph_fixture(graph_facts, rule_id=rule_id)
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
            "outcome": str(rule_result["result_type"]),
            "confirmation": {"required": False},
            "summary": {
                "position": "first",
                "text": f"{rule_id}: {rule_result['result_type']}. {rule_result['message']}",
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

    def configure_provider_settings(
        self,
        *,
        session_id: str,
        provider: str,
        model: str,
        credential: str,
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        require_native_tool_capable_model(provider=provider, model=model)
        self._credentials_by_session[session_id] = credential
        self._provider_settings_by_session[session_id] = {
            "provider": provider,
            "model": model,
            "configured": bool(credential),
        }
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
        self, *, session_id: str, export_dir: Path
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        export_dir.mkdir(parents=True, exist_ok=True)

        prepared_artifacts = self._copy_prepared_artifacts(
            session_id=session_id,
            export_dir=export_dir / "prepared",
        )
        logic_request_results = self._copy_artifact_directory(
            session_id=session_id,
            source_dirname="logic_request_results",
            export_dir=export_dir / "logic_request_results",
        )
        rule_pack_results = self._copy_artifact_directory(
            session_id=session_id,
            source_dirname="rule_pack_results",
            export_dir=export_dir / "rule_pack_results",
        )
        missing_capabilities = self._write_missing_capability_exports(
            session_id=session_id,
            export_dir=export_dir / "missing_capabilities",
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
        manifest_path = export_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return {
            "status": "exported",
            "session_id": session_id,
            "export_dir": str(export_dir),
            "manifest_path": str(manifest_path),
            "manifest": manifest,
        }

    def run_qa_turn(
        self,
        *,
        session_id: str,
        question: str,
        qa_provider: QATurnProvider,
        conversation: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        topology = self._topology_for_session(session_id)
        answer = self._compute_qa_answer(
            topology=topology,
            session_id=session_id,
            question=question,
            qa_provider=qa_provider,
            conversation=conversation,
        )

        directed = detect_directed_intent(question)
        primary = self._primary_witness_path(answer["valid_paths"])
        if directed is None or primary is None:
            return self._answered_payload(session_id, answer)

        edge_relationships = {
            str(edge["id"]): str(edge["relationship"]) for edge in topology["edges"]
        }
        basis = classify_path_direction_basis(
            [edge_relationships.get(eid, "") for eid in primary["edge_ids"]]
        )
        boundary = evaluation_boundary(directed)
        source_id = topology.get("source_id")
        review_key = direction_annotation_key(
            source_id=str(source_id) if source_id else None,
            evaluation_boundary=boundary,
            node_ids=primary["node_ids"],
            edge_ids=primary["edge_ids"],
        )

        if basis == "explicit":
            direction = {
                "proposed_direction": directed,
                "effective_direction": directed,
                "direction_basis": "explicit",
                "review_status": "confirmed",
                "evaluation_boundary": boundary,
                "review_key": review_key,
                "review_required": False,
            }
            return self._answered_payload(session_id, answer, direction=direction)

        annotation = self._direction_annotations_by_session.get(session_id, {}).get(
            review_key
        )
        if annotation is None:
            return self._needs_direction_review_payload(
                session_id=session_id,
                question=question,
                topology=topology,
                proposed_direction=directed,
                basis=basis,
                boundary=boundary,
                source_id=source_id,
                review_key=review_key,
                primary=primary,
                answer=answer,
            )

        review_status = str(annotation["review_status"])
        direction = {
            "proposed_direction": directed,
            "effective_direction": effective_direction(
                proposed_direction=directed, review_status=review_status
            ),
            "direction_basis": basis,
            "review_status": review_status,
            "evaluation_boundary": boundary,
            "review_key": review_key,
            "review_required": False,
        }
        return self._answered_payload(session_id, answer, direction=direction)

    def submit_direction_review(
        self,
        *,
        session_id: str,
        question: str,
        decision: str,
        review_key: str,
        qa_provider: QATurnProvider,
        conversation: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        review_status = {
            "confirm": "confirmed",
            "reverse": "reversed",
            "unknown": "unknown",
        }.get(decision)
        if review_status is None:
            raise ValueError(
                "direction review decision must be confirm, reverse, or unknown"
            )
        # Ensure the session is ready before recording the annotation.
        self._topology_for_session(session_id)

        # Persist the reviewer's judgement keyed to the exact witness identity the
        # review card was raised for. The session annotation never mutates the graph.
        self._direction_annotations_by_session.setdefault(session_id, {})[review_key] = {
            "review_status": review_status,
        }

        # Resume the original question; run_qa_turn recomputes the same key from the
        # (source, path, evaluation boundary) and applies the stored annotation.
        return self.run_qa_turn(
            session_id=session_id,
            question=question,
            qa_provider=qa_provider,
            conversation=conversation,
        )

    def _compute_qa_answer(
        self,
        *,
        topology: dict[str, object],
        session_id: str,
        question: str,
        qa_provider: QATurnProvider,
        conversation: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        graph_facts_path = Path(
            str(self._artifacts_by_session[session_id]["graph_facts_json"])
        )
        graph_facts = json.loads(graph_facts_path.read_text(encoding="utf-8"))
        tools = TopologyTools(
            topology_view=topology,
            session_id=session_id,
            graph_facts=graph_facts,
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
        result = run_grounded_qa_turn(
            question=question,
            topology_tools=tools,
            provider=qa_provider,
            conversation=prior_turns,
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
        }

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

    def _answered_payload(
        self,
        session_id: str,
        answer: dict[str, object],
        *,
        direction: dict[str, object] | None = None,
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
        if direction is not None:
            answer_text = self._direction_prefixed_answer(answer_text, direction)

        payload = {
            "status": "answered",
            "session_id": session_id,
            "answer_text": answer_text,
            "evidence_references": list(result.evidence_references),
            "rejected_references": list(result.rejected_references),
            "interpreted_object_ids": list(result.interpreted_object_ids),
            "evidence_highlight": evidence_highlight,
        }
        if direction is not None:
            payload["direction"] = direction
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

    def _needs_direction_review_payload(
        self,
        *,
        session_id: str,
        question: str,
        topology: dict[str, object],
        proposed_direction: str,
        basis: str,
        boundary: str,
        source_id: object,
        review_key: str,
        primary: dict[str, object],
        answer: dict[str, object],
    ) -> dict[str, object]:
        witness_highlight = build_evidence_highlight_payload(
            topology_view=topology,
            source_scope_ids=[],
            matched_object_ids=[str(primary["id"])],
            paths=[primary],
        )
        self._evidence_highlight_by_session[session_id] = witness_highlight
        return {
            "status": "needs_direction_review",
            "session_id": session_id,
            "question": question,
            "direction_review": {
                "review_key": review_key,
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
            },
            "answer_text": (
                "Before answering, please review the inferred flow direction for "
                "the highlighted witness."
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
            self._topology_by_session[str(result["session_id"])] = result["topology_view"]
            self._artifacts_by_session[str(result["session_id"])] = dict(
                result["artifacts"]
            )
            self._evidence_highlight_by_session[str(result["session_id"])] = dict(
                result["topology_view"]["evidence_highlight"]
            )
            self._visible_source_scope_by_session[str(result["session_id"])] = []
            self._rule_pack_results_by_session[str(result["session_id"])] = []
            self._missing_capabilities_by_session[str(result["session_id"])] = []

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

    def _topology_for_session(self, session_id: str) -> dict[str, object]:
        topology = self._topology_by_session.get(session_id)
        if topology is None:
            raise ValueError(f"No ready topology is known for session: {session_id}")
        return topology

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
        session_dir = self._service.artifact_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        result_dir = session_dir / "logic_request_results"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_index = len(list(result_dir.glob("logic_request_result_*.json"))) + 1
        result_path = result_dir / f"logic_request_result_{result_index}.json"
        result_path.write_text(
            json.dumps(result_artifact, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return result_path

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
        session_dir = self._service.artifact_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        result_dir = session_dir / dirname
        result_dir.mkdir(parents=True, exist_ok=True)
        result_index = len(list(result_dir.glob(f"{filename_prefix}_*.json"))) + 1
        result_path = result_dir / f"{filename_prefix}_{result_index}.json"
        result_path.write_text(
            json.dumps(result_artifact, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return result_path

    def _copy_prepared_artifacts(
        self, *, session_id: str, export_dir: Path
    ) -> list[dict[str, object]]:
        exported = []
        public_kinds = {
            "readiness_metadata": "readiness",
            "topology_view_model": "topology_view",
        }
        for kind, source_path in sorted(self._artifacts_by_session[session_id].items()):
            source = Path(str(source_path))
            if not source.is_file():
                continue
            public_kind = public_kinds.get(kind, kind)
            target = export_dir / f"{public_kind}{source.suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            exported.append(
                {
                    "kind": public_kind,
                    "path": str(target),
                }
            )
        return exported

    def _copy_artifact_directory(
        self,
        *,
        session_id: str,
        source_dirname: str,
        export_dir: Path,
    ) -> list[dict[str, object]]:
        source_dir = self._service.artifact_root / session_id / source_dirname
        if not source_dir.is_dir():
            return []

        exported = []
        export_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted(source_dir.glob("*.json")):
            target = export_dir / source.name
            shutil.copyfile(source, target)
            exported.append(
                {
                    "kind": source_dirname[:-1],
                    "path": str(target),
                }
            )
        return exported

    def _write_missing_capability_exports(
        self, *, session_id: str, export_dir: Path
    ) -> list[dict[str, object]]:
        exported = []
        missing_capabilities = self._missing_capabilities_by_session.get(session_id, [])
        if not missing_capabilities:
            return exported

        export_dir.mkdir(parents=True, exist_ok=True)
        for artifact in missing_capabilities:
            download = artifact["download"]
            if not isinstance(download, dict):
                continue
            filename = Path(str(download["filename"])).name
            target = export_dir / filename
            target.write_text(str(download["content"]), encoding="utf-8")
            exported.append(
                {
                    "kind": "missing_capability",
                    "code": artifact["code"],
                    "message": artifact["message"],
                    "path": str(target),
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
