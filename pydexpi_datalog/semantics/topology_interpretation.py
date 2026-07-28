from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from .derive_graph_semantics import PROCESS_PIPING_ATTR_NAMES

DIRECTED_RELATIONSHIPS = frozenset(
    {"source", "target", "sourceItem", "targetItem", "sourceNode", "targetNode"}
)


@dataclass(frozen=True)
class RawEdgeIdentity:
    source_id: str
    target_id: str
    edge_key: str


@dataclass(frozen=True)
class StructuralPathWitness:
    raw_node_ids: list[str]
    raw_edges: list[RawEdgeIdentity]
    topology_node_ids: list[str]
    topology_edge_ids: list[str]
    relationships: list[str]


@dataclass(frozen=True)
class ReachableObject:
    topology_id: str
    label: str
    node_class: str
    category: str
    source_id: str | None
    direction_status: str
    witness: StructuralPathWitness


@dataclass(frozen=True)
class ReachabilityResult:
    source_id: str
    reachable: list[ReachableObject]
    error: str | None = None
    truncated: bool = False


def stable_hash_id(prefix: str, payload: object) -> str:
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def build_stable_node_id_map(fact_nodes: list[dict[str, object]]) -> dict[str, str]:
    ids_by_raw_id: dict[str, str] = {}
    signature_counts: dict[str, int] = {}
    for node in sorted(
        fact_nodes,
        key=lambda item: json.dumps(item["attributes"], sort_keys=True),
    ):
        stable_base = stable_hash_id("node", node["attributes"])
        signature_counts[stable_base] = signature_counts.get(stable_base, 0) + 1
        suffix = signature_counts[stable_base]
        stable_id = stable_base if suffix == 1 else f"{stable_base}-{suffix}"
        ids_by_raw_id[str(node["node_id"])] = stable_id
    return ids_by_raw_id


def stable_edge_id(
    *, edge: dict[str, object], raw_to_topology_node_id: dict[str, str]
) -> str:
    attributes = edge.get("attributes", {})
    if not isinstance(attributes, dict):
        attributes = {}
    source_id = raw_to_topology_node_id[str(edge["source_id"])]
    target_id = raw_to_topology_node_id[str(edge["target_id"])]
    edge_key = str(edge["edge_key"])
    return stable_hash_id(
        "edge",
        {
            "source_id": source_id,
            "target_id": target_id,
            "edge_key": edge_key,
            "relationship": attributes.get("attr_name"),
            "edge_family": attributes.get("label"),
        },
    )


def classify_path_direction_basis(relationships: Iterable[str]) -> str:
    relationship_list = list(relationships)
    if not relationship_list:
        return "unknown"
    if all(relationship in DIRECTED_RELATIONSHIPS for relationship in relationship_list):
        return "explicit"
    return "inferred"


class TopologyInterpretation:
    """Read-only interpretation of canonical pyDEXPI full-graph facts.

    The module computes process-facing relationships as conclusions over the
    canonical base facts. `topology_view` is accepted only as an Adapter for
    display labels and stable evidence IDs; traversal is built from graph facts.
    """

    DEFAULT_RESULT_LIMIT = 30

    def __init__(
        self,
        *,
        graph_facts: dict[str, object],
        topology_view: dict[str, object] | None = None,
        session_id: str,
        source_id: str | None = None,
    ) -> None:
        self._graph_facts = graph_facts
        self._topology_view = topology_view or {}
        self._session_id = session_id
        self._source_id = source_id
        facts = graph_facts.get("facts", {})
        if not isinstance(facts, dict):
            facts = {}
        self._fact_nodes: list[dict[str, object]] = list(facts.get("nodes", []))  # type: ignore[arg-type]
        self._fact_edges: list[dict[str, object]] = list(facts.get("edges", []))  # type: ignore[arg-type]

        self._raw_to_topology_node_id = self._node_id_map()
        self._topology_to_raw_node_id = {
            topology_id: raw_id for raw_id, topology_id in self._raw_to_topology_node_id.items()
        }
        self._node_info_by_topology_id = self._build_node_info()
        self._topology_edge_id_by_raw_identity = self._build_topology_edge_id_map()
        self._adjacency: dict[
            str, list[tuple[str, str, str, RawEdgeIdentity]]
        ] = self._build_adjacency()

    def known_topology_ids(self) -> set[str]:
        ids = set(self._node_info_by_topology_id)
        for entries in self._adjacency.values():
            for _, edge_id, _, _ in entries:
                ids.add(edge_id)
        return ids

    def reachable_from(
        self, topology_id: str, *, max_hops: int, result_limit: int | None = None
    ) -> ReachabilityResult:
        if topology_id not in self._node_info_by_topology_id:
            return ReachabilityResult(
                source_id=topology_id,
                reachable=[],
                error=f"unknown equipment_id: {topology_id}",
            )

        limit = result_limit or self.DEFAULT_RESULT_LIMIT
        visited: set[str] = {topology_id}
        start_raw_id = self._topology_to_raw_node_id.get(topology_id, topology_id)
        queue: deque[
            tuple[str, list[str], list[str], list[str], list[RawEdgeIdentity], list[str]]
        ] = deque([(topology_id, [topology_id], [], [start_raw_id], [], [])])
        reachable: list[ReachableObject] = []
        truncated = False

        while queue:
            current_id, topology_nodes, topology_edges, raw_nodes, raw_edges, relationships = queue.popleft()
            for neighbor_id, edge_id, relationship, raw_edge in self._adjacency.get(current_id, []):
                if neighbor_id in visited:
                    continue

                next_topology_nodes = topology_nodes + [neighbor_id]
                if len(next_topology_nodes) > max_hops + 1:
                    truncated = True
                    continue

                visited.add(neighbor_id)
                neighbor_raw_id = self._topology_to_raw_node_id.get(neighbor_id, neighbor_id)
                next_topology_edges = topology_edges + [edge_id]
                next_raw_nodes = raw_nodes + [neighbor_raw_id]
                next_raw_edges = raw_edges + [raw_edge]
                next_relationships = relationships + [relationship]

                if len(reachable) >= limit:
                    truncated = True
                    continue

                node = self._node_info_by_topology_id[neighbor_id]
                witness = StructuralPathWitness(
                    raw_node_ids=list(next_raw_nodes),
                    raw_edges=list(next_raw_edges),
                    topology_node_ids=list(next_topology_nodes),
                    topology_edge_ids=list(next_topology_edges),
                    relationships=list(next_relationships),
                )
                reachable.append(
                    ReachableObject(
                        topology_id=neighbor_id,
                        label=self._node_label(neighbor_id),
                        node_class=str(node.get("class_name") or node.get("label") or ""),
                        category=str(node.get("category") or "other"),
                        source_id=self._source_id or self._session_id,
                        direction_status=classify_path_direction_basis(next_relationships),
                        witness=witness,
                    )
                )
                queue.append(
                    (
                        neighbor_id,
                        next_topology_nodes,
                        next_topology_edges,
                        next_raw_nodes,
                        next_raw_edges,
                        next_relationships,
                    )
                )

        return ReachabilityResult(
            source_id=topology_id,
            reachable=reachable,
            truncated=truncated,
        )

    def _node_id_map(self) -> dict[str, str]:
        if self._topology_view.get("nodes"):
            mapped: dict[str, str] = {}
            for node in self._topology_view.get("nodes", []):
                if not isinstance(node, dict):
                    continue
                raw_id = node.get("source_graph_node_id")
                topology_id = node.get("id")
                if isinstance(raw_id, str) and isinstance(topology_id, str):
                    mapped[raw_id] = topology_id
            if mapped:
                return mapped
        return build_stable_node_id_map(self._fact_nodes)

    def _build_node_info(self) -> dict[str, dict[str, object]]:
        node_info: dict[str, dict[str, object]] = {}
        for node in self._topology_view.get("nodes", []):
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                node_info[str(node["id"])] = dict(node)

        for fact_node in self._fact_nodes:
            raw_id = str(fact_node["node_id"])
            topology_id = self._raw_to_topology_node_id[raw_id]
            if topology_id in node_info:
                continue
            attributes = fact_node.get("attributes", {})
            if not isinstance(attributes, dict):
                attributes = {}
            node_info[topology_id] = {
                "id": topology_id,
                "label": attributes.get("label", topology_id),
                "tag_name": attributes.get("tagName"),
                "display_name": attributes.get("tagName") or attributes.get("label") or topology_id,
                "class_name": attributes.get("label", ""),
                "category": "other",
                "source_graph_node_id": raw_id,
            }
        return node_info

    def _build_adjacency(
        self,
    ) -> dict[str, list[tuple[str, str, str, RawEdgeIdentity]]]:
        adjacency: dict[str, list[tuple[str, str, str, RawEdgeIdentity]]] = {}
        for edge in self._fact_edges:
            attributes = edge.get("attributes", {})
            if not isinstance(attributes, dict):
                attributes = {}
            relationship = str(attributes.get("attr_name", ""))
            if relationship not in PROCESS_PIPING_ATTR_NAMES:
                continue
            raw_source = str(edge["source_id"])
            raw_target = str(edge["target_id"])
            if raw_source not in self._raw_to_topology_node_id or raw_target not in self._raw_to_topology_node_id:
                continue
            source_id = self._raw_to_topology_node_id[raw_source]
            target_id = self._raw_to_topology_node_id[raw_target]
            edge_id = self._edge_id_for_fact_edge(edge)
            raw_edge = RawEdgeIdentity(
                source_id=raw_source,
                target_id=raw_target,
                edge_key=str(edge["edge_key"]),
            )
            adjacency.setdefault(source_id, []).append((target_id, edge_id, relationship, raw_edge))
            adjacency.setdefault(target_id, []).append((source_id, edge_id, relationship, raw_edge))

        for entries in adjacency.values():
            entries.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
        return adjacency

    def _build_topology_edge_id_map(self) -> dict[tuple[str, str, str], str]:
        mapped: dict[tuple[str, str, str], str] = {}
        for edge in self._topology_view.get("edges", []):
            if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
                continue
            source_graph_edge = edge.get("source_graph_edge")
            if not isinstance(source_graph_edge, dict):
                continue
            source_id = source_graph_edge.get("source_id")
            target_id = source_graph_edge.get("target_id")
            edge_key = source_graph_edge.get("edge_key")
            if isinstance(source_id, str) and isinstance(target_id, str):
                mapped[(source_id, target_id, str(edge_key))] = str(edge["id"])
        return mapped

    def _edge_id_for_fact_edge(self, edge: dict[str, object]) -> str:
        raw_identity = (
            str(edge["source_id"]),
            str(edge["target_id"]),
            str(edge["edge_key"]),
        )
        mapped = self._topology_edge_id_by_raw_identity.get(raw_identity)
        if mapped is not None:
            return mapped
        return stable_edge_id(edge=edge, raw_to_topology_node_id=self._raw_to_topology_node_id)

    def _node_label(self, topology_id: str) -> str:
        node = self._node_info_by_topology_id.get(topology_id, {})
        return str(
            node.get("display_name")
            or node.get("tag_name")
            or node.get("label")
            or topology_id
        )
