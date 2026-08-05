export const PUMP_DISCHARGE_CHECK_ID = "pump_discharge_check_valve" as const;

const RULE_VERSION = 1;
const PACK_ID = "demo-process-safety";
const ENGINE_NAME = "souffle";
const RULE_SOURCE = "demo-process-safety.md";
const MAX_IDENTIFIER_LENGTH = 256;

const RULE_LIMITATIONS = Object.freeze([
  "Only the allowlisted centrifugal-pump discharge check is available.",
  "A result is authoritative only for the returned bounded scope and source revision.",
]);

const REQUIRED_RULE_CLASS = "CentrifugalPump";

export type PortLogRuleCheckRequest = {
  readonly checkId: string;
  readonly scopeEntityId: string;
  readonly signal?: AbortSignal;
};

export type PortLogRuleCheckBridge = (
  request: PortLogCheckBridgeRequest,
) => Promise<unknown>;

type PortLogCheckBridgeRequest = {
  readonly checkId: string;
  readonly scopeEntityId: string;
  readonly signal: AbortSignal | undefined;
};

export type PortLogCapabilityDescriptor = {
  readonly name: "portlog_rule_check";
  readonly version: 1;
  readonly authority: "deterministic";
  readonly ruleId: typeof PUMP_DISCHARGE_CHECK_ID;
  readonly ruleVersion: 1;
  readonly packId: typeof PACK_ID;
  readonly description: string;
};

export type PortLogRuleCheckResult = {
  [key: string]: unknown;
  capability: PortLogCapabilityDescriptor;
  rule: {
    check_id: typeof PUMP_DISCHARGE_CHECK_ID;
    check_version: 1;
    pack_id: typeof PACK_ID;
    pack_version: number;
    source: typeof RULE_SOURCE;
  };
  scope: {
    requested_entity_id: string;
    evaluated_entity_id: string;
    pump_id: string;
    class: typeof REQUIRED_RULE_CLASS;
  };
  source_revision: string;
  source_attestation: {
    revision: string;
    kind: "prepared-review-source";
    authority: "governed-check-engine";
  };
  coverage: {
    requested_entity_id: string;
    evaluated_entity_id: string;
    required_facts: string[];
    missing_facts: string[];
    complete: boolean;
  };
  limitations: readonly string[];
  provenance: {
    authority: "deterministic";
    origin: "pydexpi_datalog.verification.governed_check";
    source_revision: string;
  };
  model_interpretation: null;
  deterministic_result: Record<string, unknown>;
};

export interface PortLogCapabilityRegistry {
  list(): readonly PortLogCapabilityDescriptor[];
  invoke(
    name: string,
    request: PortLogRuleCheckRequest,
  ): Promise<PortLogRuleCheckResult>;
}

export function createPortLogCapabilityRegistry(options: {
  getRuleCheck: PortLogRuleCheckBridge;
  sourceRevision?: string;
}): PortLogCapabilityRegistry {
  const descriptor: PortLogCapabilityDescriptor = Object.freeze({
    name: "portlog_rule_check",
    version: 1,
    authority: "deterministic",
    ruleId: PUMP_DISCHARGE_CHECK_ID,
    ruleVersion: RULE_VERSION,
    packId: PACK_ID,
    description:
      "Run the allowlisted Souffle-backed centrifugal-pump discharge check over one prepared entity.",
  });

  return {
    list: () => [descriptor],
    invoke: async (name, request) => {
      if (name !== descriptor.name) throw new Error(`capability.unknown: ${name}`);
      validateRequest(request, descriptor);
      const raw = await options.getRuleCheck({
        checkId: request.checkId,
        scopeEntityId: request.scopeEntityId,
        signal: request.signal,
      });
      return normalizeRuleCheckResult(raw, request, descriptor, options.sourceRevision);
    },
  };
}

function validateRequest(
  request: PortLogRuleCheckRequest,
  descriptor: PortLogCapabilityDescriptor,
): void {
  if (!asRecord(request))
    throw new Error("request.malformed: rule-check request must be an object");
  if (!isBoundedIdentifier(request.checkId))
    throw new Error("check.invalid: a bounded rule ID is required");
  if (request.checkId !== descriptor.ruleId)
    throw new Error(`check.invalid: unknown check '${request.checkId}'`);
  if (!isBoundedIdentifier(request.scopeEntityId))
    throw new Error("scope.invalid: a bounded scope entity ID is required");
}

function normalizeRuleCheckResult(
  raw: unknown,
  request: PortLogRuleCheckRequest,
  descriptor: PortLogCapabilityDescriptor,
  expectedSourceRevision: string | undefined,
): PortLogRuleCheckResult {
  const envelope = asRecord(raw);
  const deterministic = asRecord(envelope?.deterministic_result);
  if (!envelope || !deterministic)
    throw new Error("result.malformed: governed check did not return deterministic_result");

  if (deterministic.check_id !== descriptor.ruleId)
    throw new Error("result.check_mismatch: governed result has the wrong check ID");
  if (readVersion(deterministic.check_version) !== descriptor.ruleVersion)
    throw new Error("result.version_mismatch: governed result has the wrong rule version");

  const scope = asRecord(deterministic.scope);
  if (
    !scope ||
    scope.requested_entity_id !== request.scopeEntityId ||
    scope.class !== REQUIRED_RULE_CLASS ||
    !isBoundedIdentifier(scope.pump_id)
  ) {
    throw new Error("result.scope_mismatch: governed result is outside the requested scope");
  }

  const runStatus = deterministic.run_status;
  if (runStatus !== "completed" && runStatus !== "failed")
    throw new Error("result.run_status_invalid: governed result has an unknown run status");

  const rawOutcome = deterministic.outcome;
  if (
    rawOutcome !== null &&
    rawOutcome !== "satisfied" &&
    rawOutcome !== "violated" &&
    rawOutcome !== "indeterminate"
  ) {
    throw new Error("result.outcome_invalid: governed result has an unknown outcome");
  }
  if (runStatus === "completed" && rawOutcome === null)
    throw new Error("result.outcome_missing: completed governed result has no outcome");

  const digest = readNonEmptyString(deterministic.document_preparation_digest);
  const attestation = asRecord(deterministic.source_attestation);
  if (!digest || !attestation || attestation.revision !== digest)
    throw new Error("result.source_attestation_missing: evaluated source revision is not attested");
  if (
    attestation.kind !== "prepared-review-source" ||
    attestation.authority !== "governed-check-engine"
  )
    throw new Error("result.source_attestation_invalid: unexpected source attestation");
  if (expectedSourceRevision !== undefined && digest !== expectedSourceRevision)
    throw new Error("result.source_revision_mismatch: evaluated source differs from the expected revision");

  const engine = asRecord(deterministic.engine);
  if (!engine || engine.name !== ENGINE_NAME || (engine.status !== "completed" && engine.status !== "failed"))
    throw new Error("result.engine_invalid: governed result was not produced by the Souffle engine");
  if (engine.status !== runStatus)
    throw new Error("result.status_mismatch: governed run and engine statuses disagree");
  const rule = asRecord(deterministic.rule);
  if (
    runStatus === "completed" &&
    (!rule || rule.pack_id !== descriptor.packId || readPackVersion(rule) !== descriptor.ruleVersion)
  )
    throw new Error("result.rule_mismatch: governed result has the wrong rule pack");

  const rawCoverage = asRecord(deterministic.coverage);
  const rawEvidence = asRecord(deterministic.evidence);
  const rawScopeCoverage = asRecord(rawEvidence?.scope_completeness);
  const requiredFacts = readStrictStringArray(rawCoverage?.required_facts, "required_facts");
  const missingFacts = readStrictStringArray(rawCoverage?.missing_facts, "missing_facts");
  const coverageComplete =
    requiredFacts.length > 0 &&
    rawCoverage?.requested_entity_id === request.scopeEntityId &&
    rawCoverage?.evaluated_entity_id === scope.pump_id &&
    rawCoverage?.complete === true &&
    rawScopeCoverage?.complete === true &&
    missingFacts.length === 0;

  const outcome =
    runStatus === "completed" && engine.status === "completed" && coverageComplete && rawOutcome !== null
      ? rawOutcome
      : "indeterminate";
  const normalizedDeterministic: Record<string, unknown> = {
    ...deterministic,
    check_id: descriptor.ruleId,
    check_version: descriptor.ruleVersion,
    run_status: runStatus,
    outcome,
    scope: {
      ...scope,
      requested_entity_id: request.scopeEntityId,
      class: REQUIRED_RULE_CLASS,
    },
    document_preparation_digest: digest,
    source_attestation: {
      revision: digest,
      kind: "prepared-review-source",
      authority: "governed-check-engine",
    },
    coverage: {
      requested_entity_id: request.scopeEntityId,
      evaluated_entity_id: scope.pump_id,
      required_facts: requiredFacts,
      missing_facts: missingFacts,
      complete: coverageComplete,
    },
  };

  return {
    ...envelope,
    capability: descriptor,
    rule: {
      check_id: descriptor.ruleId,
      check_version: descriptor.ruleVersion,
      pack_id: descriptor.packId,
      pack_version: readPackVersion(asRecord(deterministic.rule)),
      source: RULE_SOURCE,
    },
    scope: {
      requested_entity_id: request.scopeEntityId,
      evaluated_entity_id: scope.pump_id,
      pump_id: scope.pump_id,
      class: REQUIRED_RULE_CLASS,
    },
    source_revision: digest,
    source_attestation: {
      revision: digest,
      kind: "prepared-review-source",
      authority: "governed-check-engine",
    },
    coverage: {
      requested_entity_id: request.scopeEntityId,
      evaluated_entity_id: scope.pump_id,
      required_facts: requiredFacts,
      missing_facts: missingFacts,
      complete: coverageComplete,
    },
    limitations: coverageComplete
      ? RULE_LIMITATIONS
      : Object.freeze([...RULE_LIMITATIONS, "coverage.incomplete: the bounded scope was not fully evaluated."]),
    provenance: {
      authority: "deterministic",
      origin: "pydexpi_datalog.verification.governed_check",
      source_revision: digest,
    },
    model_interpretation: null,
    deterministic_result: normalizedDeterministic,
  };
}

function isBoundedIdentifier(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= MAX_IDENTIFIER_LENGTH;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function readNonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value : undefined;
}

function readVersion(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isInteger(value)) return value;
  if (typeof value === "string" && /^\d+$/.test(value)) return Number(value);
  return undefined;
}

function readPackVersion(rule: Record<string, unknown> | undefined): number {
  const version = readVersion(rule?.pack_version);
  return version ?? 1;
}

function readStrictStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => !isBoundedIdentifier(item)))
    throw new Error(`result.coverage_invalid: coverage.${field} must be an array of bounded non-empty strings`);
  return value as string[];
}
