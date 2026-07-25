from __future__ import annotations

from pydexpi_datalog.semantics.topology_interpretation import TopologyInterpretation
from pydexpi_datalog.workflow.review_session import build_topology_view_model

GRAPH_FACTS: dict[str, object] = {
    "fixture_id": "minimal-pump-valve",
    "source_path": "minimal.xml",
    "graph": {"node_count": 4, "edge_count": 3},
    "facts": {
        "nodes": [
            {
                "fact_type": "node",
                "node_id": "raw-pump",
                "attributes": {"label": "CentrifugalPump", "tagName": "P-101"},
            },
            {
                "fact_type": "node",
                "node_id": "raw-nozzle",
                "attributes": {"label": "Nozzle", "tagName": "N-1"},
            },
            {
                "fact_type": "node",
                "node_id": "raw-segment",
                "attributes": {"label": "PipingNetworkSegment", "tagName": "S-1"},
            },
            {
                "fact_type": "node",
                "node_id": "raw-valve",
                "attributes": {"label": "CheckValve", "tagName": "V-102"},
            },
        ],
        "edges": [
            {
                "fact_type": "edge",
                "source_id": "raw-pump",
                "target_id": "raw-nozzle",
                "edge_key": "e1",
                "attributes": {"label": "reference", "attr_name": "sourceItem"},
            },
            {
                "fact_type": "edge",
                "source_id": "raw-nozzle",
                "target_id": "raw-segment",
                "edge_key": "e2",
                "attributes": {"label": "reference", "attr_name": "targetItem"},
            },
            {
                "fact_type": "edge",
                "source_id": "raw-segment",
                "target_id": "raw-valve",
                "edge_key": "e3",
                "attributes": {"label": "reference", "attr_name": "targetItem"},
            },
        ],
    },
    "provenance": {"extractor": "test"},
}


def _topology_id_for_raw_node(topology: dict[str, object], raw_node_id: str) -> str:
    for node in topology["nodes"]:
        if node["source_graph_node_id"] == raw_node_id:
            return str(node["id"])
    raise AssertionError(f"missing topology node for {raw_node_id}")


def test_reachable_relationship_includes_complete_canonical_witness() -> None:
    """
    Behavior: read-only topology interpretation computes process-facing
    reachability from canonical base facts and returns a complete ordered
    structural path witness that can still be highlighted through topology IDs.
    """
    topology = build_topology_view_model(
        graph_facts=GRAPH_FACTS, session_id="session-1", source_id="source-1"
    )
    pump_id = _topology_id_for_raw_node(topology, "raw-pump")
    valve_id = _topology_id_for_raw_node(topology, "raw-valve")

    interpretation = TopologyInterpretation(
        graph_facts=GRAPH_FACTS,
        topology_view=topology,
        session_id="session-1",
        source_id="source-1",
    )

    result = interpretation.reachable_from(pump_id, max_hops=4)
    valve = next(item for item in result.reachable if item.topology_id == valve_id)

    assert valve.direction_status == "explicit"
    assert valve.witness.raw_node_ids == [
        "raw-pump",
        "raw-nozzle",
        "raw-segment",
        "raw-valve",
    ]
    assert [edge.edge_key for edge in valve.witness.raw_edges] == ["e1", "e2", "e3"]
    assert valve.witness.topology_node_ids[0] == pump_id
    assert valve.witness.topology_node_ids[-1] == valve_id
    assert all(
        topology_id in topology["evidence_map"]
        for topology_id in valve.witness.topology_node_ids + valve.witness.topology_edge_ids
    )
