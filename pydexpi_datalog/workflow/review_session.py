from __future__ import annotations

import hashlib
import json
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..export.pipeline import export_graph_facts_artifact
from ..semantics.derive_graph_semantics import (
    TOPOLOGY_ATTR_NAMES,
    build_derived_graph_semantics_datalog,
    build_graph_facts_datalog,
)
from .artifact_store import ArtifactStore
from .geometry_gate import evaluate_geometry_gate
from .pid_view import build_pid_view
from .schematic_scene import build_schematic_scene_report, has_drawable_geometry
from .topology_naming import derive_display_names


@dataclass(frozen=True)
class PreparationLimits:
    """Configurable boundaries for preparing a single DEXPI source.

    Defaults accept every bundled DEXPI 1.3 example P&ID; individual limits can
    be lowered to enforce stricter operational policy.
    """

    max_upload_bytes: int = 5_000_000
    max_xml_elements: int = 50_000
    max_xml_depth: int = 64
    max_preparation_seconds: float = 30.0
    max_graph_nodes: int = 5_000
    max_graph_edges: int = 10_000
    max_artifact_bytes: int = 50_000_000


def compute_source_id(dexpi_xml_path: Path) -> str:
    digest = hashlib.sha256(dexpi_xml_path.read_bytes()).hexdigest()[:16]
    return f"source-{digest}"


class ReviewSessionService:
    """Prepare one uploaded DEXPI source file for the web review workflow."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        limits: PreparationLimits | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.store = store
        self._limits = limits or PreparationLimits()
        self._clock = clock
        self._requests_by_session: dict[str, Path] = {}
        self._ready_source_by_session: dict[str, str] = {}

    def start_preparation(
        self, *, dexpi_xml_path: Path, session_id: str | None = None
    ) -> dict[str, object]:
        session_id = session_id or f"session-{uuid.uuid4().hex}"
        self._requests_by_session[session_id] = dexpi_xml_path
        return self._run_preparation(
            dexpi_xml_path=dexpi_xml_path,
            session_id=session_id,
            attempt=1,
        )

    def retry_preparation(self, *, session_id: str) -> dict[str, object]:
        dexpi_xml_path = self._requests_by_session.get(session_id)
        if dexpi_xml_path is None:
            return self._failed_result(
                session_id=session_id,
                attempt=1,
                diagnostics=[
                    diagnostic(
                        code="session.unknown",
                        message=f"No preparation request is known for session: {session_id}",
                    )
                ],
            )
        return self._run_preparation(
            dexpi_xml_path=dexpi_xml_path,
            session_id=session_id,
            attempt=2,
        )

    def _run_preparation(
        self, *, dexpi_xml_path: Path, session_id: str, attempt: int
    ) -> dict[str, object]:
        if not dexpi_xml_path.exists():
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
                diagnostics=[
                    diagnostic(
                        code="upload.missing_file",
                        message=(
                            "Uploaded DEXPI source file does not exist: "
                            f"{dexpi_xml_path}"
                        ),
                    )
                ],
            )

        source_id = compute_source_id(dexpi_xml_path)
        prepared_source_id = self._ready_source_by_session.get(session_id)
        if prepared_source_id is not None and prepared_source_id != source_id:
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
                source_id=prepared_source_id,
                diagnostics=[
                    diagnostic(
                        code="source.already_prepared",
                        message=(
                            "This chat already prepared a source. Start a new chat "
                            "to review a different DEXPI source."
                        ),
                    )
                ],
            )

        validation_diagnostics = validate_upload_input(
            dexpi_xml_path, limits=self._limits
        )
        if validation_diagnostics:
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
                source_id=source_id,
                diagnostics=validation_diagnostics,
            )

        stage_history = [
            stage("queued", "queued"),
            stage("running", "validating upload"),
            stage("running", "extracting graph facts"),
        ]
        try:
            started_at = self._clock()
            # The export pipeline writes graph_facts.json into a directory it
            # is handed, so preparation borrows a real one from the store.
            with self.store.local_dir(session_id) as session_dir:
                graph_facts = export_graph_facts_artifact(
                    dexpi_xml_path=dexpi_xml_path,
                    fixture_id=session_id,
                    output_dir=session_dir,
                )

            graph_limit_diagnostics = check_graph_size_limits(
                graph=graph_facts["graph"], limits=self._limits
            )
            if graph_limit_diagnostics:
                return self._failed_result(
                    session_id=session_id,
                    attempt=attempt,
                    source_id=source_id,
                    diagnostics=graph_limit_diagnostics,
                )

            stage_history.append(stage("running", "deriving graph facts datalog"))
            graph_facts_datalog = build_graph_facts_datalog(graph_facts)
            self.store.write_text(
                f"{session_id}/graph_facts.dl", graph_facts_datalog
            )

            stage_history.append(stage("running", "deriving graph semantics"))
            derived_graph_semantics = build_derived_graph_semantics_datalog(graph_facts)
            self.store.write_text(
                f"{session_id}/derived_graph_semantics.dl", derived_graph_semantics
            )

            stage_history.append(stage("running", "building topology view model"))
            topology_view = build_topology_view_model(
                graph_facts=graph_facts,
                session_id=session_id,
                source_id=source_id,
                dexpi_xml_path=dexpi_xml_path,
            )
            artifact_paths = session_artifact_paths(self.store, session_id)
            self.store.write_json(f"{session_id}/topology_view.json", topology_view)

            readiness = {
                "state": "ready",
                "session_id": session_id,
                "source_id": source_id,
                "graph": graph_facts["graph"],
                "diagnostics": [],
                "topology_view_model_path": artifact_paths["topology_view_model"],
            }
            self.store.write_json(f"{session_id}/readiness.json", readiness)

            artifacts = artifact_paths

            elapsed_seconds = self._clock() - started_at
            time_limit_diagnostics = check_preparation_time_limit(
                elapsed_seconds=elapsed_seconds, limits=self._limits
            )
            if time_limit_diagnostics:
                return self._failed_result(
                    session_id=session_id,
                    attempt=attempt,
                    source_id=source_id,
                    diagnostics=time_limit_diagnostics,
                )

            artifact_limit_diagnostics = check_artifact_size_limits(
                store=self.store, session_id=session_id, limits=self._limits
            )
            if artifact_limit_diagnostics:
                return self._failed_result(
                    session_id=session_id,
                    attempt=attempt,
                    source_id=source_id,
                    diagnostics=artifact_limit_diagnostics,
                )

            stage_history.append(stage("succeeded", "ready"))
            self._ready_source_by_session[session_id] = source_id

            return {
                "session_id": session_id,
                "source_id": source_id,
                "job": {
                    "job_id": f"{session_id}:prepare:{attempt}",
                    "kind": "session_preparation",
                    "status": "succeeded",
                    "stage": "ready",
                    "stage_history": stage_history,
                    "attempt": attempt,
                },
                "readiness": readiness,
                "topology_view": topology_view,
                "artifacts": artifacts,
                "diagnostics": [],
            }
        except Exception as error:  # pyDEXPI has parser and conversion exceptions.
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
                source_id=source_id,
                diagnostics=[
                    diagnostic(
                        code="preparation.failed",
                        message="Session preparation failed while extracting or deriving artifacts.",
                        raw_details=str(error),
                    )
                ],
            )

    def _failed_result(
        self,
        *,
        session_id: str,
        attempt: int,
        diagnostics: list[dict[str, object]],
        source_id: str | None = None,
    ) -> dict[str, object]:
        readiness = {
            "state": "failed",
            "session_id": session_id,
            "source_id": source_id,
            "diagnostics": diagnostics,
        }
        self.store.write_json(f"{session_id}/readiness.json", readiness)
        readiness_path = session_artifact_paths(self.store, session_id)[
            "readiness_metadata"
        ]
        return {
            "session_id": session_id,
            "source_id": source_id,
            "job": {
                "job_id": f"{session_id}:prepare:{attempt}",
                "kind": "session_preparation",
                "status": "failed",
                "stage": "failed",
                "stage_history": [
                    stage("queued", "queued"),
                    stage("failed", "failed"),
                ],
                "attempt": attempt,
            },
            "readiness": readiness,
            "topology_view": None,
            "artifacts": {"readiness_metadata": str(readiness_path)},
            "diagnostics": diagnostics,
        }


def validate_upload_input(
    dexpi_xml_path: Path, *, limits: PreparationLimits | None = None
) -> list[dict[str, object]]:
    limits = limits or PreparationLimits()
    if not dexpi_xml_path.exists():
        return [
            diagnostic(
                code="upload.missing_file",
                message=f"Uploaded process document does not exist: {dexpi_xml_path}",
            )
        ]
    if dexpi_xml_path.suffix.lower() != ".xml":
        return [
            diagnostic(
                code="upload.non_xml",
                message="Uploaded process document must be a supported DEXPI XML file.",
            )
        ]

    upload_bytes = dexpi_xml_path.stat().st_size
    if upload_bytes > limits.max_upload_bytes:
        return [
            diagnostic(
                code="limit.upload_bytes_exceeded",
                message=(
                    f"Uploaded source is {upload_bytes} bytes, exceeding the "
                    f"{limits.max_upload_bytes}-byte upload limit."
                ),
            )
        ]

    try:
        tree = ET.parse(dexpi_xml_path)
    except ET.ParseError as error:
        return [
            diagnostic(
                code="upload.xml_parse_failed",
                message="Uploaded XML could not be parsed.",
                raw_details=str(error),
            )
        ]

    root = tree.getroot()
    plant_information = root.find("PlantInformation")
    application = (
        plant_information.attrib.get("Application", "")
        if plant_information is not None
        else ""
    )
    if root.tag != "PlantModel" or application.lower() != "dexpi":
        return [
            diagnostic(
                code="upload.non_dexpi_xml",
                message="Uploaded XML is not a DEXPI PlantModel document.",
            )
        ]

    element_count = sum(1 for _ in root.iter())
    if element_count > limits.max_xml_elements:
        return [
            diagnostic(
                code="limit.xml_elements_exceeded",
                message=(
                    f"Uploaded source has {element_count} XML elements, exceeding the "
                    f"{limits.max_xml_elements}-element complexity limit."
                ),
            )
        ]

    element_depth = _xml_depth(root)
    if element_depth > limits.max_xml_depth:
        return [
            diagnostic(
                code="limit.xml_depth_exceeded",
                message=(
                    f"Uploaded source nests {element_depth} XML levels, exceeding the "
                    f"{limits.max_xml_depth}-level complexity limit."
                ),
            )
        ]

    return []


def _xml_depth(element: ET.Element) -> int:
    return 1 + max((_xml_depth(child) for child in element), default=0)


def check_graph_size_limits(
    *, graph: dict[str, object], limits: PreparationLimits
) -> list[dict[str, object]]:
    node_count = int(graph.get("node_count", 0))
    if node_count > limits.max_graph_nodes:
        return [
            diagnostic(
                code="limit.graph_nodes_exceeded",
                message=(
                    f"Extracted graph has {node_count} nodes, exceeding the "
                    f"{limits.max_graph_nodes}-node graph limit."
                ),
            )
        ]
    edge_count = int(graph.get("edge_count", 0))
    if edge_count > limits.max_graph_edges:
        return [
            diagnostic(
                code="limit.graph_edges_exceeded",
                message=(
                    f"Extracted graph has {edge_count} edges, exceeding the "
                    f"{limits.max_graph_edges}-edge graph limit."
                ),
            )
        ]
    return []


def check_preparation_time_limit(
    *, elapsed_seconds: float, limits: PreparationLimits
) -> list[dict[str, object]]:
    if elapsed_seconds > limits.max_preparation_seconds:
        return [
            diagnostic(
                code="limit.preparation_time_exceeded",
                message=(
                    f"Preparation took {elapsed_seconds:.3f}s, exceeding the "
                    f"{limits.max_preparation_seconds}s processing-time limit."
                ),
            )
        ]
    return []


def check_artifact_size_limits(
    *, store: ArtifactStore, session_id: str, limits: PreparationLimits
) -> list[dict[str, object]]:
    for kind, key in sorted(session_artifact_keys(session_id).items()):
        if not store.exists(key):
            continue
        artifact_bytes = store.size(key)
        if artifact_bytes > limits.max_artifact_bytes:
            return [
                diagnostic(
                    code="limit.artifact_bytes_exceeded",
                    message=(
                        f"Prepared artifact '{kind}' is {artifact_bytes} bytes, "
                        f"exceeding the {limits.max_artifact_bytes}-byte artifact limit."
                    ),
                )
            ]
    return []


def build_topology_view_model(
    *,
    graph_facts: dict[str, object],
    session_id: str,
    source_id: str | None = None,
    dexpi_xml_path: Path | None = None,
) -> dict[str, object]:
    # Document-level provenance; kept distinct from per-edge graph endpoint ids
    # (which also use the name "source_id") below.
    document_source_id = source_id
    fact_nodes = graph_facts["facts"]["nodes"]
    fact_edges = graph_facts["facts"]["edges"]

    node_ids_by_raw_id = build_stable_node_id_map(fact_nodes)
    display_names = derive_display_names(fact_nodes, fact_edges)
    nodes = []
    evidence_map: dict[str, dict[str, object]] = {}
    for node in sorted(
        fact_nodes, key=lambda item: node_ids_by_raw_id[item["node_id"]]
    ):
        stable_node_id = node_ids_by_raw_id[node["node_id"]]
        naming = display_names.get(node["node_id"], {})
        nodes.append(
            {
                "id": stable_node_id,
                # `label` stays the raw DEXPI class for downstream Datalog/semantics.
                "label": node["attributes"].get("label", stable_node_id),
                "tag_name": node["attributes"].get("tagName"),
                # Engineer-facing identifiers derived from the DEXPI hierarchy.
                "display_name": naming.get("display_name") or stable_node_id,
                "class_name": naming.get("class_name", ""),
                "category": naming.get("category", "other"),
                "description": naming.get("description", ""),
                "proteus_id": node["attributes"].get("proteusId"),
                "canonical_fact_id": stable_node_id,
                "source_graph_node_id": node["node_id"],
            }
        )
        evidence_map[stable_node_id] = {
            "kind": "node",
            "topology_id": stable_node_id,
            "source_id": document_source_id,
            "canonical_fact": {
                "fact_type": "node",
                "node_id": node["node_id"],
            },
        }

    topology_edges = []
    for edge in sorted(
        fact_edges,
        key=lambda item: (
            item["source_id"],
            item["target_id"],
            str(item["edge_key"]),
            str(item["attributes"].get("attr_name", "")),
        ),
    ):
        attr_name = edge["attributes"].get("attr_name")
        if attr_name not in TOPOLOGY_ATTR_NAMES:
            continue
        edge_key = str(edge["edge_key"])
        source_id = node_ids_by_raw_id[edge["source_id"]]
        target_id = node_ids_by_raw_id[edge["target_id"]]
        edge_id = stable_hash_id(
            "edge",
            {
                "source_id": source_id,
                "target_id": target_id,
                "edge_key": edge_key,
                "relationship": attr_name,
                "edge_family": edge["attributes"].get("label"),
            },
        )
        topology_edges.append(
            {
                "id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "relationship": attr_name,
                "edge_family": edge["attributes"].get("label"),
                "canonical_fact_id": edge_id,
                "source_graph_edge": {
                    "source_id": edge["source_id"],
                    "target_id": edge["target_id"],
                    "edge_key": edge_key,
                },
            }
        )
        evidence_map[edge_id] = {
            "kind": "edge",
            "topology_id": edge_id,
            "source_id": document_source_id,
            "canonical_fact": {
                "fact_type": "edge",
                "source_id": edge["source_id"],
                "target_id": edge["target_id"],
                "edge_key": edge_key,
            },
        }

    raw_schematic_scene = None
    if dexpi_xml_path is not None:
        proteus_id_to_topology_id = {
            node["proteus_id"]: node["id"] for node in nodes if node.get("proteus_id")
        }
        raw_schematic_scene = build_schematic_scene_report(
            dexpi_xml_path=dexpi_xml_path,
            proteus_id_to_topology_id=proteus_id_to_topology_id,
            namespace=document_source_id or session_id,
        )

    # Geometry sanity gate (bead pydexpi-datalog-1-2ki.5): the gate outcome,
    # not just geometry presence, decides whether the scene is disclosed as
    # drawn. Files failing the gate degrade to the auto-layout schematic view
    # (frontend-computed, per ADR 0005's tolerated client-side exception) --
    # source positions are never mixed with invented ones, so a gate failure
    # drops the scene entirely rather than presenting it partially "as drawn".
    geometry_report = evaluate_geometry_gate(raw_schematic_scene)
    drawable = raw_schematic_scene is not None and has_drawable_geometry(raw_schematic_scene)
    if drawable and geometry_report["passed"]:
        schematic_scene = raw_schematic_scene
        schematic_scene_kind = "as-drawn"
    elif raw_schematic_scene is not None:
        schematic_scene = None
        schematic_scene_kind = "auto-layout"
    else:
        schematic_scene = None
        schematic_scene_kind = "none"

    return {
        "schema_version": "topology-view.v1",
        "session_id": session_id,
        "source_id": document_source_id,
        "source_path": graph_facts["source_path"],
        "nodes": nodes,
        "edges": topology_edges,
        "evidence_map": evidence_map,
        # P&ID-like compression: equipment units + collapsed lines, for the graph panel.
        "pid_view": build_pid_view(nodes, fact_edges),
        # Drawing-faithful tier-1 scene (ADR 0004/0005); None when the source
        # carries no geometry, or when the geometry sanity gate fails
        # (bead pydexpi-datalog-1-2ki.5) -- source positions are never
        # disclosed as drawn once the gate rejects them.
        "schematic_scene": schematic_scene,
        # "as-drawn" | "auto-layout" | "none" -- the gate's disclosure of
        # which schematic tier the frontend must present. Kept backend-owned
        # even though auto-layout position computation itself may run
        # client-side (ADR 0005).
        "schematic_scene_kind": schematic_scene_kind,
        "geometry_report": geometry_report,
        "evidence_highlight": {
            "source_scope_ids": [],
            "matched_object_ids": [],
            "paths": [],
        },
    }


def build_stable_node_id_map(fact_nodes: list[dict[str, object]]) -> dict[str, str]:
    ids_by_raw_id: dict[str, str] = {}
    signature_counts: dict[str, int] = {}
    for node in sorted(
        fact_nodes,
        key=lambda item: json.dumps(item["attributes"], sort_keys=True),
    ):
        stable_base = stable_hash_id("node", node["attributes"])
        signature_counts[stable_base] = signature_counts.get(stable_base, 0) + 1
        suffix = signature_counts[stable_base]
        stable_id = stable_base if suffix == 1 else f"{stable_base}-{suffix}"
        ids_by_raw_id[node["node_id"]] = stable_id
    return ids_by_raw_id


def build_evidence_highlight_payload(
    *,
    topology_view: dict[str, object],
    source_scope_ids: list[str],
    matched_object_ids: list[str],
    paths: list[dict[str, object]],
) -> dict[str, object]:
    known_ids = set(topology_view["evidence_map"])
    highlight_ids = set(source_scope_ids) | set(matched_object_ids)
    for path in paths:
        highlight_ids.update(path.get("node_ids", []))
        highlight_ids.update(path.get("edge_ids", []))

    unknown_ids = sorted(highlight_ids - known_ids)
    if unknown_ids:
        raise ValueError(f"unknown topology id in evidence highlight: {unknown_ids[0]}")

    return {
        "source_scope_ids": list(source_scope_ids),
        "matched_object_ids": list(matched_object_ids),
        "paths": [
            {
                "id": path["id"],
                "node_ids": list(path.get("node_ids", [])),
                "edge_ids": list(path.get("edge_ids", [])),
            }
            for path in paths
        ],
    }


def stable_hash_id(prefix: str, payload: object) -> str:
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def diagnostic(
    *, code: str, message: str, raw_details: str | None = None
) -> dict[str, object]:
    item: dict[str, object] = {
        "severity": "error",
        "code": code,
        "message": message,
    }
    if raw_details is not None:
        item["raw_details"] = raw_details
    return item


def stage(status: str, text: str) -> dict[str, str]:
    return {"status": status, "text": text}


def session_artifact_keys(session_id: str) -> dict[str, str]:
    """The artifacts a ready session leaves in the store, keyed by their role.

    This is the single definition of that layout, so a session reloaded after
    a restart resolves exactly the artifacts its preparation wrote.
    """

    return {
        "graph_facts_json": f"{session_id}/{session_id}/graph_facts.json",
        "graph_facts_datalog": f"{session_id}/graph_facts.dl",
        "derived_graph_semantics_datalog": f"{session_id}/derived_graph_semantics.dl",
        "readiness_metadata": f"{session_id}/readiness.json",
        "topology_view_model": f"{session_id}/topology_view.json",
    }


def session_artifact_paths(store: ArtifactStore, session_id: str) -> dict[str, str]:
    """Where each of a session's artifacts can be fetched from.

    A URL, not a path, and the same shape in both deployment profiles: a
    `file://` URL locally, a presigned object-store URL when hosted
    (bead 2afe.8). Before that, this read `store.root` and raised for any
    store that had no directory behind it, which made a hosted deployment
    fail at the end of a successful preparation.

    The wire field names still say `path`. Renaming them is a client-visible
    change worth making deliberately rather than folding into this one.
    """

    return {
        role: store.download_url(key)
        for role, key in session_artifact_keys(session_id).items()
    }
