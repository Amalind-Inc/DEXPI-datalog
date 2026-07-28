export const RULE_PACK_RUN_PREFIX = "pydexpi:rule-pack-run:";

export type RuleOutcome = "satisfied" | "violated" | "indeterminate";

export type RuleEvidencePath = {
  id: string;
  node_ids: string[];
  edge_ids: string[];
};

export type RuleEvidenceHighlight = {
  source_scope_ids: string[];
  matched_object_ids: string[];
  paths: RuleEvidencePath[];
};

export type RuleRunResult = {
  ruleId: string;
  title: string;
  outcome: RuleOutcome;
  summaryText: string;
  evidenceHighlight: RuleEvidenceHighlight;
  evidenceItems: unknown[];
  raw: Record<string, unknown>;
};

export type RulePackRunState = {
  packId: string;
  packTitle: string;
  packVersion: number;
  authoritative: boolean;
  trustNotice: string;
  results: RuleRunResult[];
  mode?: "rule_evaluation" | "advisory_walkthrough";
  walkthrough?: AdvisoryWalkthrough;
};

export type AdvisoryWalkthroughStep = {
  kind: "advisory_checklist_step";
  title: string;
  body: string;
};

export type AdvisoryWalkthrough = {
  kind: "advisory_pack_walkthrough";
  packId: string;
  title: string;
  disclaimer: string;
  steps: AdvisoryWalkthroughStep[];
};

export function serializeRulePackRun(state: RulePackRunState): string {
  return `${RULE_PACK_RUN_PREFIX}${JSON.stringify(state)}`;
}

export function parseRulePackRunMessage(text: string): RulePackRunState | null {
  if (!text.startsWith(RULE_PACK_RUN_PREFIX)) return null;
  try {
    const parsed = JSON.parse(text.slice(RULE_PACK_RUN_PREFIX.length));
    if (!isRecord(parsed)) return null;
    if (typeof parsed.packId !== "string") return null;
    if (typeof parsed.packTitle !== "string") return null;
    if (typeof parsed.packVersion !== "number") return null;
    if (typeof parsed.authoritative !== "boolean") return null;
    if (typeof parsed.trustNotice !== "string") return null;
    if (!Array.isArray(parsed.results)) return null;
    const results: RuleRunResult[] = [];
    for (const item of parsed.results) {
      if (!isRecord(item)) return null;
      if (typeof item.ruleId !== "string") return null;
      if (typeof item.title !== "string") return null;
      if (!isRuleOutcome(item.outcome)) return null;
      if (typeof item.summaryText !== "string") return null;
      if (!isRecord(item.evidenceHighlight)) return null;
      if (!Array.isArray(item.evidenceItems)) return null;
      if (!isRecord(item.raw)) return null;
      results.push({
        ruleId: item.ruleId,
        title: item.title,
        outcome: item.outcome,
        summaryText: item.summaryText,
        evidenceHighlight: readEvidenceHighlight(item.evidenceHighlight),
        evidenceItems: item.evidenceItems,
        raw: item.raw,
      });
    }
    return {
      packId: parsed.packId,
      packTitle: parsed.packTitle,
      packVersion: parsed.packVersion,
      authoritative: parsed.authoritative,
      trustNotice: parsed.trustNotice,
      results,
      mode:
        parsed.mode === "advisory_walkthrough" || parsed.mode === "rule_evaluation"
          ? parsed.mode
          : undefined,
      walkthrough: readWalkthrough(parsed.walkthrough),
    };
  } catch {
    return null;
  }
}

function readWalkthrough(value: unknown): AdvisoryWalkthrough | undefined {
  if (!isRecord(value)) return undefined;
  if (value.kind !== "advisory_pack_walkthrough") return undefined;
  if (typeof value.packId !== "string" && typeof value.pack_id !== "string") {
    return undefined;
  }
  if (typeof value.title !== "string") return undefined;
  if (typeof value.disclaimer !== "string") return undefined;
  if (!Array.isArray(value.steps)) return undefined;
  const steps: AdvisoryWalkthroughStep[] = [];
  for (const step of value.steps) {
    if (!isRecord(step)) return undefined;
    if (step.kind !== "advisory_checklist_step") return undefined;
    if (typeof step.title !== "string") return undefined;
    if (typeof step.body !== "string") return undefined;
    steps.push({
      kind: "advisory_checklist_step",
      title: step.title,
      body: step.body,
    });
  }
  return {
    kind: "advisory_pack_walkthrough",
    packId: typeof value.packId === "string" ? value.packId : String(value.pack_id),
    title: value.title,
    disclaimer: value.disclaimer,
    steps,
  };
}

/** Convert backend walkthrough payload into frontend state. */
export function advisoryWalkthroughFromApi(
  raw: Record<string, unknown>,
): AdvisoryWalkthrough | null {
  return readWalkthrough(raw) ?? null;
}

/** Convert one raw backend `results[i]` object (from the run-all or single-rule
 * routes) into a RuleRunResult, extracting evidence the same way turn-client.ts
 * does for other message types. The backend result only carries `rule_id`, not
 * a human title, so the caller (which has the pack listing) supplies it. */
export function ruleRunResultFromApi(
  raw: Record<string, unknown>,
  ruleTitle: string,
): RuleRunResult {
  const summary = isRecord(raw.summary) ? raw.summary : {};
  const evidence = isRecord(raw.evidence) ? raw.evidence : {};
  return {
    ruleId: typeof raw.rule_id === "string" ? raw.rule_id : "",
    title: ruleTitle,
    outcome: isRuleOutcome(raw.outcome) ? raw.outcome : "indeterminate",
    summaryText: typeof summary.text === "string" ? summary.text : "",
    evidenceHighlight: readEvidenceHighlight(raw.evidence_highlight),
    evidenceItems: Array.isArray(evidence.items) ? evidence.items : [],
    raw,
  };
}

function isRuleOutcome(value: unknown): value is RuleOutcome {
  return value === "satisfied" || value === "violated" || value === "indeterminate";
}

function readEvidenceHighlight(value: unknown): RuleEvidenceHighlight {
  if (!isRecord(value)) return { source_scope_ids: [], matched_object_ids: [], paths: [] };
  return {
    source_scope_ids: readStringArray(value.source_scope_ids),
    matched_object_ids: readStringArray(value.matched_object_ids),
    paths: Array.isArray(value.paths)
      ? value.paths.filter(isRecord).map((p) => ({
          id: typeof p.id === "string" ? p.id : "",
          node_ids: readStringArray(p.node_ids),
          edge_ids: readStringArray(p.edge_ids),
        }))
      : [],
  };
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
