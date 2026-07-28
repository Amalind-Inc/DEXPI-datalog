"""Workspace-scoped immutable artifacts reusable across identical source uploads."""

from __future__ import annotations

from typing import Any

from .artifact_store import ArtifactNotFound, ArtifactStore

_CACHE_SCHEMA = "source-preparation.v1"
_RENDER_FIELDS = (
    "nodes",
    "edges",
    "evidence_map",
    "pid_view",
    "schematic_scene",
    "schematic_scene_kind",
    "geometry_report",
)
_EMPTY_HIGHLIGHT = {"source_scope_ids": [], "matched_object_ids": [], "paths": []}


class SourcePreparationCache:
    """Persist source-derived facts separately from each review session."""

    def __init__(self, *, store: ArtifactStore, source_digest: str) -> None:
        self._store = store
        self._prefix = f"_source-cache/{_CACHE_SCHEMA}/{source_digest}"

    def store(
        self,
        *,
        graph_facts: dict[str, object],
        graph_facts_datalog: str,
        derived_semantics_datalog: str,
        topology: dict[str, object],
    ) -> None:
        self._store.write_json(f"{self._prefix}/graph_facts.json", graph_facts)
        self._store.write_text(f"{self._prefix}/graph_facts.dl", graph_facts_datalog)
        self._store.write_text(f"{self._prefix}/derived_graph_semantics.dl", derived_semantics_datalog)
        self._store.write_json(
            f"{self._prefix}/render_data.json",
            {field: topology.get(field) for field in _RENDER_FIELDS},
        )

    def materialize(
        self, *, session_id: str, source_id: str, source_path: str
    ) -> dict[str, Any]:
        graph_facts = self._read_json("graph_facts.json")
        render_data = self._read_json("render_data.json")
        topology = {
            "schema_version": "topology-view.v1",
            "session_id": session_id,
            "source_id": source_id,
            "source_path": source_path,
            **render_data,
            "evidence_highlight": dict(_EMPTY_HIGHLIGHT),
        }
        graph_facts_datalog = self._store.read_text(f"{self._prefix}/graph_facts.dl")
        derived_semantics_datalog = self._store.read_text(f"{self._prefix}/derived_graph_semantics.dl")
        self._store.write_json(f"{session_id}/{session_id}/graph_facts.json", graph_facts)
        self._store.write_text(f"{session_id}/graph_facts.dl", graph_facts_datalog)
        self._store.write_text(f"{session_id}/derived_graph_semantics.dl", derived_semantics_datalog)
        self._store.write_json(f"{session_id}/topology_view.json", topology)
        return {"graph_facts": graph_facts, "topology": topology}

    def available(self) -> bool:
        return all(self._store.exists(f"{self._prefix}/{name}") for name in (
            "graph_facts.json", "graph_facts.dl", "derived_graph_semantics.dl", "render_data.json"
        ))

    def _read_json(self, name: str) -> dict[str, Any]:
        value = self._store.read_json(f"{self._prefix}/{name}")
        if not isinstance(value, dict):
            raise ArtifactNotFound(f"{self._prefix}/{name}")
        return value
