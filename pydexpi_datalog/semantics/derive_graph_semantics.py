from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_TOPOLOGY_IDB_PATH = (
    Path(__file__).resolve().parent / "datalog" / "idb" / "graph_topology_semantics.dl"
)

TOPOLOGY_ATTR_NAMES = {
    "connections",
    "connectorReference",
    "nodes",
    "pipingNetworkSystems",
    "segments",
    "source",
    "sourceItem",
    "sourceNode",
    "target",
    "targetItem",
    "targetNode",
}


def run_derive_graph_semantics(*, graph_facts_path: Path, output_dir: Path) -> int:
    artifact = json.loads(graph_facts_path.read_text(encoding="utf-8"))
    fixture_id = artifact["fixture_id"]
    output_fixture_dir = output_dir / fixture_id
    output_fixture_dir.mkdir(parents=True, exist_ok=True)

    graph_facts_datalog = build_graph_facts_datalog(artifact)
    (output_fixture_dir / "graph_facts.dl").write_text(
        graph_facts_datalog, encoding="utf-8"
    )

    datalog = build_derived_graph_semantics_datalog(artifact)
    (output_fixture_dir / "derived_graph_semantics.dl").write_text(
        datalog, encoding="utf-8"
    )
    print(render_console_report(fixture_id))
    return 0


def build_derived_graph_semantics_datalog(artifact: dict[str, object]) -> str:
    return build_graph_facts_datalog(artifact) + "\n" + load_graph_topology_idb()


def build_graph_facts_datalog(artifact: dict[str, object]) -> str:
    nodes = derive_nodes(artifact)

    lines = [
        ".decl node(id:symbol)",
        ".decl node_attribute(id:symbol, attr_name:symbol, attr_value:symbol)",
        ".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)",
        ".decl graph_edge_attribute(source:symbol, target:symbol, edge_key:symbol, attr_name:symbol, attr_value:symbol)",
        "",
    ]
    lines.extend(render_node_facts(nodes))
    lines.extend(render_node_attribute_facts(artifact))
    lines.extend(render_graph_edge_facts(artifact))
    lines.extend(render_graph_edge_attribute_facts(artifact))
    return "\n".join(lines) + "\n"


def load_graph_topology_idb() -> str:
    return GRAPH_TOPOLOGY_IDB_PATH.read_text(encoding="utf-8")


def derive_nodes(artifact: dict[str, object]) -> list[str]:
    return [node["node_id"] for node in artifact["facts"]["nodes"]]


def derive_node_labels(artifact: dict[str, object]) -> list[tuple[str, str]]:
    node_labels: list[tuple[str, str]] = []
    for node in artifact["facts"]["nodes"]:
        label = node["attributes"].get("label")
        if label is not None:
            node_labels.append((node["node_id"], label))
    return node_labels


def derive_node_attribute_aliases(
    artifact: dict[str, object], attribute_name: str
) -> list[tuple[str, str]]:
    aliases: list[tuple[str, str]] = []
    for node in artifact["facts"]["nodes"]:
        value = node["attributes"].get(attribute_name)
        if value is not None:
            aliases.append((node["node_id"], value))
    return aliases


def derive_edge_families(
    artifact: dict[str, object]
) -> dict[str, list[tuple[str, str, str]]]:
    composition_edges: list[tuple[str, str, str]] = []
    reference_edges: list[tuple[str, str, str]] = []
    candidate_topology_edges: list[tuple[str, str, str]] = []

    for edge in artifact["facts"]["edges"]:
        attributes = edge["attributes"]
        attr_name = attributes.get("attr_name")
        if attr_name is None:
            continue

        classified_edge = (edge["source_id"], edge["target_id"], attr_name)
        if attributes.get("label") == "composition":
            composition_edges.append(classified_edge)
        if attributes.get("label") == "reference":
            reference_edges.append(classified_edge)
        if attr_name in TOPOLOGY_ATTR_NAMES:
            candidate_topology_edges.append(classified_edge)

    return {
        "composition_edge": composition_edges,
        "reference_edge": reference_edges,
        "candidate_topology_edge": candidate_topology_edges,
    }


def render_node_facts(nodes: list[str]) -> list[str]:
    return [f"node({souffle_symbol(node_id)})." for node_id in sorted(nodes)]


def render_node_label_facts(node_labels: list[tuple[str, str]]) -> list[str]:
    return [
        f'node_label("{node_id}", "{label}").'
        for node_id, label in sorted(node_labels)
    ]


def render_node_attribute_facts(artifact: dict[str, object]) -> list[str]:
    facts: list[str] = []
    for node in artifact["facts"]["nodes"]:
        node_id = node["node_id"]
        for attr_name, attr_value in sorted(node["attributes"].items()):
            facts.append(
                f"node_attribute({souffle_symbol(node_id)}, {souffle_symbol(str(attr_name))}, {souffle_symbol(str(attr_value))})."
            )
    return facts


def render_graph_edge_facts(artifact: dict[str, object]) -> list[str]:
    return [
        f"graph_edge({souffle_symbol(edge['source_id'])}, {souffle_symbol(edge['target_id'])}, {souffle_symbol(str(edge['edge_key']))})."
        for edge in sorted(
            artifact["facts"]["edges"],
            key=lambda item: (item["source_id"], item["target_id"], str(item["edge_key"])),
        )
    ]


def render_graph_edge_attribute_facts(artifact: dict[str, object]) -> list[str]:
    facts: list[str] = []
    for edge in sorted(
        artifact["facts"]["edges"],
        key=lambda item: (item["source_id"], item["target_id"], str(item["edge_key"])),
    ):
        for attr_name, attr_value in sorted(edge["attributes"].items()):
            facts.append(
                f"graph_edge_attribute({souffle_symbol(edge['source_id'])}, {souffle_symbol(edge['target_id'])}, {souffle_symbol(str(edge['edge_key']))}, {souffle_symbol(str(attr_name))}, {souffle_symbol(str(attr_value))})."
            )
    return facts


def render_node_alias_facts(predicate: str, aliases: list[tuple[str, str]]) -> list[str]:
    return [f'{predicate}("{node_id}", "{value}").' for node_id, value in sorted(aliases)]


def render_edge_facts(
    predicate: str, edges: list[tuple[str, str, str]]
) -> list[str]:
    return [
        f'{predicate}("{source_id}", "{target_id}", "{attr_name}").'
        for source_id, target_id, attr_name in sorted(edges)
    ]


def souffle_symbol(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def render_console_report(fixture_id: str) -> str:
    return "\n".join(
        [
            "Derived Graph Semantics",
            f"Fixture ID: {fixture_id}",
            "Status: ok",
        ]
    )
