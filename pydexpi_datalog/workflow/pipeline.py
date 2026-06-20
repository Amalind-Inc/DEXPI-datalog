from __future__ import annotations

from pathlib import Path


def export_base_facts(
    *, dexpi_xml_path: Path, fixture_id: str, output_dir: Path
) -> dict[str, object]:
    from ..export.pipeline import export_graph_facts_artifact

    return export_graph_facts_artifact(
        dexpi_xml_path=dexpi_xml_path,
        fixture_id=fixture_id,
        output_dir=output_dir,
    )


def build_base_fact_artifact(
    *, dexpi_xml_path: Path, fixture_id: str, pydexpi_full_graph: object
) -> dict[str, object]:
    from ..export.pipeline import build_graph_facts_artifact

    return build_graph_facts_artifact(
        dexpi_xml_path=dexpi_xml_path,
        fixture_id=fixture_id,
        graph=pydexpi_full_graph,
    )


def derive_graph_facts_datalog(graph_facts: dict[str, object]) -> str:
    from ..semantics.derive_graph_semantics import build_graph_facts_datalog

    return build_graph_facts_datalog(graph_facts)


def derive_graph_semantics_datalog(graph_facts: dict[str, object]) -> str:
    from ..semantics.derive_graph_semantics import build_derived_graph_semantics_datalog

    return build_derived_graph_semantics_datalog(graph_facts)


def evaluate_rule(graph_facts: dict[str, object], *, rule_id: str) -> dict[str, object]:
    from ..verification.verify_suite import evaluate_graph_fixture

    return evaluate_graph_fixture(graph_facts, rule_id=rule_id)
