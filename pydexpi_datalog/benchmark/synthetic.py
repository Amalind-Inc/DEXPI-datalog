"""Synthetic truth-by-construction slice (bead pydexpi-datalog-1-3q1.11).

Generates drawings across a declared graph-size sweep with injected
violations, so degradation with scale is measured rather than assumed.
Ground truth is emitted directly from the construction record - the
generator accumulates the pump IDs it injects violations onto while
building each drawing - never hand-labeled afterwards.

Each drawing ships as a bundle-layout directory consumable by every arm and
matching the 3q1.4 drawing-bundle convention (``drawing.xml``,
``graph_facts.json``, ``graph.json``, ``README.md``).  Full DEXPI-valid XML
synthesis is deliberately not attempted: ``drawing.xml`` uses the documented
XML-wrapper fallback (:data:`SYNTHETIC_FIDELITY_LIMIT`), and the canonical
base fact layer is the authoritative representation, exactly as for real
exports.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from pydexpi_datalog.benchmark.dataset import (
    CATEGORY_COMPLIANCE_UNIVERSAL,
    DATASET_SCHEMA_VERSION,
    SLICE_SYNTHETIC,
)
from pydexpi_datalog.export.pipeline import (
    persist_graph_facts_artifact,
    write_bundle_derivatives,
)

SIZE_BUCKETS = ("small", "medium", "large")

# The declared size sweep: pump trains per drawing and the base discharge
# pipe-run length, both growing with the bucket.  Drawing 4 of every bucket
# additionally deepens its pipe runs (_DEEP_RUN_EXTRA) so each bucket also
# carries its longest walks.
_BUCKET_TRAINS = {"small": 1, "medium": 3, "large": 8}
_BUCKET_BASE_RUN = {"small": 1, "medium": 3, "large": 6}
_DRAWINGS_PER_BUCKET = 5
_DEEP_RUN_EXTRA = 4

SYNTHETIC_MANIFEST_FILENAME = "synthetic_manifest.json"
SYNTHETIC_FIDELITY_MODE = "xml_graph_wrapper"
SYNTHETIC_FIDELITY_LIMIT = (
    "Synthetic drawings use the XML-wrapper fallback: drawing.xml is a "
    "minimal SyntheticGraphDrawing serialization of the constructed "
    "graph-level truth, not a full DEXPI/Proteus export, so XML fidelity is "
    "limited to the node/edge structure the wrapper mirrors one-to-one from "
    "graph_facts.json (the authoritative canonical base fact layer). "
    "Results on this slice measure reasoning over the graph model, not "
    "DEXPI XML parsing fidelity."
)

_DIAMETER_ATTR = "nominalDiameterNumericalValueRepresentation"
_COMPLIANT_DN = "80"
_VIOLATING_DN = "15"


@dataclass(frozen=True)
class _TrainPlan:
    """One pump train's construction plan inside a drawing."""

    index: int
    check_valve_violation: bool
    diameter_violation: bool
    run_length: int


def generate_synthetic_slice(*, output_dir: Path) -> dict[str, object]:
    """Generate the synthetic slice: drawing bundles plus question manifest.

    Deterministic by construction (no randomness), so repeated runs produce
    byte-identical artifacts.  Returns a generation summary the caller can
    report from.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    questions: list[dict[str, object]] = []
    drawings: list[dict[str, object]] = []
    size_sweep: dict[str, dict[str, object]] = {}

    for bucket in SIZE_BUCKETS:
        bucket_node_counts: list[int] = []
        for drawing_index in range(_DRAWINGS_PER_BUCKET):
            record = _generate_drawing(
                output_dir=output_dir,
                bucket=bucket,
                drawing_index=drawing_index,
            )
            drawings.append(record)
            bucket_node_counts.append(int(record["node_count"]))
            questions.extend(_questions_from_construction(record))
        size_sweep[bucket] = {
            "drawings": _DRAWINGS_PER_BUCKET,
            "trains_per_drawing": _BUCKET_TRAINS[bucket],
            "base_run_length": _BUCKET_BASE_RUN[bucket],
            "node_counts": bucket_node_counts,
        }

    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "slice": SLICE_SYNTHETIC,
        "fidelity": {
            "mode": SYNTHETIC_FIDELITY_MODE,
            "limit": SYNTHETIC_FIDELITY_LIMIT,
        },
        "size_sweep": size_sweep,
        "questions": questions,
    }
    manifest_path = output_dir / SYNTHETIC_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    return {
        "manifest_path": manifest_path,
        "questions": len(questions),
        "drawings": drawings,
        "size_sweep": size_sweep,
        "fidelity": manifest["fidelity"],
    }


def run_generate_synthetic_slice(*, output_dir: Path) -> int:
    """CLI entry: generate the slice and print a short report."""
    summary = generate_synthetic_slice(output_dir=output_dir)
    print(render_console_report(summary))
    return 0


def render_console_report(summary: dict[str, object]) -> str:
    lines = [
        "Generated Synthetic Slice",
        f"Manifest: {summary['manifest_path']}",
        f"Questions: {summary['questions']}",
        f"Drawings: {len(summary['drawings'])}",
    ]
    for bucket in SIZE_BUCKETS:
        sweep = summary["size_sweep"][bucket]
        lines.append(
            f"  {bucket}: {sweep['drawings']} drawings x "
            f"{sweep['trains_per_drawing']} trains, "
            f"nodes {min(sweep['node_counts'])}-{max(sweep['node_counts'])}"
        )
    lines.append(f"Fidelity mode: {summary['fidelity']['mode']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Drawing construction: the record IS the ground truth
# --------------------------------------------------------------------------


def _train_plans(bucket: str, drawing_index: int) -> tuple[_TrainPlan, ...]:
    """The deterministic violation layout for one drawing.

    Per bucket the five drawings cycle: fully compliant, one check-valve
    violation, one diameter violation, one of each on different trains, and
    a compliant drawing with deepened pipe runs (longest walks).
    """
    trains = _BUCKET_TRAINS[bucket]
    run_length = _BUCKET_BASE_RUN[bucket]
    if drawing_index == 4:
        run_length += _DEEP_RUN_EXTRA

    check_valve_trains: set[int] = set()
    diameter_trains: set[int] = set()
    if drawing_index == 1:
        check_valve_trains = {0}
    elif drawing_index == 2:
        diameter_trains = {min(1, trains - 1)}
    elif drawing_index == 3:
        check_valve_trains = {trains - 1}
        diameter_trains = {0}

    return tuple(
        _TrainPlan(
            index=train_index,
            check_valve_violation=train_index in check_valve_trains,
            diameter_violation=train_index in diameter_trains,
            run_length=run_length,
        )
        for train_index in range(trains)
    )


def _generate_drawing(
    *, output_dir: Path, bucket: str, drawing_index: int
) -> dict[str, object]:
    fixture_id = f"syn-{bucket}-{drawing_index:02d}"
    plans = _train_plans(bucket, drawing_index)

    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    check_valve_violators: list[str] = []
    diameter_violators: list[str] = []

    for plan in plans:
        pump_id = _build_train(
            fixture_id=fixture_id, plan=plan, nodes=nodes, edges=edges
        )
        # The construction record is the ground truth: a pump is a witness
        # exactly because the generator injected the violation onto it.
        if plan.check_valve_violation:
            check_valve_violators.append(pump_id)
        if plan.diameter_violation:
            diameter_violators.append(pump_id)

    artifact = _build_artifact(fixture_id=fixture_id, nodes=nodes, edges=edges)
    bundle_dir = output_dir / fixture_id
    persist_graph_facts_artifact(
        output_dir=output_dir, fixture_id=fixture_id, artifact=artifact
    )
    (bundle_dir / "drawing.xml").write_text(
        _render_wrapper_xml(fixture_id=fixture_id, artifact=artifact),
        encoding="utf-8",
    )
    write_bundle_derivatives(
        bundle_dir=bundle_dir,
        artifact=artifact,
        source_reference="synthetic truth-by-construction (XML-wrapper fallback)",
        drawing_description=(
            "a minimal SyntheticGraphDrawing XML wrapper serializing the "
            "constructed graph-level truth (not a DEXPI/Proteus export; see "
            "Fidelity limit)."
        ),
        graph_facts_description=(
            "the authoritative canonical base fact layer this drawing was "
            "constructed from; `drawing.xml` mirrors it one-to-one."
        ),
        readme_extra=f"\n## Fidelity limit\n\n{SYNTHETIC_FIDELITY_LIMIT}\n",
    )

    return {
        "fixture_id": fixture_id,
        "size_bucket": bucket,
        "trains": len(plans),
        "node_count": artifact["graph"]["node_count"],
        "edge_count": artifact["graph"]["edge_count"],
        "check_valve_violators": tuple(check_valve_violators),
        "diameter_violators": tuple(diameter_violators),
    }


def _build_train(
    *,
    fixture_id: str,
    plan: _TrainPlan,
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> str:
    """Build one pump train; returns the pump node ID."""
    prefix = f"{fixture_id}-t{plan.index}"
    pump_id = f"{prefix}-pump"
    suction_nozzle_id = f"{prefix}-nozzle-suction"
    discharge_nozzle_id = f"{prefix}-nozzle-discharge"
    feed_tank_id = f"{prefix}-feed-tank"
    system_id = f"{prefix}-system"

    nodes.append(
        _node(
            pump_id,
            "CentrifugalPump",
            tagName=f"P-{plan.index + 101}",
            tagNamePrefix="P",
        )
    )
    nodes.append(_node(suction_nozzle_id, "Nozzle", subTagName="N-1"))
    nodes.append(_node(discharge_nozzle_id, "Nozzle", subTagName="N-2"))
    nodes.append(_node(feed_tank_id, "Tank", tagName=f"T-{plan.index + 101}"))
    nodes.append(_node(system_id, "PipingNetworkSystem"))
    edges.append(_edge(pump_id, suction_nozzle_id, "composition", "nozzles"))
    edges.append(_edge(pump_id, discharge_nozzle_id, "composition", "nozzles"))

    # Discharge chain: nozzle -> pipe x run_length -> boundary object.  The
    # boundary is a check valve unless this train carries the injected
    # check-valve violation, in which case the walk terminates at a tank.
    pipe_ids = [f"{prefix}-pipe-{i}" for i in range(plan.run_length)]
    for pipe_id in pipe_ids:
        nodes.append(_node(pipe_id, "Pipe"))
    if plan.check_valve_violation:
        boundary_id = f"{prefix}-outlet-tank"
        nodes.append(_node(boundary_id, "Tank", tagName=f"T-{plan.index + 201}"))
    else:
        boundary_id = f"{prefix}-check-valve"
        nodes.append(_node(boundary_id, "CheckValve", tagName=f"V-{plan.index + 101}"))

    hops = [discharge_nozzle_id, *pipe_ids, boundary_id]
    for hop_index in range(len(hops) - 1):
        segment_id = f"{prefix}-segment-{hop_index}"
        attributes: dict[str, object] = {}
        if hop_index == 0:
            # The discharge segment declares the line's nominal diameter;
            # the injected diameter violation is a DN below the rule's 25.
            attributes[_DIAMETER_ATTR] = (
                _VIOLATING_DN if plan.diameter_violation else _COMPLIANT_DN
            )
        nodes.append(_node(segment_id, "PipingNetworkSegment", **attributes))
        edges.append(_edge(segment_id, hops[hop_index], "reference", "sourceItem"))
        edges.append(_edge(segment_id, hops[hop_index + 1], "reference", "targetItem"))
        edges.append(_edge(system_id, segment_id, "composition", "segments"))

    suction_segment_id = f"{prefix}-segment-suction"
    nodes.append(_node(suction_segment_id, "PipingNetworkSegment"))
    edges.append(_edge(suction_segment_id, feed_tank_id, "reference", "sourceItem"))
    edges.append(
        _edge(suction_segment_id, suction_nozzle_id, "reference", "targetItem")
    )
    edges.append(_edge(system_id, suction_segment_id, "composition", "segments"))
    return pump_id


def _questions_from_construction(record: dict[str, object]) -> list[dict[str, object]]:
    """Emit manifest entries directly from one drawing's construction record."""
    fixture_id = record["fixture_id"]
    entries: list[dict[str, object]] = []
    for suffix, question_text, witnesses in (
        (
            "check-valve",
            "Is any pump on this drawing missing a check valve on its "
            "discharge line?",
            record["check_valve_violators"],
        ),
        (
            "diameter",
            "Does any pump discharge line on this drawing declare a nominal "
            "diameter below DN 25?",
            record["diameter_violators"],
        ),
    ):
        entries.append(
            {
                "id": f"{fixture_id}-{suffix}",
                "question": question_text,
                "slice": SLICE_SYNTHETIC,
                "drawing": str(fixture_id),
                "size_bucket": record["size_bucket"],
                "category": CATEGORY_COMPLIANCE_UNIVERSAL,
                "ground_truth": {
                    "verdict": "violation_found" if witnesses else "no_violation",
                    "witness_ids": sorted(witnesses),
                },
            }
        )
    return entries


# --------------------------------------------------------------------------
# Artifact and XML-wrapper rendering
# --------------------------------------------------------------------------


def _node(node_id: str, label: str, **attributes: object) -> dict[str, object]:
    return {
        "fact_type": "node",
        "node_id": node_id,
        "attributes": dict(sorted({"label": label, **attributes}.items())),
    }


def _edge(
    source_id: str, target_id: str, label: str, attr_name: str
) -> dict[str, object]:
    return {
        "fact_type": "edge",
        "source_id": source_id,
        "target_id": target_id,
        "edge_key": 0,
        "attributes": {"attr_name": attr_name, "label": label},
    }


def _build_artifact(
    *,
    fixture_id: str,
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> dict[str, object]:
    sorted_nodes = sorted(nodes, key=lambda node: node["node_id"])
    sorted_edges = sorted(
        edges,
        key=lambda edge: (edge["source_id"], edge["target_id"], str(edge["edge_key"])),
    )
    return {
        "fixture_id": fixture_id,
        "source_path": "drawing.xml",
        "graph": {
            "node_count": len(sorted_nodes),
            "edge_count": len(sorted_edges),
        },
        "facts": {
            "nodes": sorted_nodes,
            "edges": sorted_edges,
        },
        "provenance": {
            "extractor": "synthetic-truth-by-construction",
            "extractor_version": "1",
            "fidelity_mode": SYNTHETIC_FIDELITY_MODE,
            "fidelity_limit": SYNTHETIC_FIDELITY_LIMIT,
        },
    }


def _render_wrapper_xml(*, fixture_id: str, artifact: dict[str, object]) -> str:
    """The minimal XML wrapper around the constructed graph-level truth."""
    root = ET.Element(
        "SyntheticGraphDrawing",
        attrib={
            "fixtureId": fixture_id,
            "schemaVersion": "1",
            "fidelityMode": SYNTHETIC_FIDELITY_MODE,
        },
    )
    fidelity = ET.SubElement(root, "FidelityLimit")
    fidelity.text = SYNTHETIC_FIDELITY_LIMIT
    nodes_element = ET.SubElement(root, "Nodes")
    for node in artifact["facts"]["nodes"]:
        ET.SubElement(
            nodes_element,
            "Node",
            attrib={
                "id": node["node_id"],
                **{key: str(value) for key, value in node["attributes"].items()},
            },
        )
    edges_element = ET.SubElement(root, "Edges")
    for edge in artifact["facts"]["edges"]:
        ET.SubElement(
            edges_element,
            "Edge",
            attrib={
                "sourceId": edge["source_id"],
                "targetId": edge["target_id"],
                "edgeKey": str(edge["edge_key"]),
                **{
                    key: str(value)
                    for key, value in edge["attributes"].items()
                },
            },
        )
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"
