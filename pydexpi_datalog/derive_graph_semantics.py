from __future__ import annotations

import json
from pathlib import Path


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

    datalog = build_derived_graph_semantics_datalog(artifact)
    (output_fixture_dir / "derived_graph_semantics.dl").write_text(
        datalog, encoding="utf-8"
    )
    print(render_console_report(fixture_id))
    return 0


def build_derived_graph_semantics_datalog(artifact: dict[str, object]) -> str:
    nodes = derive_nodes(artifact)
    node_labels = derive_node_labels(artifact)
    node_tags = derive_node_attribute_aliases(artifact, "tagName")
    node_proteus_ids = derive_node_attribute_aliases(artifact, "proteusId")
    edge_families = derive_edge_families(artifact)
    composition_edges = edge_families["composition_edge"]
    reference_edges = edge_families["reference_edge"]
    candidate_topology_edges = edge_families["candidate_topology_edge"]

    lines = [
        ".decl node(id:symbol)",
        ".decl node_label(id:symbol, label:symbol)",
        ".decl node_tag(id:symbol, tag:symbol)",
        ".decl node_proteus_id(id:symbol, proteus_id:symbol)",
        ".decl composition_edge(source:symbol, target:symbol, attr_name:symbol)",
        ".decl reference_edge(source:symbol, target:symbol, attr_name:symbol)",
        ".decl candidate_topology_edge(source:symbol, target:symbol, attr_name:symbol)",
        ".decl downstream_candidate(source:symbol, target:symbol)",
        ".decl downstream_composition(source:symbol, target:symbol)",
        ".decl downstream_reference(source:symbol, target:symbol)",
        ".decl reachable(source:symbol, target:symbol)",
        "",
    ]
    lines.extend(render_node_facts(nodes))
    lines.extend(render_node_label_facts(node_labels))
    lines.extend(render_node_alias_facts("node_tag", node_tags))
    lines.extend(render_node_alias_facts("node_proteus_id", node_proteus_ids))
    lines.extend(render_edge_facts("composition_edge", composition_edges))
    lines.extend(render_edge_facts("reference_edge", reference_edges))
    lines.extend(render_edge_facts("candidate_topology_edge", candidate_topology_edges))
    lines.extend(
        [
            "",
            "downstream_candidate(source, target) :- candidate_topology_edge(source, target, _).",
            "downstream_composition(source, target) :- composition_edge(source, target, _).",
            "downstream_reference(source, target) :- reference_edge(source, target, _).",
            "reachable(source, target) :- candidate_topology_edge(source, target, _).",
            "reachable(source, target) :- candidate_topology_edge(source, intermediate, _), reachable(intermediate, target).",
        ]
    )
    return "\n".join(lines) + "\n"


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
    return [f'node("{node_id}").' for node_id in sorted(nodes)]


def render_node_label_facts(node_labels: list[tuple[str, str]]) -> list[str]:
    return [
        f'node_label("{node_id}", "{label}").'
        for node_id, label in sorted(node_labels)
    ]


def render_node_alias_facts(predicate: str, aliases: list[tuple[str, str]]) -> list[str]:
    return [f'{predicate}("{node_id}", "{value}").' for node_id, value in sorted(aliases)]


def render_edge_facts(
    predicate: str, edges: list[tuple[str, str, str]]
) -> list[str]:
    return [
        f'{predicate}("{source_id}", "{target_id}", "{attr_name}").'
        for source_id, target_id, attr_name in sorted(edges)
    ]


def render_console_report(fixture_id: str) -> str:
    return "\n".join(
        [
            "Derived Graph Semantics",
            f"Fixture ID: {fixture_id}",
            "Status: ok",
        ]
    )
