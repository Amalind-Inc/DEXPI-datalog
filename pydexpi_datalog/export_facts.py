from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

from pydexpi import __file__ as pydexpi_file
from pydexpi.loaders import GraphLoader, ProteusSerializer


def run_export_facts(
    *, dexpi_xml_path: Path, fixture_id: str, output_dir: Path
) -> int:
    serializer = ProteusSerializer()
    dexpi_model = serializer.load(dexpi_xml_path.parent, dexpi_xml_path.name)

    graph = GraphLoader().dexpi_to_graph(dexpi_model)
    artifact = build_graph_facts_artifact(
        dexpi_xml_path=dexpi_xml_path,
        fixture_id=fixture_id,
        graph=graph,
    )
    persist_graph_facts_artifact(output_dir=output_dir, fixture_id=fixture_id, artifact=artifact)
    print(render_console_report(artifact))
    return 0


def build_graph_facts_artifact(
    *, dexpi_xml_path: Path, fixture_id: str, graph: object
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
        "source_path": str(dexpi_xml_path.resolve()),
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
