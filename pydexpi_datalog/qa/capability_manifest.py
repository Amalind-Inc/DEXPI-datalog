from __future__ import annotations

from dataclasses import dataclass, field

PERMISSION_ALLOWED_READ_ONLY = "allowed_read_only"
PERMISSION_CONFIRMATION_REQUIRED = "confirmation_required"
PERMISSION_DENIED = "denied"


@dataclass(frozen=True)
class GroundedQACapability:
    tool_name: str
    description: str
    permission_class: str
    when_to_use: str
    evidence_kind: str
    source_grounding_posture: str
    limitations: tuple[str, ...]
    citation_metadata: dict[str, str]
    parameters: dict[str, object]
    denied_reason: str | None = None

    def provider_tool_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": self.provider_description(),
                "parameters": self.parameters,
            },
        }

    def provider_description(self) -> str:
        limitations = " ".join(self.limitations)
        return " ".join(
            part
            for part in (
                self.description,
                f"Permission: {self.permission_class}.",
                f"When to use: {self.when_to_use}",
                f"Evidence: {self.evidence_kind}.",
                f"Source grounding: {self.source_grounding_posture}.",
                f"Limitations: {limitations}" if limitations else "",
            )
            if part
        )


@dataclass(frozen=True)
class GroundedQACapabilityManifest:
    capabilities: tuple[GroundedQACapability, ...] = field(default_factory=tuple)

    def require(self, tool_name: str) -> GroundedQACapability:
        capability = self.get(tool_name)
        if capability is None:
            raise KeyError(tool_name)
        return capability

    def get(self, tool_name: str) -> GroundedQACapability | None:
        for capability in self.capabilities:
            if capability.tool_name == tool_name:
                return capability
        return None

    def provider_tool_definitions(self) -> list[dict[str, object]]:
        return [
            capability.provider_tool_definition()
            for capability in self.capabilities
            if capability.permission_class != PERMISSION_DENIED
        ]

    def system_prompt_tool_guidance(self) -> str:
        lines = [
            "Available grounded QA capabilities are backend-owned and policy checked:",
        ]
        for capability in self.capabilities:
            if capability.permission_class == PERMISSION_DENIED:
                continue
            lines.append(
                "- "
                f"{capability.tool_name}: {capability.when_to_use} "
                f"Permission={capability.permission_class}; "
                f"evidence={capability.evidence_kind}; "
                f"limitations={' '.join(capability.limitations)}"
            )
        return "\n".join(lines)

    def system_prompt(self) -> str:
        """Full model-facing system prompt: tool guidance plus grounding policy."""
        return f"{self.system_prompt_tool_guidance()}\n\n{GROUNDING_DISCLOSURE_POLICY}"


# Answer grounding policy. The model owns language interpretation and decides each
# answer's grounding posture; the backend deterministically enforces that the
# declared posture matches the validated evidence. There is no backend question
# classifier, so off-topic redirection is model behavior driven by this policy.
GROUNDING_DISCLOSURE_POLICY = "\n".join(
    [
        "Declare a grounding_posture on every final answer:",
        "- source_grounded: a conclusion about the loaded source. Only use this "
        "when you cite validated topology evidence; unsupported source claims are "
        "rejected.",
        "- general_knowledge: general process-engineering education. State clearly "
        "that it is not derived from the loaded source.",
        "- source_data_unavailable: a source-specific calculation whose operating "
        "inputs are absent. Say what data is missing; never invent values.",
        "- needs_clarification: the request omits the object, scope, or acceptance "
        "criterion needed for a source-grounded check. Ask for that detail and "
        "offer concrete checks the loaded source can support.",
        "- out_of_scope: a question unrelated to P&ID source review. You may "
        "first give a brief, honest acknowledgment of the question (one or two "
        "sentences -- e.g. name the model you are, or answer a trivial general "
        "question directly); never pretend you cannot understand it. Then "
        "redirect the user conversationally back to their loaded source.",
        "Never present model knowledge as if it were a conclusion read from the "
        "loaded source.",
    ]
)


def default_grounded_qa_manifest(
    *, temporary_datalog_contract: str | None = None
) -> GroundedQACapabilityManifest:
    datalog_contract = temporary_datalog_contract or (
        "declare `.decl answer(x:symbol)` and output exactly `.output answer`; "
        "rules and facts may use ONLY the predicates `answer` and `reachable`; "
        "`reachable` facts are supplied by the engine -- never define or redeclare it."
    )
    return GroundedQACapabilityManifest(
        capabilities=(
            GroundedQACapability(
                tool_name="find_equipment",
                description=(
                    "Search or list topology objects in the loaded P&ID source. "
                    "Results are bounded and ordered toward process-facing objects."
                ),
                permission_class=PERMISSION_ALLOWED_READ_ONLY,
                when_to_use=(
                    "Use before answering when the user mentions a tag, equipment, "
                    "line, nozzle, or ambiguous object reference."
                ),
                evidence_kind="topology_object_candidates",
                source_grounding_posture="loaded_source",
                limitations=(
                    "Candidate results identify possible source objects; they do not by themselves prove connectivity or path claims.",
                    "Truncated candidate results must be disclosed and cannot prove absence.",
                ),
                citation_metadata={
                    "primary_id_field": "evidence_id",
                    "label_field": "label",
                    "citation_role": "candidate_object",
                },
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": (
                                "Search term matched against tag, line number, label, class, or category. "
                                "Use an empty string to list bounded candidate objects."
                            ),
                        }
                    },
                    "required": ["pattern"],
                },
            ),
            GroundedQACapability(
                tool_name="get_reachable_equipment",
                description=(
                    "Find topology objects reachable from a given loaded-source object and return complete structural path witnesses."
                ),
                permission_class=PERMISSION_ALLOWED_READ_ONLY,
                when_to_use=(
                    "Use for loaded-source connectivity, structural reachability, upstream/downstream, and path-witness questions."
                ),
                evidence_kind="structural_path_witness",
                source_grounding_posture="loaded_source",
                limitations=(
                    "Direction evidence may be explicit, inferred, or unknown and must be disclosed for direction-sensitive claims.",
                    "Bounded traversal results support witnessed existential claims, but truncated coverage cannot prove absence or universal coverage.",
                ),
                citation_metadata={
                    "primary_id_field": "evidence_id",
                    "witness_field": "witness",
                    "citation_role": "structural_witness",
                },
                parameters={
                    "type": "object",
                    "properties": {
                        "equipment_id": {
                            "type": "string",
                            "description": "The evidence_id of the source topology object.",
                        },
                        "max_hops": {
                            "type": "integer",
                            "description": "Maximum traversal depth. Default 6.",
                            "default": 6,
                        },
                    },
                    "required": ["equipment_id"],
                },
            ),
            GroundedQACapability(
                tool_name="propose_temporary_datalog",
                description=(
                    "Propose a temporary generated Datalog query and engineer-readable restatement when read-only retrieval is insufficient."
                ),
                permission_class=PERMISSION_CONFIRMATION_REQUIRED,
                when_to_use=(
                    "Use only after bounded retrieval when the question requires recursion, formal constraints, or predicate contract reasoning."
                ),
                evidence_kind="datalog_query_pair",
                source_grounding_posture="predicate_contract_and_resolved_identities",
                limitations=(
                    "This capability proposes but never executes generated Datalog without explicit user confirmation.",
                    "The model receives predicate contract context and relevant resolved identities, not the complete full fact database by default.",
                ),
                citation_metadata={
                    "primary_id_field": "proposal_id",
                    "citation_role": "confirmation_required_query_pair",
                },
                parameters={
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "The user request requiring generated Datalog.",
                        },
                        "generated_datalog": {
                            "type": "string",
                            "description": (
                                "The exact temporary Souffle Datalog program proposed for "
                                "confirmation. Contract (violations are rejected before "
                                f"confirmation): {datalog_contract} "
                                "Refer to objects exclusively by their exact quoted evidence "
                                "IDs already resolved through read-only retrieval (never "
                                "invented names); no `.input`, `.include`, or filesystem "
                                "directives. Canonical shape: `.decl answer(x:symbol)` then "
                                "`.output answer` then "
                                '`answer(x) :- reachable("<evidence-id>", x).`'
                            ),
                        },
                        "formal_restatement": {
                            "type": "string",
                            "description": "Engineer-readable restatement of what the temporary query returns.",
                        },
                        "resolved_identity_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Evidence IDs already resolved through read-only retrieval.",
                        },
                    },
                    "required": ["request", "generated_datalog", "formal_restatement"],
                },
            ),
            GroundedQACapability(
                tool_name="mutate_source_graph",
                description="Denied capability placeholder documenting that source graph mutation is unavailable.",
                permission_class=PERMISSION_DENIED,
                when_to_use="Never use. Source graph mutation is outside grounded QA.",
                evidence_kind="none",
                source_grounding_posture="denied",
                limitations=("The grounded QA harness never exposes graph mutation tools.",),
                citation_metadata={"citation_role": "none"},
                parameters={"type": "object", "properties": {}},
                denied_reason="Source graph mutation is denied for grounded QA.",
            ),
        )
    )
