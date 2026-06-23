from __future__ import annotations

import json
from pathlib import Path
import hashlib
import uuid
import xml.etree.ElementTree as ET

from ..export.pipeline import export_graph_facts_artifact
from ..semantics.derive_graph_semantics import (
    TOPOLOGY_ATTR_NAMES,
    build_derived_graph_semantics_datalog,
    build_graph_facts_datalog,
)


class ReviewSessionService:
    """Prepare one uploaded DEXPI source file for the web review workflow."""

    def __init__(self, *, artifact_root: Path) -> None:
        self.artifact_root = artifact_root
        self._requests_by_session: dict[str, Path] = {}

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
        validation_diagnostics = validate_upload_input(dexpi_xml_path)
        if validation_diagnostics:
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
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
            graph_facts = export_graph_facts_artifact(
                dexpi_xml_path=dexpi_xml_path,
                fixture_id=session_id,
                output_dir=session_dir,
            )
            graph_facts_json_path = session_dir / session_id / "graph_facts.json"

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
            )
            topology_view_path = session_dir / "topology_view.json"
            topology_view_path.write_text(
                json.dumps(topology_view, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            readiness = {
                "state": "ready",
                "session_id": session_id,
                "graph": graph_facts["graph"],
                "diagnostics": [],
                "topology_view_model_path": str(topology_view_path),
            }
            readiness_path = session_dir / "readiness.json"
            readiness_path.write_text(
                json.dumps(readiness, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            stage_history.append(stage("succeeded", "ready"))

            return {
                "session_id": session_id,
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
                "artifacts": {
                    "graph_facts_json": str(graph_facts_json_path),
                    "graph_facts_datalog": str(graph_facts_datalog_path),
                    "derived_graph_semantics_datalog": str(derived_graph_semantics_path),
                    "readiness_metadata": str(readiness_path),
                    "topology_view_model": str(topology_view_path),
                },
                "diagnostics": [],
            }
        except Exception as error:  # pyDEXPI has parser and conversion exceptions.
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
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
    ) -> dict[str, object]:
        session_dir = self.artifact_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        readiness = {
            "state": "failed",
            "session_id": session_id,
            "diagnostics": diagnostics,
        }
        readiness_path = session_dir / "readiness.json"
        readiness_path.write_text(
            json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8"
        )
        return {
            "session_id": session_id,
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


def validate_upload_input(dexpi_xml_path: Path) -> list[dict[str, object]]:
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

    return []


def build_topology_view_model(
    *, graph_facts: dict[str, object], session_id: str
) -> dict[str, object]:
    fact_nodes = graph_facts["facts"]["nodes"]
    fact_edges = graph_facts["facts"]["edges"]

    node_ids_by_raw_id = build_stable_node_id_map(fact_nodes)
    nodes = []
    evidence_map: dict[str, dict[str, object]] = {}
    for node in sorted(
        fact_nodes, key=lambda item: node_ids_by_raw_id[item["node_id"]]
    ):
        stable_node_id = node_ids_by_raw_id[node["node_id"]]
        nodes.append(
            {
                "id": stable_node_id,
                "label": node["attributes"].get("label", stable_node_id),
                "tag_name": node["attributes"].get("tagName"),
                "proteus_id": node["attributes"].get("proteusId"),
                "canonical_fact_id": stable_node_id,
                "source_graph_node_id": node["node_id"],
            }
        )
        evidence_map[stable_node_id] = {
            "kind": "node",
            "topology_id": stable_node_id,
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
        "source_path": graph_facts["source_path"],
        "nodes": nodes,
        "edges": topology_edges,
        "evidence_map": evidence_map,
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
