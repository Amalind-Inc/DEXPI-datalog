from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import re

from pydexpi import __file__ as pydexpi_file
from pydexpi.loaders import GraphLoader, ProteusSerializer


def run_export_facts(
    *, dexpi_xml_path: Path, fixture_id: str, output_dir: Path
) -> int:
    artifact = export_graph_facts_artifact(
        dexpi_xml_path=dexpi_xml_path,
        fixture_id=fixture_id,
        output_dir=output_dir,
    )
    print(render_console_report(artifact))
    return 0


def run_export_corpus(*, fixture_root: Path, output_dir: Path) -> int:
    fixture_root_for_summary = fixture_root.as_posix()
    fixture_root = fixture_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    excluded_fixtures: list[dict[str, str]] = []
    fixture_summaries: list[dict[str, object]] = []
    node_attribute_keys: set[str] = set()
    edge_attribute_keys: set[str] = set()
    edge_attr_names: set[str] = set()
    base_fact_collections: set[str] = set()

    for dexpi_xml_path in sorted(fixture_root.glob("**/*.xml")):
        relative_path = dexpi_xml_path.relative_to(fixture_root)
        fixture_id = fixture_id_from_path(relative_path)
        try:
            artifact = export_graph_facts_artifact(
                dexpi_xml_path=dexpi_xml_path,
                fixture_id=fixture_id,
                output_dir=output_dir,
                source_path=(Path(fixture_root_for_summary) / relative_path).as_posix(),
            )
        except Exception as error:  # pyDEXPI raises several parser-specific exceptions.
            fixture_summaries.append(
                {
                    "fixture_id": fixture_id,
                    "relative_path": relative_path.as_posix(),
                    "status": "failed",
                    "error": str(error),
                }
            )
            continue

        graph = artifact["graph"]
        facts = artifact["facts"]
        base_fact_collections.update(facts.keys())
        for node in facts["nodes"]:
            node_attribute_keys.update(node["attributes"].keys())
        for edge in facts["edges"]:
            edge_attribute_keys.update(edge["attributes"].keys())
            attr_name = edge["attributes"].get("attr_name")
            if attr_name is not None:
                edge_attr_names.add(attr_name)
        fixture_summaries.append(
            {
                "fixture_id": fixture_id,
                "relative_path": relative_path.as_posix(),
                "status": "parsed",
                "node_count": graph["node_count"],
                "edge_count": graph["edge_count"],
                "artifact_path": f"{fixture_id}/graph_facts.json",
            }
        )

    summary = build_corpus_summary(
        fixture_root=fixture_root_for_summary,
        fixtures=fixture_summaries,
        excluded_fixtures=excluded_fixtures,
        attribute_coverage={
            "node_attribute_keys": sorted(node_attribute_keys),
            "edge_attribute_keys": sorted(edge_attribute_keys),
            "edge_attr_names": sorted(edge_attr_names),
            "base_fact_collections": sorted(base_fact_collections),
        },
    )
    (output_dir / "corpus_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(render_corpus_report(summary))
    return 0


def export_graph_facts_artifact(
    *, dexpi_xml_path: Path, fixture_id: str, output_dir: Path, source_path: str | None = None
) -> dict[str, object]:
    serializer = ProteusSerializer()
    dexpi_model = serializer.load(dexpi_xml_path.parent, dexpi_xml_path.name)

    graph = GraphLoader().dexpi_to_graph(dexpi_model)
    artifact = build_graph_facts_artifact(
        dexpi_xml_path=dexpi_xml_path,
        fixture_id=fixture_id,
        graph=graph,
        source_path=source_path,
    )
    persist_graph_facts_artifact(output_dir=output_dir, fixture_id=fixture_id, artifact=artifact)
    return artifact


def fixture_id_from_path(relative_path: Path) -> str:
    slug_source = relative_path.with_suffix("").as_posix().replace("/", " ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug_source.lower()).strip("-")
    return slug


def build_graph_facts_artifact(
    *, dexpi_xml_path: Path, fixture_id: str, graph: object, source_path: str | None = None
) -> dict[str, object]:
    nodes = [
        {
            "fact_type": "node",
            "node_id": node_id,
            "attributes": dict(sorted(attributes.items())),
        }
        for node_id, attributes in sorted(graph.nodes(data=True), key=lambda item: item[0])
    ]
    edges = [
        {
            "fact_type": "edge",
            "source_id": source_id,
            "target_id": target_id,
            "edge_key": edge_key,
            "attributes": dict(sorted(attributes.items())),
        }
        for source_id, target_id, edge_key, attributes in sorted(
            graph.edges(keys=True, data=True),
            key=lambda item: (item[0], item[1], str(item[2])),
        )
    ]
    return {
        "fixture_id": fixture_id,
        "source_path": source_path or str(dexpi_xml_path.resolve()),
        "graph": {
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
        "facts": {
            "nodes": nodes,
            "edges": edges,
        },
        "provenance": {
            "extractor": "pyDEXPI",
            "extractor_path": str(Path(pydexpi_file).resolve()),
            "extractor_version": importlib.metadata.version("pyDEXPI"),
        },
    }


def persist_graph_facts_artifact(
    *, output_dir: Path, fixture_id: str, artifact: dict[str, object]
) -> None:
    artifact_dir = output_dir / fixture_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "graph_facts.json"
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")


def render_console_report(artifact: dict[str, object]) -> str:
    graph = artifact["graph"]
    return "\n".join(
        [
            "Exported Graph Facts",
            f"Fixture ID: {artifact['fixture_id']}",
            f"Nodes: {graph['node_count']}",
            f"Edges: {graph['edge_count']}",
        ]
    )


def build_corpus_summary(
    *,
    fixture_root: str,
    fixtures: list[dict[str, object]],
    excluded_fixtures: list[dict[str, str]],
    attribute_coverage: dict[str, list[str]],
) -> dict[str, object]:
    parsed = [fixture for fixture in fixtures if fixture["status"] == "parsed"]
    failed = [fixture for fixture in fixtures if fixture["status"] == "failed"]
    return {
        "fixture_root": fixture_root,
        "totals": {
            "discovered": len(fixtures) + len(excluded_fixtures),
            "parsed": len(parsed),
            "failed": len(failed),
            "excluded": len(excluded_fixtures),
        },
        "attribute_coverage": attribute_coverage,
        "fixtures": fixtures,
        "excluded_fixtures": excluded_fixtures,
    }


def render_corpus_report(summary: dict[str, object]) -> str:
    totals = summary["totals"]
    return "\n".join(
        [
            "Exported DEXPI 1.3 Corpus Facts",
            f"Fixture Root: {summary['fixture_root']}",
            f"Discovered: {totals['discovered']}",
            f"Parsed: {totals['parsed']}",
            f"Failed: {totals['failed']}",
            f"Excluded: {totals['excluded']}",
        ]
    )
