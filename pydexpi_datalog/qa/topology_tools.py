from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from pydexpi_datalog.qa.capability_manifest import (
    PERMISSION_ALLOWED_READ_ONLY,
    PERMISSION_CONFIRMATION_REQUIRED,
    PERMISSION_DENIED,
    default_grounded_qa_manifest,
)
from pydexpi_datalog.qa.trusted_templates import execute_bundled_query_template

from pydexpi_datalog.semantics.derive_graph_semantics import (
    TOPOLOGY_ATTR_NAMES,
    build_graph_facts_datalog,
    load_graph_topology_idb,
)
from pydexpi_datalog.semantics.souffle_runner import (
    SouffleExecutionError,
    run_souffle_program,
)
from pydexpi_datalog.semantics.topology_interpretation import TopologyInterpretation
from pydexpi_datalog.verification.bundled_rule_pack import pack_metadata


# Reviewer-facing consent context for temporary Datalog proposals. The effect
# statement is hardcoded — never model-generated — because the executor is
# strictly read-only. The assumptions describe what the traversal actually
# does: undirected breadth-first reachability over topology-attribute edges.
TEMPORARY_DATALOG_EFFECT = (
    "Read-only analysis. Does not modify the P&ID, graph, annotations, or rule pack."
)

TEMPORARY_DATALOG_ASSUMPTIONS: dict[str, object] = {
    "included_edge_types": [
        "process-flow piping connectivity (source/target, sourceItem/targetItem)",
        "composition relationships (nodes, segments, pipingNetworkSystems)",
        "connector references between topology objects",
    ],
    "excluded_edge_types": [
        "instrument signal and annotation references outside the topology attributes",
        "any relationship not declared as a topology attribute",
    ],
    "recycle_paths": (
        "Recycle loops are traversed like any other connection; each object is "
        "visited at most once."
    ),
}


@dataclass(frozen=True)
class RetrievalBudgets:
    max_steps: int = 10
    max_seconds: float = 10.0
    max_paths: int = 30
    max_rows: int = 100
    max_evidence_objects: int = 100
    max_path_length: int = 30
    max_payload_bytes: int = 100_000


class TopologyTools:
    """Read-only topology operations exposed to the model as native tool calls."""

    MAX_FIND_RESULTS = 25

    def __init__(
        self,
        *,
        topology_view: dict[str, object],
        session_id: str,
        graph_facts: dict[str, object] | None = None,
        retrieval_budgets: RetrievalBudgets | None = None,
        loaded_rule_pack_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> None:
        self._topology = topology_view
        self._session_id = session_id
        self._retrieval_budgets = retrieval_budgets or RetrievalBudgets()
        self._retrieval_steps = 0
        # Accumulates only time actually spent executing a tool's retrieval
        # work (see execute()'s timing wrapper below) -- deliberately excludes
        # time spent waiting on the model between tool calls, so the budget
        # measures retrieval cost, not turn wall-clock. A wall-clock-since-
        # session-start version of this previously double-charged the budget
        # for the model's own inference latency: a slower model (e.g. a large
        # reasoning model over BYOK/OpenRouter) could exhaust the whole budget
        # on thinking time alone, making every subsequent retrieval call
        # return a spurious time_limit rejection regardless of how trivial
        # the actual graph traversal was.
        self._retrieval_seconds_used = 0.0
        self._nodes: list[dict[str, object]] = list(topology_view.get("nodes", []))  # type: ignore[arg-type]
        self._edges: list[dict[str, object]] = list(topology_view.get("edges", []))  # type: ignore[arg-type]
        self._evidence_map: dict[str, object] = dict(
            topology_view.get("evidence_map", {})
        )  # type: ignore[arg-type]
        self._uses_topology_adapter = graph_facts is None
        self._graph_facts = graph_facts or self._graph_facts_from_topology_view()
        self._loaded_rule_pack_ids = tuple(
            sorted(str(pack_id) for pack_id in (loaded_rule_pack_ids or ()))
        )
        self._capability_manifest = default_grounded_qa_manifest(
            temporary_datalog_contract=self._temporary_datalog_contract_description()
        )
        self._interpretation = TopologyInterpretation(
            graph_facts=self._graph_facts,
            topology_view=self._topology_with_source_graph_ids(),
            session_id=session_id,
            source_id=str(topology_view.get("source_id") or session_id),
        )

    def tool_definitions(self) -> list[dict[str, object]]:
        return self._capability_manifest.provider_tool_definitions()

    def system_prompt(self) -> str:
        """Model-facing system prompt derived from the capability manifest."""
        return self._capability_manifest.system_prompt()

    def execute(
        self, tool_name: str, tool_input: dict[str, object]
    ) -> dict[str, object]:
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
        budget_rejection = self._operation_budget_rejection()
        if budget_rejection is not None:
            return budget_rejection
        self._retrieval_steps += 1
        if tool_name == "find_equipment":
            return self._timed_retrieval(
                lambda: self._find_equipment(
                    str(tool_input.get("pattern", "")),
                    claim_type=str(tool_input.get("claim_type", "existential")),
                    evidence_role=str(tool_input.get("evidence_role", "witness")),
                )
            )
        if tool_name == "get_reachable_equipment":
            return self._timed_retrieval(
                lambda: self._get_reachable_equipment(
                    str(tool_input.get("equipment_id", "")),
                    int(tool_input.get("max_hops", 6)),
                    claim_type=str(tool_input.get("claim_type", "existential")),
                )
            )
        if tool_name == "execute_bundled_query_template":
            return self._timed_retrieval(
                lambda: self._execute_bundled_query_template(tool_input)
            )
        return self._tool_rejection(
            tool_name=tool_name,
            code="tool.unimplemented",
            message=f"no adapter registered for tool: {tool_name}",
        )

    def _execute_bundled_query_template(
        self, tool_input: dict[str, object]
    ) -> dict[str, object]:
        result = execute_bundled_query_template(
            request=str(tool_input.get("request", "")),
            template_id=str(tool_input.get("template_id", "")),
            bindings=tool_input.get("bindings"),
            graph_facts=self._graph_facts,
        )
        raw_witnesses = result.get("witnesses", [])
        if isinstance(raw_witnesses, list):
            result["witnesses"] = self._temporary_answer_evidence_ids(
                [str(witness) for witness in raw_witnesses]
            )
        return result

    def _timed_retrieval(
        self, run: Callable[[], dict[str, object]]
    ) -> dict[str, object]:
        started_at = monotonic()
        try:
            return run()
        finally:
            self._retrieval_seconds_used += monotonic() - started_at

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
        # A proposal that fails validation can never execute, so pausing the
        # turn for user confirmation would be a guaranteed dead end (bead 3cq
        # follow-up: the live BYOK model omitted `.output answer` and the user
        # approved a program that could only re-fail). Return the rejection as
        # an ordinary tool result instead -- the harness feeds it back to the
        # model, which revises and re-proposes within the same turn. Only
        # safe_to_confirm proposals reach the user.
        if validation.get("status") == "rejected":
            diagnostics = list(validation.get("diagnostics", []))
            reasons = "; ".join(
                str(item.get("message", ""))
                for item in diagnostics
                if isinstance(item, dict)
            )
            return {
                "status": "rejected",
                "code": "tool.proposal_rejected",
                "tool_name": "propose_temporary_datalog",
                "executed": False,
                "validation": validation,
                "diagnostics": diagnostics,
                "message": (
                    f"Temporary Datalog proposal rejected: {reasons} "
                    "Revise the program and call propose_temporary_datalog "
                    "again. Authoring contract: "
                    + self._temporary_datalog_contract_description()
                ),
                "matches": [],
                "reachable": [],
            }
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
                "interpretation": formal_restatement,
                "exact_datalog": generated_datalog,
                "effect": TEMPORARY_DATALOG_EFFECT,
                "scope": self._temporary_datalog_scope(resolved_identity_ids),
                "assumptions": TEMPORARY_DATALOG_ASSUMPTIONS,
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

    def _temporary_datalog_scope(
        self, resolved_identity_ids: list[str]
    ) -> dict[str, object]:
        return {
            "starting_object_ids": resolved_identity_ids,
            "graph": str(self._topology.get("source_id") or self._session_id),
            "direction": "undirected traversal (structural connectivity, not flow direction)",
            "direction_basis": "structural adjacency; explicit flow direction is not applied",
            "path_treatment": (
                "breadth-first reachability up to 6 hops; each object visited at most once"
            ),
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
        # Predicates the program itself defines (rule heads and literal facts)
        # are legitimate intermediates -- e.g. pump / pump_with_check_valve for
        # "do all pumps have a check valve?" (bead 3cq). Only reading a
        # relation that is neither engine-supplied nor locally defined is
        # unapproved; local heads can only derive from approved inputs.
        predicate_names = []
        defined_predicates: set[str] = set()
        for line in stripped.splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("."):
                continue
            predicate_names.extend(
                re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", candidate)
            )
            head = candidate.split(":-", 1)[0]
            head_names = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", head)
            if head_names:
                defined_predicates.add(head_names[0])
        approved_predicates = self._temporary_datalog_approved_predicates()
        unapproved_predicates = sorted(
            {
                predicate
                for predicate in predicate_names
                if predicate not in approved_predicates
                and predicate not in defined_predicates
            }
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
            line.strip()
            for line in stripped.splitlines()
            if line.strip().startswith(".output")
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

    def _temporary_datalog_approved_predicates(self) -> set[str]:
        return {"answer"} | self._temporary_datalog_schema_predicates()

    def _temporary_datalog_schema_predicates(self) -> set[str]:
        schema_text = (
            build_graph_facts_datalog(self._graph_facts)
            + "\n"
            + load_graph_topology_idb()
            + "\n"
            + "\n".join(self._loaded_rule_pack_programs())
        )
        return self._declared_predicates(schema_text)

    def _temporary_datalog_contract_description(self) -> str:
        predicates = sorted(self._temporary_datalog_schema_predicates())
        predicate_list = ", ".join(f"`{predicate}`" for predicate in predicates)
        return (
            "declare `.decl answer(x:symbol)` and output exactly `.output answer`; "
            "rules may define `answer` plus program-local helper predicates "
            "(declare each helper with its own `.decl`; output only `answer`), "
            f"and may read only helpers or these engine-supplied predicates: {predicate_list}. "
            "Do not redeclare or define engine-supplied predicates. "
            "`reachable(source, target)` is the schema's topology reachability relation."
        )

    def _loaded_rule_pack_programs(self) -> list[str]:
        programs: list[str] = []
        for pack_id in self._loaded_rule_pack_ids:
            pack = pack_metadata(pack_id)
            for rule in pack["rules"]:
                executable_logic = rule.get("executable_logic", {})
                content = (
                    executable_logic.get("content")
                    if isinstance(executable_logic, dict)
                    else None
                )
                if isinstance(content, str):
                    programs.append(self._strip_souffle_outputs(content))
        return programs

    @staticmethod
    def _declared_predicates(program_text: str) -> set[str]:
        return {
            match.group(1)
            for match in re.finditer(
                r"(?m)^\s*\.decl\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                program_text,
            )
        }

    @staticmethod
    def _strip_souffle_outputs(program_text: str) -> str:
        return "\n".join(
            line
            for line in program_text.splitlines()
            if not line.strip().startswith(".output")
        )

    def _temporary_datalog_answer_ids(self, generated_datalog: str) -> list[str]:
        """Execute a validated temporary Datalog program on real Souffle.

        The program runs against the same graph facts and topology-semantics
        schema used by rule packs, plus read-only IDB predicates from the
        currently loaded rule packs. Raises SouffleExecutionError on any engine
        failure so callers surface an explicit error instead of a silent
        empty result.
        """
        program = self._temporary_datalog_program(generated_datalog)
        relations = run_souffle_program(program)
        matched_ids: list[str] = []
        for row in relations.get("answer", []):
            if not row:
                continue
            value = row[0]
            if value not in matched_ids:
                matched_ids.append(value)
        return matched_ids

    def _temporary_datalog_program(self, generated_datalog: str) -> str:
        return self._deduplicate_souffle_declarations(
            "\n".join(
                [
                    build_graph_facts_datalog(self._graph_facts),
                    load_graph_topology_idb(),
                    *self._loaded_rule_pack_programs(),
                    generated_datalog,
                ]
            )
        )

    @staticmethod
    def _deduplicate_souffle_declarations(program_text: str) -> str:
        seen: set[str] = set()
        lines: list[str] = []
        for line in program_text.splitlines():
            match = re.match(r"\s*\.decl\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if match:
                predicate = match.group(1)
                if predicate in seen:
                    continue
                seen.add(predicate)
            lines.append(line)
        return "\n".join(lines) + "\n"

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
        if (
            not isinstance(validation, dict)
            or validation.get("status") != "safe_to_confirm"
        ):
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
        try:
            matched_ids = self._temporary_datalog_answer_ids(generated_datalog)
        except SouffleExecutionError as error:
            diagnostic: dict[str, object] = {
                "code": f"temporary_datalog.{error.code}",
                "message": str(error),
            }
            if error.detail:
                diagnostic["detail"] = error.detail
            return {
                "status": "execution_failed",
                "executed": False,
                "confirmation": confirmation,
                "diagnostics": [diagnostic],
            }
        evidence_ids = self._temporary_answer_evidence_ids(matched_ids)
        evidence_items = [
            {
                "id": evidence_id,
                "label": self._node_label(evidence_id),
                "source": "temporary_datalog",
                "topology_evidence": self._evidence_map[evidence_id],
            }
            for evidence_id in evidence_ids
            if evidence_id in self._evidence_map
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

    def _temporary_answer_evidence_ids(self, answer_ids: list[str]) -> list[str]:
        evidence_ids: list[str] = []
        for answer_id in answer_ids:
            evidence_id = self._evidence_id_for_temporary_answer(answer_id)
            if evidence_id is not None and evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
        return evidence_ids

    def _evidence_id_for_temporary_answer(self, answer_id: str) -> str | None:
        if answer_id in self._evidence_map:
            return answer_id
        for node in self._nodes:
            if str(node.get("source_graph_node_id") or "") == answer_id:
                return str(node.get("id"))
        return None

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

    def _find_equipment(
        self, pattern: str, *, claim_type: str, evidence_role: str
    ) -> dict[str, object]:
        normalized = pattern.lower()
        matches = []
        examined_nodes = self._nodes[: self._retrieval_budgets.max_rows]
        for index, node in enumerate(examined_nodes):
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
                            "label": display_name
                            or tag_name
                            or raw_label
                            or str(node["id"]),
                            "node_class": class_name or raw_label,
                            "category": category,
                            "description": str(node.get("description") or ""),
                            "source_id": self._session_id,
                        },
                    )
                )
        matches.sort(key=lambda item: (item[0], item[1]))
        ordered = [entry for _, _, entry in matches]
        total = len(self._nodes)
        total_matches = sum(
            1
            for node in self._nodes
            if not normalized
            or normalized
            in " ".join(
                str(node.get(key) or "")
                for key in (
                    "display_name",
                    "class_name",
                    "label",
                    "tag_name",
                    "category",
                )
            ).lower()
        )
        result_limit = min(
            self.MAX_FIND_RESULTS,
            self._retrieval_budgets.max_rows,
            self._retrieval_budgets.max_evidence_objects,
        )
        bounded = ordered[:result_limit]
        limitations = []
        if len(self._nodes) > self._retrieval_budgets.max_rows:
            limitations.append(
                {
                    "code": "retrieval.row_limit",
                    "message": "Retrieval stopped at the configured row limit.",
                    "limit": self._retrieval_budgets.max_rows,
                }
            )
        elif total_matches > result_limit:
            limitations.append(self._limitation("row_limit", result_limit))
        if len(ordered) > self._retrieval_budgets.max_evidence_objects:
            limitations.append(
                {
                    "code": "retrieval.evidence_object_limit",
                    "message": "Retrieval stopped at the configured evidence-object limit.",
                    "limit": self._retrieval_budgets.max_evidence_objects,
                }
            )
        complete = (
            not limitations
            and len(examined_nodes) == len(self._nodes)
            and len(ordered) == len(bounded)
        )
        if self._payload_too_large(bounded):
            bounded = []
            complete = False
            limitations.insert(
                0,
                self._limitation(
                    "payload_size_limit", self._retrieval_budgets.max_payload_bytes
                ),
            )
        outcome = self._claim_outcome(
            claim_type=claim_type,
            has_evidence=bool(bounded),
            complete=complete,
            evidence_role=evidence_role,
        )
        return {
            "matches": bounded,
            "count": len(bounded),
            "total_matches": total_matches,
            "truncated": not complete,
            "outcome": outcome,
            "coverage": {
                "complete": complete,
                "examined_rows": len(examined_nodes),
                "total_rows": total,
                "returned_evidence_objects": len(bounded),
            },
            "limitations": limitations,
        }

    def _get_reachable_equipment(
        self, equipment_id: str, max_hops: int, *, claim_type: str
    ) -> dict[str, object]:
        result = self._interpretation.reachable_from(
            equipment_id,
            max_hops=max_hops,
            result_limit=self._retrieval_budgets.max_paths,
        )
        if result.error is not None:
            return {
                "error": result.error,
                "source_id": equipment_id,
                "reachable": [],
            }

        eligible = [
            item
            for item in result.reachable
            if len(item.witness.topology_edge_ids)
            <= self._retrieval_budgets.max_path_length
        ]
        evidence_limit = min(
            self._retrieval_budgets.max_paths,
            self._retrieval_budgets.max_rows,
            self._retrieval_budgets.max_evidence_objects,
        )
        eligible = eligible[:evidence_limit]
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
            for item in eligible
        ]
        limitations = []
        if result.truncated:
            limitations.append(
                self._limitation("path_limit", self._retrieval_budgets.max_paths)
            )
        if any(
            len(item.witness.topology_edge_ids)
            > self._retrieval_budgets.max_path_length
            for item in result.reachable
        ) or (self._retrieval_budgets.max_path_length < max_hops and result.truncated):
            limitations.append(
                self._limitation(
                    "path_length_limit", self._retrieval_budgets.max_path_length
                )
            )
        complete = not limitations and not result.truncated
        if self._payload_too_large(reachable):
            reachable = []
            complete = False
            limitations.insert(
                0,
                self._limitation(
                    "payload_size_limit", self._retrieval_budgets.max_payload_bytes
                ),
            )
        response: dict[str, object] = {
            "source_id": equipment_id,
            "reachable": reachable,
            "outcome": self._claim_outcome(
                claim_type=claim_type,
                has_evidence=bool(reachable),
                complete=complete,
                evidence_role="witness",
            ),
            "coverage": {
                "complete": complete,
                "examined_paths": len(result.reachable),
                "returned_paths": len(reachable),
                "returned_evidence_objects": len(reachable),
            },
            "limitations": limitations,
        }
        if result.truncated:
            response["truncated"] = True
        return response

    def _operation_budget_rejection(self) -> dict[str, object] | None:
        if self._retrieval_steps >= self._retrieval_budgets.max_steps:
            return self._limited_result("step_limit", self._retrieval_budgets.max_steps)
        if self._retrieval_seconds_used >= self._retrieval_budgets.max_seconds:
            return self._limited_result(
                "time_limit", self._retrieval_budgets.max_seconds
            )
        return None

    def _limited_result(self, name: str, limit: int | float) -> dict[str, object]:
        return {
            "outcome": "indeterminate",
            "matches": [],
            "reachable": [],
            "coverage": {"complete": False, "returned_evidence_objects": 0},
            "limitations": [self._limitation(name, limit)],
        }

    @staticmethod
    def _limitation(name: str, limit: int | float) -> dict[str, object]:
        return {
            "code": f"retrieval.{name}",
            "message": f"Retrieval stopped at the configured {name.replace('_', ' ')}.",
            "limit": limit,
        }

    def _payload_too_large(self, evidence: object) -> bool:
        import json

        return (
            len(json.dumps(evidence, separators=(",", ":")).encode("utf-8"))
            > self._retrieval_budgets.max_payload_bytes
        )

    @staticmethod
    def _claim_outcome(
        *, claim_type: str, has_evidence: bool, complete: bool, evidence_role: str
    ) -> str:
        if claim_type == "absence":
            return (
                "violated"
                if has_evidence
                else ("satisfied" if complete else "indeterminate")
            )
        if claim_type == "universal":
            if has_evidence and evidence_role == "counterexample":
                return "violated"
            return "satisfied" if complete else "indeterminate"
        if claim_type in {"existential", "counterexample", "explanation"}:
            return (
                "satisfied"
                if has_evidence
                else ("violated" if complete else "indeterminate")
            )
        return "indeterminate"

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
                    "tagName": str(
                        node.get("tag_name") or node.get("display_name") or ""
                    ),
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
