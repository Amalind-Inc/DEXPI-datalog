from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Callable

from ..llm.logic_requests import (
    parse_model_draft_response,
    route_logic_request,
    route_without_model_access,
)
from ..llm.model_access import ModelProvider, supported_byok_provider
from ..workflow.review_session import (
    ReviewSessionService,
    build_evidence_highlight_payload,
)


class ChainlitReviewFlow:
    """Chainlit-facing state model for the single-file review workflow."""

    def __init__(
        self,
        *,
        artifact_root: Path,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._service = ReviewSessionService(artifact_root=artifact_root)
        self._clock = clock
        self._timing_records: list[dict[str, object]] = []
        self._artifacts_by_session: dict[str, dict[str, object]] = {}
        self._topology_by_session: dict[str, dict[str, object]] = {}
        self._evidence_highlight_by_session: dict[str, dict[str, object]] = {}
        self._visible_source_scope_by_session: dict[str, list[str]] = {}
        self._last_selected_by_session: dict[str, str] = {}
        self._provider_settings_by_session: dict[str, dict[str, object]] = {}
        self._credentials_by_session: dict[str, str] = {}

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
                "label": node["label"],
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
                result["missing_capability"] = self._missing_capability_artifact(
                    session_id=session_id,
                    prompt=prompt,
                    diagnostics=list(routed["diagnostics"]),
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

        response = provider.complete(
            request=str(refinement["refined_prompt"]),
            context={
                "route": improvement["route"],
                "provider": provider_settings,
                "scope": refinement["scope"],
                "source_scope_ids": list(refinement["source_scope_ids"]),
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
            "direct_datalog_edit": self._direct_datalog_edit_unavailable(),
            "diagnostics": [],
        }

    def execute_confirmed_logic_request(
        self,
        *,
        session_id: str,
        confirmation: dict[str, object],
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

        evidence_items = self._deterministic_evidence_items(
            session_id=session_id,
            request=request,
            generated_logic=generated_logic,
        )
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
        evidence_count = len(evidence_items)
        return {
            "status": "answered",
            "session_id": session_id,
            "request": request,
            "summary": {
                "position": "first",
                "text": (
                    f"Deterministic execution produced {evidence_count} evidence "
                    f"item{'s' if evidence_count != 1 else ''}."
                ),
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

    def configure_provider_settings(
        self,
        *,
        session_id: str,
        provider: str,
        model: str,
        credential: str,
    ) -> dict[str, object]:
        self._topology_for_session(session_id)
        supported_byok_provider(provider)
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
        source_scope_ids = list(request["source_scope_ids"])
        topology = self._topology_for_session(session_id)
        evidence_map = topology["evidence_map"]
        matched_ids = source_scope_ids or [
            str(node["id"]) for node in topology["nodes"][:1]
        ]
        return [
            {
                "id": topology_id,
                "source": "derived_graph_semantics",
                "generated_logic_excerpt": str(generated_logic["content"]).splitlines()[:3],
                "topology_evidence": evidence_map[topology_id],
            }
            for topology_id in matched_ids
        ]

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
