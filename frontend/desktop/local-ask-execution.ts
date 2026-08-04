export type AskEvaluation = {
  scopeEntityId: string;
  outcome: "satisfied" | "violated" | "indeterminate";
  reasonCode?: string;
  evidenceIds: string[];
};

export type AskDerivation = {
  claim: string;
  ruleId: string;
  domain?: string;
  domainComplete: boolean;
  emptyDomain: boolean;
  scopeEntityIds: string[];
  evaluations: AskEvaluation[];
  counterexamples: string[];
  unknowns: string[];
  outcome: "satisfied" | "violated" | "indeterminate";
  summary: string;
};

type ScopedCheck = { scopeEntityId: string; result: unknown };

type DerivationInput = {
  claim: string;
  ruleId: string;
  scopeEntityIds: readonly string[];
  checks: readonly ScopedCheck[];
  domain?: string;
};

export function buildRuleDerivation(input: DerivationInput): AskDerivation {
  const evaluations = input.scopeEntityIds.map((scopeEntityId) =>
    evaluateScope(
      scopeEntityId,
      input.checks.find((check) => check.scopeEntityId === scopeEntityId)?.result,
    ),
  );
  const outcome = aggregateOutcome(evaluations, input.scopeEntityIds.length === 0);
  const counterexamples = evaluations
    .filter((evaluation) => evaluation.outcome === "violated")
    .map((evaluation) => evaluation.scopeEntityId);
  const unknowns = evaluations
    .filter((evaluation) => evaluation.outcome === "indeterminate")
    .map((evaluation) => evaluation.scopeEntityId);
  const emptyDomain = input.scopeEntityIds.length === 0;
  const summary = summarize(input, outcome, counterexamples, unknowns, emptyDomain);

  return {
    claim: input.claim,
    ruleId: input.ruleId,
    domain: input.domain,
    domainComplete:
      !emptyDomain && unknowns.length === 0 && evaluations.length === input.scopeEntityIds.length,
    emptyDomain,
    scopeEntityIds: [...input.scopeEntityIds],
    evaluations,
    counterexamples,
    unknowns,
    outcome,
    summary,
  };
}

export function aggregateUniversalRule(input: DerivationInput & { domain: string }): AskDerivation {
  return buildRuleDerivation(input);
}

function evaluateScope(scopeEntityId: string, result: unknown): AskEvaluation {
  const check = findDeterministicResult(result);
  const outcome =
    check?.run_status === "completed" && isOutcome(check.outcome) ? check.outcome : "indeterminate";
  const reasonCode = typeof check?.reason_code === "string" ? check.reason_code : undefined;
  return {
    scopeEntityId,
    outcome,
    reasonCode,
    evidenceIds: extractEvidenceIds(check?.evidence),
  };
}

function aggregateOutcome(
  evaluations: readonly AskEvaluation[],
  emptyDomain: boolean,
): AskDerivation["outcome"] {
  if (emptyDomain || evaluations.some((evaluation) => evaluation.outcome === "indeterminate"))
    return "indeterminate";
  if (evaluations.some((evaluation) => evaluation.outcome === "violated")) return "violated";
  return "satisfied";
}

function summarize(
  input: DerivationInput,
  outcome: AskDerivation["outcome"],
  counterexamples: readonly string[],
  unknowns: readonly string[],
  emptyDomain: boolean,
): string {
  const domainLabel = input.domain?.replaceAll("_", " ");
  if (emptyDomain) {
    return `No ${domainLabel ?? "scoped objects"} were found; the rule was not proven.`;
  }
  if (input.domain) {
    if (outcome === "violated")
      return `The universal rule for all ${domainLabel} was disproved; counterexample(s): ${counterexamples.join(", ")}.`;
    if (outcome === "indeterminate")
      return `The universal rule for all ${domainLabel} is indeterminate; unknown member(s): ${unknowns.join(", ")}.`;
    return `The universal rule was proved for all ${input.scopeEntityIds.length} ${domainLabel}.`;
  }
  if (outcome === "violated") return `The rule was violated for ${counterexamples.join(", ")}.`;
  if (outcome === "indeterminate")
    return `The rule could not be determined for ${unknowns.join(", ")}.`;
  return `The rule was satisfied for all ${input.scopeEntityIds.length} checked scope(s).`;
}

function findDeterministicResult(value: unknown): Record<string, unknown> | undefined {
  if (Array.isArray(value)) {
    for (const item of value) {
      const result = findDeterministicResult(item);
      if (result) return result;
    }
    return undefined;
  }
  if (!value || typeof value !== "object") return undefined;
  const object = value as Record<string, unknown>;
  if (object.deterministic_result && typeof object.deterministic_result === "object")
    return object.deterministic_result as Record<string, unknown>;
  for (const child of Object.values(object)) {
    const result = findDeterministicResult(child);
    if (result) return result;
  }
  return undefined;
}

function extractEvidenceIds(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
  const object = value as Record<string, unknown>;
  const direct = [object.ordered_topology_ids, object.evidence_ids, object.evidenceIds]
    .flatMap((candidate) => (Array.isArray(candidate) ? candidate : []))
    .filter((candidate): candidate is string => typeof candidate === "string");
  return [...new Set(direct)];
}

function isOutcome(value: unknown): value is AskEvaluation["outcome"] {
  return value === "satisfied" || value === "violated" || value === "indeterminate";
}
