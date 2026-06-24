from __future__ import annotations

from pathlib import Path
import time
from typing import Callable

from ..llm.logic_requests import route_logic_request, route_without_model_access
from ..llm.model_access import supported_byok_provider
from ..workflow.review_session import ReviewSessionService


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
        self._topology_by_session: dict[str, dict[str, object]] = {}
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
