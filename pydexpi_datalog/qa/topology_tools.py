from __future__ import annotations

from pydexpi_datalog.semantics.derive_graph_semantics import TOPOLOGY_ATTR_NAMES
from pydexpi_datalog.semantics.topology_interpretation import TopologyInterpretation



class TopologyTools:
    """Read-only topology operations exposed to the model as native tool calls."""

    MAX_FIND_RESULTS = 25

    def __init__(
        self,
        *,
        topology_view: dict[str, object],
        session_id: str,
        graph_facts: dict[str, object] | None = None,
    ) -> None:
        self._topology = topology_view
        self._session_id = session_id
        self._nodes: list[dict[str, object]] = list(topology_view.get("nodes", []))  # type: ignore[arg-type]
        self._edges: list[dict[str, object]] = list(topology_view.get("edges", []))  # type: ignore[arg-type]
        self._evidence_map: dict[str, object] = dict(topology_view.get("evidence_map", {}))  # type: ignore[arg-type]
        self._uses_topology_adapter = graph_facts is None
        self._graph_facts = graph_facts or self._graph_facts_from_topology_view()
        self._interpretation = TopologyInterpretation(
            graph_facts=self._graph_facts,
            topology_view=self._topology_with_source_graph_ids(),
            session_id=session_id,
            source_id=str(topology_view.get("source_id") or session_id),
        )


    def tool_definitions(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "find_equipment",
                    "description": (
                        "Search for objects by tag, line number, label, or class "
                        "(e.g. 'P-4713', '47132', 'pump', 'nozzle'). Use an empty "
                        "pattern to list everything. Results are ordered with "
                        "process equipment, nozzles, and lines before internal "
                        "connection nodes, and each carries label/category/description."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": (
                                    "Search term matched against tag name or label. "
                                    "Empty string returns all equipment."
                                ),
                            }
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_reachable_equipment",
                    "description": (
                        "Find topology objects reachable from a given equipment via graph edges, "
                        "with the complete ordered structural path witness for each result."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "equipment_id": {
                                "type": "string",
                                "description": "The evidence_id of the source equipment node.",
                            },
                            "max_hops": {
                                "type": "integer",
                                "description": "Maximum traversal depth (default 6).",
                                "default": 6,
                            },
                        },
                        "required": ["equipment_id"],
                    },
                },
            },
        ]

    def execute(self, tool_name: str, tool_input: dict[str, object]) -> dict[str, object]:
        if tool_name == "find_equipment":
            return self._find_equipment(str(tool_input.get("pattern", "")))
        if tool_name == "get_reachable_equipment":
            return self._get_reachable_equipment(
                str(tool_input.get("equipment_id", "")),
                int(tool_input.get("max_hops", 6)),
            )
        return {"error": f"unknown tool: {tool_name}", "reachable": [], "matches": []}

    def known_evidence_ids(self) -> set[str]:
        return set(self._evidence_map.keys())

    # Process-meaningful objects are offered before model-internal plumbing so
    # the model foregrounds equipment, nozzles, and lines over connection nodes.
    _CATEGORY_RANK = {
        "equipment": 0,
        "nozzle": 1,
        "line": 2,
        "piping": 3,
        "connection": 4,
        "structural": 5,
        "other": 6,
    }

    def _find_equipment(self, pattern: str) -> dict[str, object]:
        normalized = pattern.lower()
        matches = []
        for index, node in enumerate(self._nodes):
            display_name = str(node.get("display_name") or "")
            class_name = str(node.get("class_name") or "")
            raw_label = str(node.get("label", ""))
            tag_name = str(node.get("tag_name") or "")
            category = str(node.get("category") or "other")
            haystack = " ".join(
                [display_name, class_name, raw_label, tag_name, category]
            ).lower()
            if not normalized or normalized in haystack:
                matches.append(
                    (
                        self._CATEGORY_RANK.get(category, 99),
                        index,
                        {
                            "evidence_id": node["id"],
                            "label": display_name or tag_name or raw_label or str(node["id"]),
                            "node_class": class_name or raw_label,
                            "category": category,
                            "description": str(node.get("description") or ""),
                            "source_id": self._session_id,
                        },
                    )
                )
        matches.sort(key=lambda item: (item[0], item[1]))
        ordered = [entry for _, _, entry in matches]
        total = len(ordered)
        bounded = ordered[: self.MAX_FIND_RESULTS]
        return {
            "matches": bounded,
            "count": len(bounded),
            "total_matches": total,
            "truncated": total > len(bounded),
        }

    def _get_reachable_equipment(
        self, equipment_id: str, max_hops: int
    ) -> dict[str, object]:
        result = self._interpretation.reachable_from(
            equipment_id,
            max_hops=max_hops,
            result_limit=30,
        )
        if result.error is not None:
            return {
                "error": result.error,
                "source_id": equipment_id,
                "reachable": [],
            }

        reachable = [
            {
                "evidence_id": item.topology_id,
                "label": item.label,
                "node_class": item.node_class,
                "category": item.category,
                "direction_status": item.direction_status,
                "source_id": item.source_id,
                "witness": {
                    "node_ids": list(item.witness.topology_node_ids),
                    "edge_ids": list(item.witness.topology_edge_ids),
                    "raw_node_ids": list(item.witness.raw_node_ids),
                    "raw_edges": [
                        {
                            "source_id": edge.source_id,
                            "target_id": edge.target_id,
                            "edge_key": edge.edge_key,
                        }
                        for edge in item.witness.raw_edges
                    ],
                },
            }
            for item in result.reachable
        ]
        response: dict[str, object] = {
            "source_id": equipment_id,
            "reachable": reachable,
        }
        if result.truncated:
            response["truncated"] = True
        return response

    def _topology_with_source_graph_ids(self) -> dict[str, object]:
        topology = dict(self._topology)
        topology["nodes"] = []
        for node in self._nodes:
            source_graph_node_id = (
                node.get("id")
                if self._uses_topology_adapter
                else node.get("source_graph_node_id") or node.get("id")
            )
            topology["nodes"].append(
                {**node, "source_graph_node_id": source_graph_node_id}
            )
        topology["edges"] = []
        for edge in self._edges:
            source_graph_edge = (
                {
                    "source_id": edge.get("source_id"),
                    "target_id": edge.get("target_id"),
                    "edge_key": edge.get("id"),
                }
                if self._uses_topology_adapter
                else edge.get("source_graph_edge")
                or {
                    "source_id": edge.get("source_id"),
                    "target_id": edge.get("target_id"),
                    "edge_key": edge.get("id"),
                }
            )
            topology["edges"].append({**edge, "source_graph_edge": source_graph_edge})
        return topology

    def _graph_facts_from_topology_view(self) -> dict[str, object]:
        nodes = [
            {
                "fact_type": "node",
                "node_id": str(node["id"]),
                "attributes": {
                    "label": str(node.get("label") or node.get("class_name") or ""),
                    "tagName": str(node.get("tag_name") or node.get("display_name") or ""),
                },
            }
            for node in self._nodes
        ]
        edges = [
            {
                "fact_type": "edge",
                "source_id": str(edge["source_id"]),
                "target_id": str(edge["target_id"]),
                "edge_key": str(edge["id"]),
                "attributes": {
                    "label": str(edge.get("edge_family") or "reference"),
                    "attr_name": self._topology_relationship(edge),
                },
            }
            for edge in self._edges
        ]
        return {
            "fixture_id": "topology-view-adapter",
            "source_path": "",
            "graph": {"node_count": len(nodes), "edge_count": len(edges)},
            "facts": {"nodes": nodes, "edges": edges},
            "provenance": {"extractor": "topology_view_adapter"},
        }

    @staticmethod
    def _topology_relationship(edge: dict[str, object]) -> str:
        relationship = str(edge.get("relationship") or "")
        return relationship if relationship in TOPOLOGY_ATTR_NAMES else "connections"

    def _node_info(self, node_id: str) -> dict[str, object] | None:
        for node in self._nodes:
            if node["id"] == node_id:
                return node
        return None

    def _node_label(self, node_id: str) -> str:
        node = self._node_info(node_id)
        if node:
            return str(
                node.get("display_name")
                or node.get("tag_name")
                or node.get("label")
                or node_id
            )
        return node_id
