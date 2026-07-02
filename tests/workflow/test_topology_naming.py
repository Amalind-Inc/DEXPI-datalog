"""Behavioral contracts for engineer-facing topology naming (Phase 2).

The DEXPI graph identifies most objects only by internal class ("PipingNode") or
opaque ids. Process engineers reference equipment tags (P-4713), nozzle sub-tags
qualified by their equipment (P-4713 / N-1), and line numbers (Line 47132). These
tests pin those derivations from the raw graph facts.
"""
from __future__ import annotations

from pydexpi_datalog.workflow.topology_naming import derive_display_names


def _node(node_id: str, **attributes):
    return {"node_id": node_id, "attributes": attributes}


def _edge(source: str, target: str, attr_name: str, label: str):
    return {
        "source_id": source,
        "target_id": target,
        "attributes": {"attr_name": attr_name, "label": label},
    }


# A miniature of the E06 structure:
#   pump (P-4713) --nozzles--> nozzle (N-1) --nodes--> piping connection node
#   plate exchanger (H-1009) --nozzles--> nozzle (N-1)   (same sub-tag, diff parent)
#   piping system carries the line number 47132
FACT_NODES = [
    _node("pump", label="CentrifugalPump", tagName="P-4713", label_description="A pump."),
    _node("hx", label="PlateHeatExchanger", tagName="H-1009"),
    _node("noz_pump", label="Nozzle", subTagName="N-1"),
    _node("noz_hx", label="Nozzle", subTagName="N-1"),
    _node("pnode", label="PipingNode", proteusId="PipingNode-1"),
    _node("system", label="PipingNetworkSystem", lineNumber="47132", fluidCode="MNb"),
    _node("segment", label="PipingNetworkSegment"),
    _node("root", label="ConceptualModel"),
]
FACT_EDGES = [
    _edge("pump", "noz_pump", "nozzles", "composition"),
    _edge("hx", "noz_hx", "nozzles", "composition"),
    _edge("noz_pump", "pnode", "nodes", "composition"),
    _edge("system", "segment", "segments", "composition"),
]


def test_equipment_is_named_by_its_tag():
    names = derive_display_names(FACT_NODES, FACT_EDGES)
    assert names["pump"]["display_name"] == "P-4713"
    assert names["hx"]["display_name"] == "H-1009"
    assert names["pump"]["category"] == "equipment"


def test_nozzle_is_qualified_by_its_parent_equipment():
    names = derive_display_names(FACT_NODES, FACT_EDGES)
    # The two nozzles share sub-tag N-1 but are disambiguated by their owners.
    assert names["noz_pump"]["display_name"] == "P-4713 / N-1"
    assert names["noz_hx"]["display_name"] == "H-1009 / N-1"
    assert names["noz_pump"]["category"] == "nozzle"


def test_piping_connection_node_inherits_meaning_from_its_nozzle():
    names = derive_display_names(FACT_NODES, FACT_EDGES)
    assert names["pnode"]["display_name"] == "P-4713 / N-1 (connection)"
    assert names["pnode"]["category"] == "connection"


def test_piping_system_is_named_by_line_number():
    names = derive_display_names(FACT_NODES, FACT_EDGES)
    assert names["system"]["display_name"] == "Line 47132"
    assert names["system"]["category"] == "line"


def test_segment_inherits_its_line():
    names = derive_display_names(FACT_NODES, FACT_EDGES)
    assert names["segment"]["display_name"] == "Line 47132 (segment)"


def test_friendly_class_name_is_used_when_no_tag_exists():
    names = derive_display_names(FACT_NODES, FACT_EDGES)
    # The model root is structural and gets a readable, spaced class name.
    assert names["root"]["display_name"] == "Conceptual Model"
    assert names["root"]["category"] == "structural"


def test_class_label_and_description_are_carried_through():
    names = derive_display_names(FACT_NODES, FACT_EDGES)
    assert names["pump"]["class_name"] == "Centrifugal Pump"
    assert names["pump"]["description"] == "A pump."
