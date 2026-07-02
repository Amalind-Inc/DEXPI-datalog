from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import hashlib
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Callable

from ..export.pipeline import export_graph_facts_artifact
from ..semantics.derive_graph_semantics import (
    TOPOLOGY_ATTR_NAMES,
    build_derived_graph_semantics_datalog,
    build_graph_facts_datalog,
)
from .topology_naming import derive_display_names
from .pid_view import build_pid_view


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
        artifact_root: Path,
        limits: PreparationLimits | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.artifact_root = artifact_root
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

        session_dir = self.artifact_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        stage_history = [
            stage("queued", "queued"),
            stage("running", "validating upload"),
            stage("running", "extracting graph facts"),
        ]
        try:
            started_at = self._clock()
            graph_facts = export_graph_facts_artifact(
                dexpi_xml_path=dexpi_xml_path,
                fixture_id=session_id,
                output_dir=session_dir,
            )
            graph_facts_json_path = session_dir / session_id / "graph_facts.json"

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
            graph_facts_datalog_path = session_dir / "graph_facts.dl"
            graph_facts_datalog_path.write_text(graph_facts_datalog, encoding="utf-8")

            stage_history.append(stage("running", "deriving graph semantics"))
            derived_graph_semantics = build_derived_graph_semantics_datalog(graph_facts)
            derived_graph_semantics_path = session_dir / "derived_graph_semantics.dl"
            derived_graph_semantics_path.write_text(
                derived_graph_semantics, encoding="utf-8"
            )

            stage_history.append(stage("running", "building topology view model"))
            topology_view = build_topology_view_model(
                graph_facts=graph_facts,
                session_id=session_id,
                source_id=source_id,
            )
            topology_view_path = session_dir / "topology_view.json"
            topology_view_path.write_text(
                json.dumps(topology_view, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            readiness = {
                "state": "ready",
                "session_id": session_id,
                "source_id": source_id,
                "graph": graph_facts["graph"],
                "diagnostics": [],
                "topology_view_model_path": str(topology_view_path),
            }
            readiness_path = session_dir / "readiness.json"
            readiness_path.write_text(
                json.dumps(readiness, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            artifacts = {
                "graph_facts_json": str(graph_facts_json_path),
                "graph_facts_datalog": str(graph_facts_datalog_path),
                "derived_graph_semantics_datalog": str(derived_graph_semantics_path),
                "readiness_metadata": str(readiness_path),
                "topology_view_model": str(topology_view_path),
            }

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
                artifacts=artifacts, limits=self._limits
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
        session_dir = self.artifact_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        readiness = {
            "state": "failed",
            "session_id": session_id,
            "source_id": source_id,
            "diagnostics": diagnostics,
        }
        readiness_path = session_dir / "readiness.json"
        readiness_path.write_text(
            json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8"
        )
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
                message=f"Uploaded DEXPI source file does not exist: {dexpi_xml_path}",
            )
        ]
    if dexpi_xml_path.suffix.lower() != ".xml":
        return [
            diagnostic(
                code="upload.non_xml",
                message="Uploaded P&ID source must be a DEXPI XML file.",
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
    *, artifacts: dict[str, str], limits: PreparationLimits
) -> list[dict[str, object]]:
    for kind, artifact_path in sorted(artifacts.items()):
        path = Path(artifact_path)
        if not path.is_file():
            continue
        artifact_bytes = path.stat().st_size
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
    *, graph_facts: dict[str, object], session_id: str, source_id: str | None = None
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
