from __future__ import annotations


class TopologyTools:
    """Read-only topology operations exposed to the model as native tool calls."""

    MAX_FIND_RESULTS = 25

    def __init__(self, *, topology_view: dict[str, object], session_id: str) -> None:
        self._topology = topology_view
        self._session_id = session_id
        self._nodes: list[dict[str, object]] = list(topology_view.get("nodes", []))  # type: ignore[arg-type]
        self._edges: list[dict[str, object]] = list(topology_view.get("edges", []))  # type: ignore[arg-type]
        self._evidence_map: dict[str, object] = dict(topology_view.get("evidence_map", {}))  # type: ignore[arg-type]
        self._adjacency: dict[str, list[tuple[str, str]]] = {}
        self._build_adjacency()

    def _build_adjacency(self) -> None:
        for edge in self._edges:
            src = str(edge["source_id"])
            tgt = str(edge["target_id"])
            edge_id = str(edge["id"])
            self._adjacency.setdefault(src, []).append((tgt, edge_id))
            self._adjacency.setdefault(tgt, []).append((src, edge_id))

    def tool_definitions(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "find_equipment",
                    "description": (
                        "Search for equipment by tag or label pattern. "
                        "Use an empty pattern to list all equipment."
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

    def _find_equipment(self, pattern: str) -> dict[str, object]:
        normalized = pattern.lower()
        matches = []
        for node in self._nodes:
            label = str(node.get("label", ""))
            tag_name = str(node.get("tag_name") or "")
            if (
                not normalized
                or normalized in label.lower()
                or normalized in tag_name.lower()
            ):
                matches.append(
                    {
                        "evidence_id": node["id"],
                        "label": tag_name or label or str(node["id"]),
                        "node_class": label,
                        "source_id": self._session_id,
                    }
                )
        total = len(matches)
        bounded = matches[: self.MAX_FIND_RESULTS]
        return {
            "matches": bounded,
            "count": len(bounded),
            "total_matches": total,
            "truncated": total > len(bounded),
        }

    def _get_reachable_equipment(
        self, equipment_id: str, max_hops: int
    ) -> dict[str, object]:
        if equipment_id not in self._evidence_map:
            return {
                "error": f"unknown equipment_id: {equipment_id}",
                "source_id": equipment_id,
                "reachable": [],
            }

        visited: set[str] = {equipment_id}
        # queue entries: (current_node_id, ordered_node_path, ordered_edge_path)
        queue: list[tuple[str, list[str], list[str]]] = [
            (equipment_id, [equipment_id], [])
        ]
        reachable: list[dict[str, object]] = []

        while queue and len(reachable) < 30:
            current_id, node_path, edge_path = queue.pop(0)
            if len(node_path) > max_hops + 1:
                continue

            for neighbor_id, edge_id in self._adjacency.get(current_id, []):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                new_node_path = node_path + [neighbor_id]
                new_edge_path = edge_path + [edge_id]

                neighbor = self._node_info(neighbor_id)
                if neighbor is not None:
                    reachable.append(
                        {
                            "evidence_id": neighbor_id,
                            "label": (
                                str(neighbor.get("tag_name") or neighbor.get("label") or neighbor_id)
                            ),
                            "direction_status": "inferred",
                            "source_id": self._session_id,
                            "witness": {
                                "node_ids": list(new_node_path),
                                "edge_ids": list(new_edge_path),
                            },
                        }
                    )

                queue.append((neighbor_id, new_node_path, new_edge_path))

        return {"source_id": equipment_id, "reachable": reachable}

    def _node_info(self, node_id: str) -> dict[str, object] | None:
        for node in self._nodes:
            if node["id"] == node_id:
                return node
        return None

    def _node_label(self, node_id: str) -> str:
        node = self._node_info(node_id)
        if node:
            return str(node.get("tag_name") or node.get("label") or node_id)
        return node_id
