from __future__ import annotations

import json
from pathlib import Path

from pydexpi.loaders import GraphLoader, ProteusSerializer

from ..semantics.derive_graph_semantics import build_derived_graph_semantics_datalog
from ..export.pipeline import build_graph_facts_artifact
from ..artifacts.result_schemas import validate_result_schema
from .verify_suite import evaluate_graph_fixture


def run_verify_raw_fixture(*, dexpi_xml_path: Path, output_dir: Path) -> int:
    serializer = ProteusSerializer()
    dexpi_model = serializer.load(dexpi_xml_path.parent, dexpi_xml_path.name)
    graph = GraphLoader().dexpi_to_graph(dexpi_model)
    graph_facts = build_graph_facts_artifact(
        dexpi_xml_path=dexpi_xml_path,
        fixture_id=dexpi_xml_path.stem,
        graph=graph,
    )
    result = evaluate_graph_fixture(graph_facts, rule_id="pump_discharge_check_valve")
    derived_semantics_filename = f"{dexpi_xml_path.stem}.derived_graph_semantics.dl"
    result["evidence"]["derived_graph_semantics"][
        "artifact"
    ] = derived_semantics_filename
    diagnostics = validate_result_schema(result)
    if diagnostics:
        raise ValueError(f"invalid result schema: {diagnostics}")

    output_dir.mkdir(parents=True, exist_ok=True)
    graph_facts_path = output_dir / f"{dexpi_xml_path.stem}.graph_facts.json"
    result_path = output_dir / f"{dexpi_xml_path.stem}.result.json"
    derived_semantics_path = output_dir / derived_semantics_filename
    graph_facts_path.write_text(json.dumps(graph_facts, indent=2, sort_keys=True), encoding="utf-8")
    derived_semantics_path.write_text(
        build_derived_graph_semantics_datalog(graph_facts), encoding="utf-8"
    )
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(render_console_report(result_path))
    return 0


def render_console_report(result_path: Path) -> str:
    return "\n".join(
        [
            "Verified Raw Fixture",
            f"Result Artifact: {result_path}",
        ]
    )
