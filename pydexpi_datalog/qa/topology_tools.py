from __future__ import annotations

import hashlib
import re

from pydexpi_datalog.qa.capability_manifest import (
    PERMISSION_ALLOWED_READ_ONLY,
    PERMISSION_CONFIRMATION_REQUIRED,
    PERMISSION_DENIED,
    default_grounded_qa_manifest,
)

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
        self._capability_manifest = default_grounded_qa_manifest()
        self._uses_topology_adapter = graph_facts is None
        self._graph_facts = graph_facts or self._graph_facts_from_topology_view()
        self._interpretation = TopologyInterpretation(
            graph_facts=self._graph_facts,
            topology_view=self._topology_with_source_graph_ids(),
            session_id=session_id,
            source_id=str(topology_view.get("source_id") or session_id),
        )


    def tool_definitions(self) -> list[dict[str, object]]:
        return self._capability_manifest.provider_tool_definitions()

    def execute(self, tool_name: str, tool_input: dict[str, object]) -> dict[str, object]:
        capability = self._capability_manifest.get(tool_name)
        if capability is None:
            return self._tool_rejection(
                tool_name=tool_name,
                code="tool.unknown",
                message=f"unknown tool: {tool_name}",
            )
        if capability.permission_class == PERMISSION_DENIED:
            return self._tool_rejection(
                tool_name=tool_name,
                code="tool.denied",
                message=capability.denied_reason or f"denied tool: {tool_name}",
            )
        if capability.permission_class == PERMISSION_CONFIRMATION_REQUIRED:
            if tool_name == "propose_temporary_datalog":
                return self._propose_temporary_datalog(tool_input)
            return {
                "status": "confirmation_required",
                "code": "tool.confirmation_required",
                "tool_name": tool_name,
                "message": (
                    f"{tool_name} requires explicit user confirmation before execution."
                ),
                "permission_class": capability.permission_class,
                "matches": [],
                "reachable": [],
            }
        if capability.permission_class != PERMISSION_ALLOWED_READ_ONLY:
            return self._tool_rejection(
                tool_name=tool_name,
                code="tool.unsupported_permission",
                message=f"unsupported permission class: {capability.permission_class}",
            )
        if tool_name == "find_equipment":
            return self._find_equipment(str(tool_input.get("pattern", "")))
        if tool_name == "get_reachable_equipment":
            return self._get_reachable_equipment(
                str(tool_input.get("equipment_id", "")),
                int(tool_input.get("max_hops", 6)),
            )
        return self._tool_rejection(
            tool_name=tool_name,
            code="tool.unimplemented",
            message=f"no adapter registered for tool: {tool_name}",
        )

    @staticmethod
    def _tool_rejection(
        *, tool_name: str, code: str, message: str
    ) -> dict[str, object]:
        return {
            "status": "rejected",
            "code": code,
            "tool_name": tool_name,
            "message": message,
            "matches": [],
            "reachable": [],
        }

    def _propose_temporary_datalog(
        self, tool_input: dict[str, object]
    ) -> dict[str, object]:
        request = str(tool_input.get("request", "")).strip()
        generated_datalog = str(tool_input.get("generated_datalog", ""))
        formal_restatement = str(tool_input.get("formal_restatement", "")).strip()
        resolved_identity_ids = [
            identity
            for identity in tool_input.get("resolved_identity_ids", [])
            if isinstance(identity, str)
        ]
        validation = self._validate_temporary_datalog(
            generated_datalog=generated_datalog,
            formal_restatement=formal_restatement,
        )
        proposal_id = self._temporary_datalog_proposal_id(
            request=request,
            generated_datalog=generated_datalog,
            formal_restatement=formal_restatement,
        )
        return {
            "status": "confirmation_required",
            "code": "tool.confirmation_required",
            "tool_name": "propose_temporary_datalog",
            "executed": False,
            "proposal": {
                "proposal_id": proposal_id,
                "request": request,
                "generated_datalog": generated_datalog,
                "formal_restatement": formal_restatement,
                "resolved_identity_ids": resolved_identity_ids,
            },
            "validation": validation,
            "confirmation": {
                "required": True,
                "grant": "execute_temporary_datalog_pair",
                "proposal_id": proposal_id,
            },
            "matches": [],
            "reachable": [],
        }

    @staticmethod
    def _temporary_datalog_proposal_id(
        *, request: str, generated_datalog: str, formal_restatement: str
    ) -> str:
        return hashlib.sha256(
            (request + "\n" + generated_datalog + "\n" + formal_restatement).encode(
                "utf-8"
            )
        ).hexdigest()[:16]

    def _validate_temporary_datalog(
        self, *, generated_datalog: str, formal_restatement: str
    ) -> dict[str, object]:
        diagnostics = []
        stripped = generated_datalog.strip()
        if not stripped or not formal_restatement:
            diagnostics.append(
                {
                    "code": "temporary_datalog.missing_pair",
                    "message": "Temporary Datalog proposals require generated_datalog and formal_restatement.",
                }
            )
        if len(stripped) > 4_000:
            diagnostics.append(
                {
                    "code": "temporary_datalog.size_limit",
                    "message": "Temporary Datalog proposal exceeds the 4000 character size limit.",
                }
            )
        lowered = stripped.lower()
        if any(token in lowered for token in (".include", ".input", "file://", "../")):
            diagnostics.append(
                {
                    "code": "temporary_datalog.filesystem_forbidden",
                    "message": "Temporary Datalog cannot include files, declare inputs, or reference filesystem paths.",
                }
            )
        syntax_invalid = False
        for line in stripped.splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("//"):
                continue
            if not candidate.startswith(".") and not candidate.endswith("."):
                syntax_invalid = True
            if candidate.count('"') % 2 != 0:
                syntax_invalid = True
        if syntax_invalid:
            diagnostics.append(
                {
                    "code": "temporary_datalog.syntax_invalid",
                    "message": "Temporary Datalog must use complete line-oriented Souffle declarations, outputs, facts, or rules.",
                }
            )
        predicate_names = []
        for line in stripped.splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("."):
                continue
            predicate_names.extend(
                re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", candidate)
            )
        approved_predicates = {"answer", "reachable"}
        unapproved_predicates = sorted(
            {predicate for predicate in predicate_names if predicate not in approved_predicates}
        )
        if unapproved_predicates:
            diagnostics.append(
                {
                    "code": "temporary_datalog.predicate_not_approved",
                    "message": "Temporary Datalog used unapproved predicate(s): "
                    + ", ".join(unapproved_predicates),
                }
            )
        output_lines = [
            line.strip() for line in stripped.splitlines() if line.strip().startswith(".output")
        ]
        if output_lines != [".output answer"]:
            diagnostics.append(
                {
                    "code": "temporary_datalog.output_shape",
                    "message": "Temporary Datalog must output exactly answer(x:symbol).",
                }
            )
        if ".decl answer(x:symbol)" not in stripped:
            diagnostics.append(
                {
                    "code": "temporary_datalog.answer_decl_missing",
                    "message": "Temporary Datalog must declare answer(x:symbol).",
                }
            )
        literal_answer_facts = [
            line.strip()
            for line in stripped.splitlines()
            if line.strip().startswith("answer(") and ":-" not in line
        ]
        if len(literal_answer_facts) > 100:
            diagnostics.append(
                {
                    "code": "temporary_datalog.row_limit",
                    "message": "Temporary Datalog answer facts exceed the 100 row limit.",
                }
            )
        known_ids = self.known_evidence_ids()
        unresolved = [
            fact.removeprefix("answer(").removesuffix(").").strip().strip('"')
            for fact in literal_answer_facts
            if fact.endswith(").")
            and fact.removeprefix("answer(").removesuffix(").").strip().strip('"')
            not in known_ids
        ]
        if unresolved:
            diagnostics.append(
                {
                    "code": "temporary_datalog.unresolved_identity",
                    "message": "Temporary Datalog answered unknown evidence IDs: "
                    + ", ".join(unresolved),
                }
            )
        if diagnostics:
            return {
                "status": "rejected",
                "diagnostics": diagnostics,
                "limits": {"timeout_seconds": 2, "row_limit": 100, "size_limit": 4000},
            }
        return {
            "status": "safe_to_confirm",
            "diagnostics": [],
            "limits": {"timeout_seconds": 2, "row_limit": 100, "size_limit": 4000},
        }

    def _temporary_datalog_answer_ids(self, generated_datalog: str) -> list[str]:
        matched_ids: list[str] = []
        for line in generated_datalog.splitlines():
            candidate = line.strip()
            if (
                candidate.startswith("answer(")
                and candidate.endswith(").")
                and ":-" not in candidate
            ):
                topology_id = (
                    candidate.removeprefix("answer(")
                    .removesuffix(").")
                    .strip()
                    .strip('"')
                )
                if topology_id in self._evidence_map and topology_id not in matched_ids:
                    matched_ids.append(topology_id)
                continue
            reachable_match = re.fullmatch(
                r'answer\(x\)\s*:-\s*reachable\("([^"]+)",\s*x\)\.',
                candidate,
            )
            if reachable_match:
                result = self._interpretation.reachable_from(
                    reachable_match.group(1), max_hops=6
                )
                for reachable in result.reachable:
                    if reachable.topology_id not in matched_ids:
                        matched_ids.append(reachable.topology_id)
        return matched_ids

    def execute_confirmed_temporary_datalog(
        self, proposal_result: dict[str, object]
    ) -> dict[str, object]:
        proposal = proposal_result.get("proposal")
        confirmation = proposal_result.get("confirmation")
        validation = proposal_result.get("validation")
        if not isinstance(proposal, dict) or not isinstance(confirmation, dict):
            return {
                "status": "execution_failed",
                "executed": False,
                "diagnostics": [
                    {
                        "code": "temporary_datalog.confirmation_missing",
                        "message": "Temporary Datalog execution requires the exact confirmed proposal pair.",
                    }
                ],
            }
        if not isinstance(validation, dict) or validation.get("status") != "safe_to_confirm":
            return {
                "status": "execution_failed",
                "executed": False,
                "confirmation": confirmation,
                "diagnostics": list(validation.get("diagnostics", []))
                if isinstance(validation, dict)
                else [],
            }
        request = str(proposal.get("request", ""))
        generated_datalog = str(proposal.get("generated_datalog", ""))
        formal_restatement = str(proposal.get("formal_restatement", ""))
        expected_proposal_id = self._temporary_datalog_proposal_id(
            request=request,
            generated_datalog=generated_datalog,
            formal_restatement=formal_restatement,
        )
        if confirmation.get("proposal_id") != expected_proposal_id:
            return {
                "status": "execution_failed",
                "executed": False,
                "confirmation": confirmation,
                "diagnostics": [
                    {
                        "code": "temporary_datalog.confirmation_mismatch",
                        "message": "Temporary Datalog execution requires the exact confirmed query/restatement pair.",
                    }
                ],
            }
        validation = self._validate_temporary_datalog(
            generated_datalog=generated_datalog,
            formal_restatement=str(proposal.get("formal_restatement", "")),
        )
        if validation["status"] != "safe_to_confirm":
            return {
                "status": "execution_failed",
                "executed": False,
                "confirmation": confirmation,
                "diagnostics": validation["diagnostics"],
            }
        matched_ids = self._temporary_datalog_answer_ids(generated_datalog)
        evidence_items = [
            {
                "id": topology_id,
                "label": self._node_label(topology_id),
                "source": "temporary_datalog",
                "topology_evidence": self._evidence_map[topology_id],
            }
            for topology_id in matched_ids
            if topology_id in self._evidence_map
        ]
        return {
            "status": "answered",
            "executed": True,
            "confirmation": confirmation,
            "summary": {
                "text": str(proposal.get("formal_restatement", "")),
            },
            "evidence": {
                "display": "expandable",
                "items": evidence_items,
            },
            "diagnostics": [],
        }

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
