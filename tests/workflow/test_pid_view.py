"""Behavioral contracts for compressing topology into a P&ID-like view.

A raw DEXPI topology contains objects an engineer never sees on a drawing
(document root, internal piping nodes) and splits a single drawn "line" into a
chain of nozzle -> node -> segment -> node -> nozzle. The P&ID view compresses
this to what a process engineer reads: equipment units (with their nozzles as
ports) joined by single labelled lines.
"""
from __future__ import annotations

from pydexpi_datalog.workflow.pid_view import build_pid_view


def _node(stable_id, raw_id, category, display_name, class_name="", description=""):
    return {
        "id": stable_id,
        "source_graph_node_id": raw_id,
        "category": category,
        "display_name": display_name,
        "class_name": class_name,
        "description": description,
    }


def _edge(source_raw, target_raw, attr_name, label):
    return {
        "source_id": source_raw,
        "target_id": target_raw,
        "attributes": {"attr_name": attr_name, "label": label},
    }


# Mirror of E06: pump P-4713 (nozzle N-1) --line 47132--> exchanger H-1009 (nozzle N-2),
# routed through internal piping nodes and a network segment, all under a doc root.
TOPOLOGY_NODES = [
    _node("s_pump", "pump", "equipment", "P-4713", "Centrifugal Pump", "A pump."),
    _node("s_hx", "hx", "equipment", "H-1009", "Plate Heat Exchanger"),
    _node("s_nz1", "nz1", "nozzle", "P-4713 / N-1"),
    _node("s_nz2", "nz2", "nozzle", "H-1009 / N-2"),
    _node("s_pn1", "pn1", "connection", "P-4713 / N-1 (connection)"),
    _node("s_pn2", "pn2", "connection", "H-1009 / N-2 (connection)"),
    _node("s_seg", "seg", "piping", "Line 47132 (segment)"),
    _node("s_sys", "sys", "line", "Line 47132"),
    _node("s_root", "root", "structural", "Conceptual Model"),
]
FACT_EDGES = [
    _edge("root", "pump", "taggedPlantItems", "composition"),
    _edge("root", "hx", "taggedPlantItems", "composition"),
    _edge("root", "sys", "pipingNetworkSystems", "composition"),
    _edge("pump", "nz1", "nozzles", "composition"),
    _edge("hx", "nz2", "nozzles", "composition"),
    _edge("nz1", "pn1", "nodes", "composition"),
    _edge("nz2", "pn2", "nodes", "composition"),
    _edge("sys", "seg", "segments", "composition"),
    _edge("seg", "nz1", "sourceItem", "reference"),
    _edge("seg", "nz2", "targetItem", "reference"),
]


def test_units_are_the_equipment_with_nozzles_as_ports():
    view = build_pid_view(TOPOLOGY_NODES, FACT_EDGES)
    units = {u["id"]: u for u in view["units"]}
    assert set(units) == {"s_pump", "s_hx"}
    assert units["s_pump"]["label"] == "P-4713"
    # The pump's nozzle is a port on the pump, not a separate unit.
    port_ids = {p["id"] for p in units["s_pump"]["ports"]}
    assert port_ids == {"s_nz1"}
    assert units["s_pump"]["ports"][0]["label"] == "P-4713 / N-1"


def test_document_root_and_internal_plumbing_are_not_units():
    view = build_pid_view(TOPOLOGY_NODES, FACT_EDGES)
    unit_ids = {u["id"] for u in view["units"]}
    # Conceptual root, piping nodes, segment, system are never drawn as units.
    assert unit_ids.isdisjoint({"s_root", "s_pn1", "s_pn2", "s_seg", "s_sys"})


def test_chain_collapses_to_one_line_between_equipment():
    view = build_pid_view(TOPOLOGY_NODES, FACT_EDGES)
    assert len(view["lines"]) == 1
    line = view["lines"][0]
    assert {line["source_unit"], line["target_unit"]} == {"s_pump", "s_hx"}
    assert line["label"] == "Line 47132"
    assert {line["source_port"], line["target_port"]} == {"s_nz1", "s_nz2"}


def test_line_carries_underlying_topology_ids_for_highlighting():
    view = build_pid_view(TOPOLOGY_NODES, FACT_EDGES)
    members = set(view["lines"][0]["member_topology_ids"])
    # Citing any part of the witness (segment, nozzles, internal nodes, system)
    # must be attributable to this single drawn line.
    assert {"s_seg", "s_nz1", "s_nz2", "s_pn1", "s_pn2", "s_sys"} <= members


def test_hidden_ids_include_the_document_root():
    view = build_pid_view(TOPOLOGY_NODES, FACT_EDGES)
    assert "s_root" in view["hidden_topology_ids"]
