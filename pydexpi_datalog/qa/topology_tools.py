from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from pydexpi_datalog.qa.capability_manifest import (
    PERMISSION_ALLOWED_READ_ONLY,
    PERMISSION_CONFIRMATION_REQUIRED,
    PERMISSION_DENIED,
    default_grounded_qa_manifest,
)
from pydexpi_datalog.qa.counterfactual_probes import (
    run_mandatory_counterfactual_probes,
)
from pydexpi_datalog.qa.faithfulness_gate import (
    evaluate_layered_faithfulness_gate,
)
from pydexpi_datalog.qa.route_receipts import (
    ROUTE_DEONTIC_ABSTENTION,
    ROUTE_GENERATED_QUERY_AUTHORIZED,
    ROUTE_TEMPLATE_NO_FIT,
    RouteReceiptAuthority,
    is_deontic_or_defeasible_request,
    source_snapshot_identity,
)
from pydexpi_datalog.qa.structured_intent import (
    compare_program_structured_intent,
    compare_structured_intents,
    encode_structured_intent_program,
    normalize_structured_intent,
)
from pydexpi_datalog.qa.trusted_templates import (
    TRUSTED_TEMPLATE_CATALOG_VERSION,
    execute_bundled_query_template,
)
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
from pydexpi_datalog.verification.pack_skill_context import render_skill_context_prompt

MANDATORY_TEMPORARY_DATALOG_VALIDATORS = (
    "mechanical_safety",
    "counterfactual_probes",
    "layered_faithfulness_gate",
)


class AutomaticExecutionUnavailableError(RuntimeError):
    """Raised when automatic temporary Datalog cannot be activated safely."""


@dataclass(frozen=True)
class TemporaryDatalogValidatorBundle:
    """Mandatory validators required to activate automatic temporary Datalog."""

    mechanical_safety: Callable[..., dict[str, object]] | None
    counterfactual_probes: Callable[..., dict[str, object]] | None
    layered_faithfulness_gate: Callable[..., dict[str, object]] | None

    @classmethod
    def production(cls) -> TemporaryDatalogValidatorBundle:
        return cls(
            mechanical_safety=_production_mechanical_safety_marker,
            counterfactual_probes=run_mandatory_counterfactual_probes,
            layered_faithfulness_gate=evaluate_layered_faithfulness_gate,
        )

    def unavailable_names(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.mechanical_safety is None:
            missing.append("mechanical_safety")
        if self.counterfactual_probes is None:
            missing.append("counterfactual_probes")
        if self.layered_faithfulness_gate is None:
            missing.append("layered_faithfulness_gate")
        return tuple(missing)


def _production_mechanical_safety_marker(**_kwargs: object) -> dict[str, object]:
    """Sentinel proving the mechanical-safety validator seam is wired.

    TopologyTools owns the concrete mechanical check; this marker exists so
    automatic mode can refuse activation when that seam is explicitly unset.
    """
    return {"status": "available"}


# Reviewer-facing consent context for temporary Datalog proposals. The effect
# statement is hardcoded — never model-generated — because the executor is
# strictly read-only. The assumptions describe what the traversal actually
# does: undirected breadth-first reachability over topology-attribute edges.
TEMPORARY_DATALOG_EFFECT = (
    "Read-only analysis. Does not modify the source document, graph, annotations, or rule pack."
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
        attached_pack_skill_context: list[dict[str, object]] | None = None,
        validators: TemporaryDatalogValidatorBundle | None = None,
    ) -> None:
        self._topology = topology_view
        self._session_id = session_id
        self._retrieval_budgets = retrieval_budgets or RetrievalBudgets()
        # Released hybrid workflow always auto-executes validated temporary
        # Datalog. Activation is refused when any mandatory safety or
        # faithfulness validator is unavailable (3qo.9.9).
        self._validators = validators or TemporaryDatalogValidatorBundle.production()
        self._ensure_automatic_execution_available(self._validators)
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
        self._route_receipts = RouteReceiptAuthority()
        self._active_question = ""
        self._active_structured_intent: dict[str, object] | None = None
        self._faithfulness_probe_attempts: list[dict[str, object]] = []
        self._faithfulness_gate_attempts: list[dict[str, object]] = []
        self._loaded_rule_pack_ids = tuple(
            sorted(str(pack_id) for pack_id in (loaded_rule_pack_ids or ()))
        )
        self._attached_pack_skill_context = list(attached_pack_skill_context or [])
        self._capability_manifest = default_grounded_qa_manifest(
            temporary_datalog_contract=self._temporary_datalog_contract_description()
        )
        self._interpretation = TopologyInterpretation(
            graph_facts=self._graph_facts,
            topology_view=self._topology_with_source_graph_ids(),
            session_id=session_id,
            source_id=str(topology_view.get("source_id") or session_id),
        )

    @staticmethod
    def _ensure_automatic_execution_available(
        validators: TemporaryDatalogValidatorBundle,
    ) -> None:
        missing = validators.unavailable_names()
        if missing:
            raise AutomaticExecutionUnavailableError(
                "Automatic temporary Datalog execution requires every mandatory "
                f"safety and faithfulness validator; unavailable: {', '.join(missing)}."
            )

    def begin_request(
        self,
        question: str,
        *,
        resume_route_receipt: dict[str, object] | None = None,
    ) -> None:
        self._active_question = question
        self._active_structured_intent = None
        self._faithfulness_probe_attempts = []
        self._faithfulness_gate_attempts = []
        self._route_receipts.begin_request(
            intent=question,
            source_snapshot_id=source_snapshot_identity(self._graph_facts),
            template_catalog_version=TRUSTED_TEMPLATE_CATALOG_VERSION,
            resume_receipt=resume_route_receipt,
        )
        self._active_structured_intent = self._route_receipts.active_structured_intent()

    def record_backend_route_outcome(
        self,
        outcome: str,
        *,
        structured_intent: dict[str, object] | None = None,
    ) -> dict[str, object]:
        result = self._route_receipts.record_backend_outcome(
            outcome,
            structured_intent=structured_intent,
        )
        self._active_structured_intent = self._route_receipts.active_structured_intent()
        return result

    @staticmethod
    def policy_route_outcome(question: str) -> str | None:
        if is_deontic_or_defeasible_request(question):
            return ROUTE_DEONTIC_ABSTENTION
        return None

    def tool_definitions(self) -> list[dict[str, object]]:
        policy_outcome = self.policy_route_outcome(self._active_question)
        definitions = self._capability_manifest.provider_tool_definitions()
        if policy_outcome is not None:
            return [
                definition
                for definition in definitions
                if definition["function"]["name"]
                not in {
                    "execute_bundled_query_template",
                    "report_template_no_fit",
                    "propose_temporary_datalog",
                }
            ]
        # Generated Datalog is always offered (except deontic policy above).
        # Authorization binds to the session question + structured intent, not
        # to a prior no-fit ceremony or a paraphrased model request (bead 2669).
        return definitions

    def system_prompt(self) -> str:
        """Model-facing system prompt derived from the capability manifest."""
        prompt = self._capability_manifest.system_prompt()
        skill_prompt = render_skill_context_prompt(self._attached_pack_skill_context)
        if not skill_prompt:
            return prompt
        return f"{prompt}\n\n{skill_prompt}"

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
        policy_outcome = self.policy_route_outcome(self._active_question)
        if policy_outcome is not None and tool_name in {
            "execute_bundled_query_template",
            "report_template_no_fit",
            "propose_temporary_datalog",
        }:
            result = self.record_backend_route_outcome(policy_outcome)
            return {
                **result,
                "status": "policy_abstention",
                "tool_name": tool_name,
                "executed": False,
                "message": (
                    "Permission and defeasible-exception questions require "
                    "abstention or human review."
                ),
            }
        if capability.permission_class == PERMISSION_DENIED:
            return self._tool_rejection(
                tool_name=tool_name,
                code="tool.denied",
                message=capability.denied_reason or f"denied tool: {tool_name}",
            )
        if capability.permission_class == PERMISSION_CONFIRMATION_REQUIRED:
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
        if tool_name == "report_template_no_fit":
            return self._report_template_no_fit(tool_input)
        if tool_name == "propose_temporary_datalog":
            return self._propose_temporary_datalog_with_route_receipt(tool_input)
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
        if tool_name == "census_outgoing_edge_cardinality":
            return self._timed_retrieval(
                lambda: self._census_outgoing_edge_cardinality(tool_input)
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

    def _report_template_no_fit(
        self, tool_input: dict[str, object]
    ) -> dict[str, object]:
        reason = str(tool_input.get("reason", "")).strip()
        if not reason:
            return self._tool_rejection(
                tool_name="report_template_no_fit",
                code="route.no_fit_reason_required",
                message="Template no-fit reporting requires a reason.",
            )
        raw_structured_intent = tool_input.get("structured_intent")
        if raw_structured_intent is None:
            return {
                **self._tool_rejection(
                    tool_name="report_template_no_fit",
                    code="route.structured_intent_required",
                    message=(
                        "Template no-fit reporting requires structured logic intent."
                    ),
                ),
                "diagnostics": [
                    {
                        "code": "structured_intent.required",
                        "field": "structured_intent",
                        "message": (
                            "Supply requested classes, roles, scope, direction, "
                            "quantifier, polarity, and output obligations."
                        ),
                    }
                ],
            }
        if raw_structured_intent is not None:
            structured_intent, diagnostics = normalize_structured_intent(
                raw_structured_intent
            )
            if diagnostics or structured_intent is None:
                return {
                    **self._tool_rejection(
                        tool_name="report_template_no_fit",
                        code="route.structured_intent_invalid",
                        message="Template no-fit structured intent is invalid.",
                    ),
                    "diagnostics": diagnostics,
                }
            if (
                self._active_structured_intent is not None
                and structured_intent != self._active_structured_intent
            ):
                _, changed_diagnostics = compare_structured_intents(
                    self._active_structured_intent,
                    structured_intent,
                )
                return {
                    **self._tool_rejection(
                        tool_name="report_template_no_fit",
                        code="route.structured_intent_changed",
                        message=(
                            "Structured intent is already fixed for this request "
                            "and cannot be changed."
                        ),
                    ),
                    "diagnostics": changed_diagnostics,
                }
            self._active_structured_intent = structured_intent
        return {
            **self.record_backend_route_outcome(
                ROUTE_TEMPLATE_NO_FIT,
                structured_intent=self._active_structured_intent,
            ),
            "reason": reason,
            "structured_intent": self._active_structured_intent,
        }

    def _propose_temporary_datalog_with_route_receipt(
        self, tool_input: dict[str, object]
    ) -> dict[str, object]:
        # Ignore model-authored receipt blobs; authorization is backend-owned.
        authorization = self._authorize_generated_query_for_session(tool_input)
        if authorization is not None:
            return authorization
        route_receipt = self._route_receipts.active_receipt()
        # Bind to the session question, not a paraphrased model `request`
        # field — live models routinely rewrite the request string (bead 2669).
        session_question = self._active_question or ""
        if route_receipt is None or not self._route_receipts.matches_active_intent(
            session_question
        ):
            return {
                "status": "rejected",
                "code": "route.valid_receipt_required",
                "tool_name": "propose_temporary_datalog",
                "executed": False,
                "message": (
                    "Generated Datalog requires a backend-issued route receipt "
                    "for this exact request and environment."
                ),
                "matches": [],
                "reachable": [],
            }
        result = self._propose_temporary_datalog(tool_input)
        result["route_receipt"] = route_receipt
        return result

    def _authorize_generated_query_for_session(
        self, tool_input: dict[str, object]
    ) -> dict[str, object] | None:
        """Ensure a session-bound receipt + structured intent exist.

        Returns a rejection dict when authorization cannot proceed; None when
        the active receipt is ready for proposal validation/execution.
        """
        session_question = self._active_question or ""
        active = self._route_receipts.active_receipt()
        if active is not None and self._route_receipts.matches_active_intent(
            session_question
        ):
            if self._active_structured_intent is None:
                restored = self._route_receipts.active_structured_intent()
                if restored is not None:
                    self._active_structured_intent = restored
            if self._active_structured_intent is not None:
                return None

        structured_intent = self._structured_intent_from_proposal(tool_input)
        if structured_intent is None:
            return {
                "status": "rejected",
                "code": "route.structured_intent_required",
                "tool_name": "propose_temporary_datalog",
                "executed": False,
                "message": (
                    "Generated Datalog requires structured logic intent "
                    "(via faithfulness_review.back_translated_intent or a prior "
                    "template no-fit receipt)."
                ),
                "matches": [],
                "reachable": [],
                "diagnostics": [
                    {
                        "code": "structured_intent.required",
                        "field": "structured_intent",
                        "message": (
                            "Supply requested classes, roles, scope, direction, "
                            "quantifier, polarity, and output obligations."
                        ),
                    }
                ],
            }

        if (
            self._active_structured_intent is not None
            and structured_intent != self._active_structured_intent
        ):
            _, changed_diagnostics = compare_structured_intents(
                self._active_structured_intent,
                structured_intent,
            )
            return {
                "status": "rejected",
                "code": "route.structured_intent_changed",
                "tool_name": "propose_temporary_datalog",
                "executed": False,
                "message": (
                    "Structured intent is already fixed for this request "
                    "and cannot be changed."
                ),
                "matches": [],
                "reachable": [],
                "diagnostics": changed_diagnostics,
            }

        self._active_structured_intent = structured_intent
        issued = self.record_backend_route_outcome(
            ROUTE_GENERATED_QUERY_AUTHORIZED,
            structured_intent=structured_intent,
        )
        if issued.get("status") != "route_receipt_issued":
            return {
                "status": "rejected",
                "code": "route.valid_receipt_required",
                "tool_name": "propose_temporary_datalog",
                "executed": False,
                "message": (
                    "Generated Datalog could not obtain a backend route receipt "
                    "for this session question."
                ),
                "matches": [],
                "reachable": [],
                "diagnostics": issued.get("diagnostics", []),
            }
        return None

    def _structured_intent_from_proposal(
        self, tool_input: dict[str, object]
    ) -> dict[str, object] | None:
        raw = tool_input.get("structured_intent")
        if raw is None:
            review = tool_input.get("faithfulness_review")
            if isinstance(review, dict):
                raw = review.get("back_translated_intent")
        if raw is None and self._active_structured_intent is not None:
            return dict(self._active_structured_intent)
        if raw is None:
            return None
        structured_intent, diagnostics = normalize_structured_intent(raw)
        if diagnostics or structured_intent is None:
            return None
        return structured_intent

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
        model_review = tool_input.get("faithfulness_review")
        raw_resolved_identity_ids = tool_input.get("resolved_identity_ids")
        resolved_identity_ids = (
            [
                identity
                for identity in raw_resolved_identity_ids
                if isinstance(identity, str)
            ]
            if isinstance(raw_resolved_identity_ids, list)
            else []
        )
        mechanical_validation = self._validate_temporary_datalog(
            generated_datalog=generated_datalog,
            formal_restatement=formal_restatement,
        )
        validation = mechanical_validation
        encoded_intent: dict[str, object] | None = None
        semantic_diagnostics: list[dict[str, object]]
        if self._active_structured_intent is None:
            semantic_diagnostics = [
                {
                    "code": "structured_intent.required",
                    "field": "structured_intent",
                    "message": (
                        "Generated query execution requires backend-bound "
                        "structured intent."
                    ),
                }
            ]
        else:
            encoded_intent, semantic_diagnostics = compare_program_structured_intent(
                self._active_structured_intent,
                generated_datalog,
            )
        if semantic_diagnostics:
            raw_validation_diagnostics = validation.get("diagnostics")
            validation_diagnostics = (
                [
                    dict(item)
                    for item in raw_validation_diagnostics
                    if isinstance(item, dict)
                ]
                if isinstance(raw_validation_diagnostics, list)
                else []
            )
            diagnostics = [*validation_diagnostics, *semantic_diagnostics]
            validation = {
                **validation,
                "status": "rejected",
                "diagnostics": diagnostics,
            }

        program_id = hashlib.sha256(generated_datalog.encode("utf-8")).hexdigest()
        if mechanical_validation.get("status") == "safe_to_confirm":
            counterfactual = self._validators.counterfactual_probes
            if counterfactual is None:
                raise AutomaticExecutionUnavailableError(
                    "Automatic temporary Datalog execution requires every mandatory "
                    "safety and faithfulness validator; unavailable: counterfactual_probes."
                )
            counterfactual_validation = counterfactual(
                generated_datalog,
                self._active_structured_intent or {},
            )
        else:
            counterfactual_validation = {
                "status": "not_applicable",
                "probes": [],
                "diagnostics": [],
                "reason": "mechanical_validation_failed",
            }
        probe_attempt = {
            "program_id": program_id,
            "generated_datalog": generated_datalog,
            **counterfactual_validation,
        }
        self._faithfulness_probe_attempts.append(probe_attempt)
        faithfulness = self._validators.layered_faithfulness_gate
        if faithfulness is None:
            raise AutomaticExecutionUnavailableError(
                "Automatic temporary Datalog execution requires every mandatory "
                "safety and faithfulness validator; unavailable: layered_faithfulness_gate."
            )
        faithfulness_gate = faithfulness(
            mechanical_validation=mechanical_validation,
            requested_intent=self._active_structured_intent,
            encoded_intent=encoded_intent,
            semantic_diagnostics=semantic_diagnostics,
            counterfactual_validation=counterfactual_validation,
            model_review=model_review,
        )
        self._faithfulness_gate_attempts.append(
            {
                "program_id": program_id,
                "generated_datalog": generated_datalog,
                **faithfulness_gate,
            }
        )
        if validation.get("status") == "rejected":
            raw_diagnostics = validation.get("diagnostics")
            diagnostics = (
                [dict(item) for item in raw_diagnostics if isinstance(item, dict)]
                if isinstance(raw_diagnostics, list)
                else []
            )
            reasons = "; ".join(
                str(item.get("message", ""))
                for item in diagnostics
                if isinstance(item, dict)
            )
            return self._reject_temporary_proposal(
                code="tool.proposal_rejected",
                message=(
                    f"Temporary Datalog proposal rejected: {reasons} "
                    "Revise the program and call propose_temporary_datalog "
                    "again. Authoring contract: "
                    + self._temporary_datalog_contract_description()
                ),
                diagnostics=diagnostics,
                validation=validation,
                counterfactual_validation=counterfactual_validation,
                faithfulness_gate=faithfulness_gate,
                probe_attempt=probe_attempt,
            )

        if counterfactual_validation.get("status") not in {
            "passed",
            "not_applicable",
        }:
            raw_diagnostics = counterfactual_validation.get("diagnostics")
            diagnostics = (
                list(raw_diagnostics)
                if isinstance(raw_diagnostics, list)
                else [
                    {
                        "code": "faithfulness.counterfactual_invalid_result",
                        "message": (
                            "Counterfactual replay returned no usable diagnostics."
                        ),
                    }
                ]
            )
            reasons = "; ".join(
                str(item.get("message", ""))
                for item in diagnostics
                if isinstance(item, dict)
            )
            return self._reject_temporary_proposal(
                code="faithfulness.counterfactual_failed",
                message=(
                    f"Mandatory counterfactual replay failed: {reasons} "
                    "Revise the program and call propose_temporary_datalog again."
                ),
                diagnostics=diagnostics,
                validation=validation,
                counterfactual_validation=counterfactual_validation,
                faithfulness_gate=faithfulness_gate,
                probe_attempt=probe_attempt,
            )
        if faithfulness_gate["status"] != "passed":
            diagnostics = list(
                faithfulness_gate["layers"]["model_review"]["diagnostics"]  # type: ignore[index]
            )
            reasons = "; ".join(
                str(item.get("message", ""))
                for item in diagnostics
                if isinstance(item, dict)
            )
            return self._reject_temporary_proposal(
                code="faithfulness.model_veto",
                message=(
                    f"Layered faithfulness gate rejected the model review: {reasons} "
                    "Revise the program and its back-translation, then call "
                    "propose_temporary_datalog again."
                ),
                diagnostics=diagnostics,
                validation=validation,
                counterfactual_validation=counterfactual_validation,
                faithfulness_gate=faithfulness_gate,
                probe_attempt=probe_attempt,
            )

        proposal_id = self._temporary_datalog_proposal_id(
            request=request,
            generated_datalog=generated_datalog,
            formal_restatement=formal_restatement,
        )
        return self._execute_automatic_temporary_datalog(
            request=request,
            generated_datalog=generated_datalog,
            formal_restatement=formal_restatement,
            resolved_identity_ids=resolved_identity_ids,
            proposal_id=proposal_id,
            program_id=program_id,
            validation=validation,
            counterfactual_validation=counterfactual_validation,
            faithfulness_gate=faithfulness_gate,
        )

    def _reject_temporary_proposal(
        self,
        *,
        code: str,
        message: str,
        diagnostics: list[dict[str, object]],
        validation: dict[str, object],
        counterfactual_validation: dict[str, object],
        faithfulness_gate: dict[str, object],
        probe_attempt: dict[str, object],
    ) -> dict[str, object]:
        """Fail closed on a proposal while returning a machine-usable repair kit."""
        return {
            "status": "rejected",
            "code": code,
            "tool_name": "propose_temporary_datalog",
            "executed": False,
            "validation": validation,
            "counterfactual_validation": counterfactual_validation,
            "faithfulness_gate": faithfulness_gate,
            "faithfulness_probe_attempts": [probe_attempt],
            "faithfulness_gate_attempts": [self._faithfulness_gate_attempts[-1]],
            "diagnostics": diagnostics,
            "authoring_scaffold": self._authoring_scaffold(diagnostics),
            "message": message,
            "matches": [],
            "reachable": [],
        }

    def _authoring_scaffold(
        self, diagnostics: list[dict[str, object]]
    ) -> dict[str, object]:
        """Backend-owned repair kit for the next propose_temporary_datalog call."""
        approved = sorted(self._temporary_datalog_approved_predicates())
        stub = (
            ".decl answer(x:symbol)\n"
            ".output answer\n"
            'answer(x) :- node_attribute(x, "label", "__AUTHORING_STUB__").\n'
        )
        intent = self._active_structured_intent
        if intent is not None:
            try:
                skeleton = encode_structured_intent_program(stub, intent)
            except ValueError:
                skeleton = stub
        else:
            skeleton = stub
        diagnostic_codes = [
            str(item.get("code"))
            for item in diagnostics
            if isinstance(item, dict) and item.get("code")
        ]
        return {
            "approved_predicates": approved,
            "program_skeleton": skeleton,
            "diagnostic_codes": diagnostic_codes,
            "instructions": (
                "Revise generated_datalog by editing only the answer-rule body of "
                "program_skeleton. Keep `.decl answer(x:symbol)`, `.output answer`, "
                "and every query_intent_contract guard unchanged. Use only "
                "approved_predicates (plus program-local helpers you declare). "
                "Do not invent schema predicates. Then call propose_temporary_datalog "
                "again with the revised program and the same structured intent."
            ),
            "examples": [
                {
                    "shape": "cardinality_or_ownership",
                    "hint": (
                        "Universal ownership/cardinality: find sources missing the "
                        "required relation; return those source evidence IDs as answer."
                    ),
                },
                {
                    "shape": "reachability",
                    "hint": (
                        "Reachability: use engine-supplied reachable(source, target) "
                        "or piping connectivity predicates from approved_predicates."
                    ),
                },
            ],
            "contract": self._temporary_datalog_contract_description(),
        }

    def _execute_automatic_temporary_datalog(
        self,
        *,
        request: str,
        generated_datalog: str,
        formal_restatement: str,
        resolved_identity_ids: list[str],
        proposal_id: str,
        program_id: str,
        validation: dict[str, object],
        counterfactual_validation: dict[str, object],
        faithfulness_gate: dict[str, object],
    ) -> dict[str, object]:
        """Execute a gate-passing temporary proposal immediately.

        Reached only after mechanical safety validation, mandatory
        counterfactual replay, and the layered faithfulness gate have all
        passed on this exact program. The result never creates confirmation
        state; it discloses the executed pair after the fact and carries a
        minimal audit record. Generated logic stays temporary: nothing here
        grants reusable-rule trust or touches persistent promotion.
        """
        started = monotonic()
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
                "code": "temporary_datalog.engine_failure",
                "tool_name": "propose_temporary_datalog",
                "executed": False,
                "execution_mode": "automatic",
                "validation": validation,
                "counterfactual_validation": counterfactual_validation,
                "faithfulness_gate": faithfulness_gate,
                "diagnostics": [diagnostic],
                "message": (
                    "The generated program passed every gate but the engine "
                    "run failed. Repair the program using the diagnostics and "
                    "call propose_temporary_datalog again."
                ),
                "matches": [],
                "reachable": [],
            }
        latency_seconds = monotonic() - started
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
        gate_attempts = len(self._faithfulness_gate_attempts)
        failed_gate_attempts = sum(
            1
            for attempt in self._faithfulness_gate_attempts
            if attempt.get("status") != "passed"
        )
        source_scope = self._temporary_datalog_scope(resolved_identity_ids)
        deterministic_result = {
            "matched_object_ids": evidence_ids,
            "raw_answer_ids": matched_ids,
            "row_count": len(matched_ids),
        }
        disclosure = {
            "restatement": formal_restatement,
            "source_scope": source_scope,
            "route": "generated_temporary_datalog",
            "validation": validation,
            "counterfactual_validation": counterfactual_validation,
            "faithfulness_gate": faithfulness_gate,
            "inspectable_datalog": {
                "display": "collapsed",
                "generated_datalog": generated_datalog,
            },
            "deterministic_result": deterministic_result,
            "effect": TEMPORARY_DATALOG_EFFECT,
            "assumptions": TEMPORARY_DATALOG_ASSUMPTIONS,
        }
        route_artifact: dict[str, object] = {
            "route": "generated_temporary_datalog",
            "execution_mode": "automatic",
            "engine": "souffle",
            "program_id": program_id,
            "proposal_id": proposal_id,
            "request": request,
            "restatement": formal_restatement,
            "source_scope": source_scope,
            "validation": validation,
            "counterfactual_validation": counterfactual_validation,
            "faithfulness_gate": faithfulness_gate,
            "repair_summary": {
                "gate_attempts": gate_attempts,
                "failed_gate_attempts": failed_gate_attempts,
            },
            "logic_program": generated_datalog,
            "execution": {
                "latency_seconds": latency_seconds,
                "row_count": len(matched_ids),
            },
            "trust": {
                "temporary": True,
                "reusable_rule_trust": False,
                "promotion": "separate_explicit_authoring_action",
            },
        }
        audit_record = {
            "route": "generated_temporary_datalog",
            "decision": "automatic_execution",
            "proposal_id": proposal_id,
            "program_id": program_id,
            "session_id": self._session_id,
            "question": request,
            "formal_restatement": formal_restatement,
            "generated_datalog": generated_datalog,
            "validation": validation,
            "counterfactual_validation": counterfactual_validation,
            "faithfulness_gate": faithfulness_gate,
            "repair_summary": {
                "gate_attempts": gate_attempts,
                "failed_gate_attempts": failed_gate_attempts,
            },
            "evidence_ids": evidence_ids,
            "executed": True,
            "execution_status": "answered",
            "latency_seconds": latency_seconds,
        }
        trace_events = [
            {"event": "generated_proposed", "proposal_id": proposal_id},
            {
                "event": "generated_gates_passed",
                "validation": str(validation.get("status", "")),
                "counterfactual": str(counterfactual_validation.get("status", "")),
                "faithfulness_gate": str(faithfulness_gate.get("status", "")),
            },
            {
                "event": "generated_executed",
                "engine": "souffle",
                "execution_mode": "automatic",
            },
            {
                "event": "result_observed",
                "row_count": len(matched_ids),
                "evidence_count": len(evidence_ids),
            },
        ]
        return {
            "status": "answered",
            "code": "temporary_datalog.automatic_execution",
            "tool_name": "propose_temporary_datalog",
            "executed": True,
            "execution_mode": "automatic",
            "confirmation": {"required": False},
            "summary": {"text": formal_restatement},
            "disclosure": disclosure,
            "matched_object_ids": evidence_ids,
            "matches": evidence_items,
            "reachable": [],
            "evidence": {
                "display": "expandable",
                "items": evidence_items,
            },
            "validation": validation,
            "counterfactual_validation": counterfactual_validation,
            "faithfulness_gate": faithfulness_gate,
            "route_artifact": route_artifact,
            "audit_record": audit_record,
            "trace_events": trace_events,
            "diagnostics": [],
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

    def _census_outgoing_edge_cardinality(
        self, tool_input: dict[str, object]
    ) -> dict[str, object]:
        """Exhaustive outgoing-edge cardinality census for a source node class."""
        source_label = str(tool_input.get("source_node_label", "")).strip()
        edge_label = str(tool_input.get("edge_label", "")).strip()
        attr_name = str(tool_input.get("attr_name", "")).strip()
        expected_count = int(tool_input.get("expected_count", 1))
        if not source_label or not attr_name:
            return {
                "status": "rejected",
                "code": "census.invalid_bindings",
                "tool_name": "census_outgoing_edge_cardinality",
                "message": (
                    "census_outgoing_edge_cardinality requires source_node_label "
                    "and attr_name."
                ),
                "rows": [],
                "violators": [],
                "coverage": {"complete": False},
                "truncated": True,
            }

        sources = [
            node
            for node in self._nodes
            if source_label
            in {
                str(node.get("label") or ""),
                str(node.get("class_name") or ""),
            }
        ]
        examined = sources[: self._retrieval_budgets.max_rows]
        rows: list[dict[str, object]] = []
        violators: list[dict[str, object]] = []
        for node in examined:
            node_id = str(node["id"])
            matched_edges = [
                edge
                for edge in self._edges
                if str(edge.get("source_id")) == node_id
                and self._edge_matches_census(edge, edge_label=edge_label, attr_name=attr_name)
            ]
            count = len(matched_edges)
            row = {
                "evidence_id": node_id,
                "label": str(
                    node.get("display_name")
                    or node.get("tag_name")
                    or node.get("label")
                    or node_id
                ),
                "node_class": str(node.get("class_name") or node.get("label") or ""),
                "count": count,
                "expected_count": expected_count,
                "targets": [
                    {
                        "evidence_id": str(edge.get("target_id")),
                        "edge_id": str(edge.get("id") or ""),
                    }
                    for edge in matched_edges
                ],
            }
            rows.append(row)
            if count != expected_count:
                violators.append(row)

        result_limit = min(
            self._retrieval_budgets.max_rows,
            self._retrieval_budgets.max_evidence_objects,
        )
        bounded_rows = rows[:result_limit]
        bounded_violators = [
            row for row in violators if row["evidence_id"]
            in {item["evidence_id"] for item in bounded_rows}
        ]
        limitations: list[dict[str, object]] = []
        if len(sources) > self._retrieval_budgets.max_rows:
            limitations.append(
                {
                    "code": "retrieval.row_limit",
                    "message": "Census stopped at the configured row limit.",
                    "limit": self._retrieval_budgets.max_rows,
                }
            )
        if len(rows) > result_limit:
            limitations.append(
                {
                    "code": "retrieval.evidence_object_limit",
                    "message": "Census stopped at the configured evidence-object limit.",
                    "limit": self._retrieval_budgets.max_evidence_objects,
                }
            )
        complete = (
            not limitations
            and len(examined) == len(sources)
            and len(bounded_rows) == len(rows)
        )
        if self._payload_too_large(bounded_rows):
            bounded_rows = []
            bounded_violators = []
            complete = False
            limitations.insert(
                0,
                self._limitation(
                    "payload_size_limit", self._retrieval_budgets.max_payload_bytes
                ),
            )
        return {
            "status": "answered",
            "tool_name": "census_outgoing_edge_cardinality",
            "source_node_label": source_label,
            "edge_label": edge_label,
            "attr_name": attr_name,
            "expected_count": expected_count,
            "source_count": len(sources),
            "rows": bounded_rows,
            "violators": bounded_violators,
            "violator_ids": [str(row["evidence_id"]) for row in bounded_violators],
            "truncated": not complete,
            "coverage": {
                "complete": complete,
                "examined_rows": len(examined),
                "total_rows": len(sources),
                "returned_evidence_objects": len(bounded_rows),
            },
            "limitations": limitations,
            "matches": bounded_violators,
        }

    @staticmethod
    def _edge_matches_census(
        edge: dict[str, object], *, edge_label: str, attr_name: str
    ) -> bool:
        relationship = str(edge.get("relationship") or "")
        family = str(edge.get("edge_family") or "")
        attributes = edge.get("attributes")
        attr_map = attributes if isinstance(attributes, dict) else {}
        edge_attr = str(attr_map.get("attr_name") or relationship)
        edge_family = str(attr_map.get("label") or family)
        if edge_attr != attr_name:
            return False
        if not edge_label:
            return True
        return edge_label in {edge_family, family, relationship}

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
