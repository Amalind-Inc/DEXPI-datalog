"""Compress a raw DEXPI topology into a P&ID-like view.

A process engineer reads a P&ID as equipment units joined by lines. The raw
topology, however, also contains the document root and the internal piping
chain (nozzle -> piping node -> segment -> piping node -> nozzle) that a drawing
hides or implies. This module distils the topology down to:

- units: equipment, each carrying its nozzles as ports,
- lines: a single labelled connection between two units, collapsing the chain,
- hidden_topology_ids: objects intentionally not drawn (e.g. the document root).

Every unit/line keeps the underlying stable topology ids so the existing
evidence-highlight channel still lights up the right glyph.
"""
from __future__ import annotations

from collections import defaultdict

from .bundled_symbols import BUNDLED_SYMBOLS

_EQUIPMENT_CATEGORIES = frozenset({"equipment", "instrument"})
_COMPOSITION = "composition"


def build_pid_view(
    topology_nodes: list[dict[str, object]],
    fact_edges: list[dict[str, object]],
) -> dict[str, object]:
    node_by_raw = {
        str(n["source_graph_node_id"]): n
        for n in topology_nodes
        if n.get("source_graph_node_id") is not None
    }
    stable_of = {raw: str(node["id"]) for raw, node in node_by_raw.items()}

    nozzle_parent: dict[str, str] = {}        # nozzle_raw -> owner equipment_raw
    nozzle_nodes: dict[str, list[str]] = defaultdict(list)  # nozzle_raw -> piping node raws
    segment_raws: list[str] = []              # segments owned by a piping system
    system_of_segment: dict[str, str] = {}    # segment_raw -> system_raw
    endpoints: dict[str, dict[str, str]] = defaultdict(dict)  # connector_raw -> {source,target}

    for edge in fact_edges:
        attrs = edge.get("attributes", {})
        attr_name = attrs.get("attr_name")
        label = attrs.get("label")
        src = str(edge["source_id"])
        tgt = str(edge["target_id"])
        if label == _COMPOSITION and attr_name == "nozzles":
            nozzle_parent[tgt] = src
        elif label == _COMPOSITION and attr_name == "nodes":
            nozzle_nodes[src].append(tgt)
        elif label == _COMPOSITION and attr_name == "segments":
            segment_raws.append(tgt)
            system_of_segment[tgt] = src
        elif attr_name == "sourceItem":
            endpoints[src]["source"] = tgt
        elif attr_name == "targetItem":
            endpoints[src]["target"] = tgt

    units = _build_units(topology_nodes, node_by_raw, nozzle_parent, stable_of)
    lines = _build_lines(
        segment_raws,
        endpoints,
        nozzle_parent,
        nozzle_nodes,
        system_of_segment,
        node_by_raw,
        stable_of,
    )
    hidden = [
        str(n["id"])
        for n in topology_nodes
        if str(n.get("category")) == "structural"
    ]
    generic_placeholders = [
        {"unit_id": unit["id"], "class_name": unit["raw_class_name"], "reason": "unknown_component_class"}
        for unit in units
        if unit["symbol_key"] == "generic"
    ]
    return {
        "units": units,
        "lines": lines,
        "hidden_topology_ids": hidden,
        "symbol_report": {"generic_placeholders": generic_placeholders},
    }


def _build_units(
    topology_nodes: list[dict[str, object]],
    node_by_raw: dict[str, dict[str, object]],
    nozzle_parent: dict[str, str],
    stable_of: dict[str, str],
) -> list[dict[str, object]]:
    ports_by_owner: dict[str, list[dict[str, str]]] = defaultdict(list)
    for nozzle_raw, owner_raw in nozzle_parent.items():
        nozzle = node_by_raw.get(nozzle_raw)
        if nozzle is None:
            continue
        ports_by_owner[owner_raw].append(
            {"id": str(nozzle["id"]), "label": str(nozzle.get("display_name") or nozzle["id"])}
        )

    units = []
    for node in topology_nodes:
        if str(node.get("category")) not in _EQUIPMENT_CATEGORIES:
            continue
        raw = str(node.get("source_graph_node_id"))
        raw_class_name = str(node.get("label") or "")
        units.append(
            {
                "id": str(node["id"]),
                "label": str(node.get("display_name") or node["id"]),
                "class_name": str(node.get("class_name") or ""),
                "category": str(node.get("category") or ""),
                "description": str(node.get("description") or ""),
                "ports": sorted(ports_by_owner.get(raw, []), key=lambda p: p["label"]),
                "raw_class_name": raw_class_name,
                "symbol_key": raw_class_name if raw_class_name in BUNDLED_SYMBOLS else "generic",
            }
        )
    return units


def _build_lines(
    segment_raws: list[str],
    endpoints: dict[str, dict[str, str]],
    nozzle_parent: dict[str, str],
    nozzle_nodes: dict[str, list[str]],
    system_of_segment: dict[str, str],
    node_by_raw: dict[str, dict[str, object]],
    stable_of: dict[str, str],
) -> list[dict[str, object]]:
    lines = []
    for seg_raw in segment_raws:
        ends = endpoints.get(seg_raw, {})
        src_noz = ends.get("source")
        tgt_noz = ends.get("target")
        if not src_noz or not tgt_noz:
            continue
        source_unit = nozzle_parent.get(src_noz)
        target_unit = nozzle_parent.get(tgt_noz)
        system_raw = system_of_segment.get(seg_raw)
        label = ""
        if system_raw and system_raw in node_by_raw:
            label = str(node_by_raw[system_raw].get("display_name") or "")

        members_raw = {seg_raw, src_noz, tgt_noz}
        members_raw.update(nozzle_nodes.get(src_noz, []))
        members_raw.update(nozzle_nodes.get(tgt_noz, []))
        if system_raw:
            members_raw.add(system_raw)

        lines.append(
            {
                "id": stable_of.get(seg_raw, seg_raw),
                "label": label,
                "source_unit": stable_of.get(source_unit) if source_unit else None,
                "target_unit": stable_of.get(target_unit) if target_unit else None,
                "source_port": stable_of.get(src_noz),
                "target_port": stable_of.get(tgt_noz),
                "member_topology_ids": sorted(
                    stable_of[m] for m in members_raw if m in stable_of
                ),
            }
        )
    return lines
