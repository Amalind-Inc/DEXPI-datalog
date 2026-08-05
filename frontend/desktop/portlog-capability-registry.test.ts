import assert from "node:assert/strict";
import test from "node:test";

import {
  createPortLogCapabilityRegistry,
  PUMP_DISCHARGE_CHECK_ID,
} from "./portlog-capability-registry.ts";

const completeResult = (outcome: "satisfied" | "violated" | "indeterminate") => ({
  status: "answered",
  deterministic_result: {
    schema_version: 1,
    check_id: PUMP_DISCHARGE_CHECK_ID,
    check_version: 1,
    rule: { pack_id: "demo-process-safety", pack_version: 1 },
    scope: {
      requested_entity_id: "P-101",
      pump_id: "CentrifugalPump-1",
      class: "CentrifugalPump",
    },
    required_facts: ["discharge path"],
    run_status: "completed",
    outcome,
    evidence: {
      scope_completeness: { complete: true, basis: "terminal_boundary_reached" },
      ordered_entity_ids: ["CentrifugalPump-1", "CheckValve-1"],
    },
    coverage: {
      requested_entity_id: "P-101",
      evaluated_entity_id: "CentrifugalPump-1",
      required_facts: ["discharge path"],
      missing_facts: [],
      complete: true,
    },
    engine: { name: "souffle", status: "completed", rule_source: "demo-process-safety.md" },
    document_preparation_digest: "sha256:source-1",
    source_attestation: {
      revision: "sha256:source-1",
      kind: "prepared-review-source",
      authority: "governed-check-engine",
    },
  },
});

test("registry exposes one source-bound deterministic rule capability", async () => {
  let calls = 0;
  const registry = createPortLogCapabilityRegistry({
    sourceRevision: "sha256:source-1",
    getRuleCheck: async (request) => {
      calls += 1;
      assert.equal(request.checkId, PUMP_DISCHARGE_CHECK_ID);
      assert.equal(request.scopeEntityId, "P-101");
      return completeResult("satisfied");
    },
  });

  assert.deepEqual(registry.list().map((capability) => capability.name), ["portlog_rule_check"]);
  const result = await registry.invoke("portlog_rule_check", {
    checkId: PUMP_DISCHARGE_CHECK_ID,
    scopeEntityId: "P-101",
    signal: new AbortController().signal,
  });

  assert.equal(calls, 1);
  assert.equal(result.capability.name, "portlog_rule_check");
  assert.equal(result.rule.check_id, PUMP_DISCHARGE_CHECK_ID);
  assert.equal(result.scope.requested_entity_id, "P-101");
  assert.equal(result.source_revision, "sha256:source-1");
  assert.equal(result.coverage.complete, true);
  assert.deepEqual(result.limitations, [
    "Only the allowlisted centrifugal-pump discharge check is available.",
    "A result is authoritative only for the returned bounded scope and source revision.",
  ]);
  assert.equal(result.deterministic_result.outcome, "satisfied");
  assert.equal(result.model_interpretation, null);
});

test("registry preserves all three deterministic outcomes and refuses incomplete coverage as a pass", async () => {
  for (const outcome of ["satisfied", "violated", "indeterminate"] as const) {
    const registry = createPortLogCapabilityRegistry({
      sourceRevision: "sha256:source-1",
      getRuleCheck: async () => completeResult(outcome),
    });
    const result = await registry.invoke("portlog_rule_check", {
      checkId: PUMP_DISCHARGE_CHECK_ID,
      scopeEntityId: "P-101",
    });
    assert.equal(result.deterministic_result.outcome, outcome);
  }

  const incomplete = createPortLogCapabilityRegistry({
    sourceRevision: "sha256:source-1",
    getRuleCheck: async () => ({
      ...completeResult("satisfied"),
      deterministic_result: {
        ...completeResult("satisfied").deterministic_result,
        evidence: { scope_completeness: { complete: false, basis: "off_page_connector" } },
      },
    }),
  });
  const result = await incomplete.invoke("portlog_rule_check", {
    checkId: PUMP_DISCHARGE_CHECK_ID,
    scopeEntityId: "P-101",
  });
  assert.equal(result.coverage.complete, false);
  assert.equal(result.deterministic_result.outcome, "indeterminate");
});

test("registry rejects unknown checks, mismatched scopes, and malformed engine results", async () => {
  const registry = createPortLogCapabilityRegistry({
    sourceRevision: "sha256:source-1",
    getRuleCheck: async () => completeResult("satisfied"),
  });

  await assert.rejects(
    registry.invoke("not-a-registered-capability", {
      checkId: PUMP_DISCHARGE_CHECK_ID,
      scopeEntityId: "P-101",
    }),
    /capability\.unknown/,
  );
  await assert.rejects(
    registry.invoke("portlog_rule_check", {
      checkId: "not-allowlisted",
      scopeEntityId: "P-101",
    }),
    /check\.invalid/,
  );

  const mismatch = createPortLogCapabilityRegistry({
    sourceRevision: "sha256:source-1",
    getRuleCheck: async () => ({
      ...completeResult("satisfied"),
      deterministic_result: {
        ...completeResult("satisfied").deterministic_result,
        scope: { ...completeResult("satisfied").deterministic_result.scope, requested_entity_id: "P-999" },
      },
    }),
  });
  await assert.rejects(
    mismatch.invoke("portlog_rule_check", {
      checkId: PUMP_DISCHARGE_CHECK_ID,
      scopeEntityId: "P-101",
    }),
    /result\.scope_mismatch/,
  );

  const malformed = createPortLogCapabilityRegistry({
    sourceRevision: "sha256:source-1",
    getRuleCheck: async () => ({ prose: "The model says it passed." }),
  });
  await assert.rejects(
    malformed.invoke("portlog_rule_check", {
      checkId: PUMP_DISCHARGE_CHECK_ID,
      scopeEntityId: "P-101",
    }),
    /result\.malformed/,
  );
});


test("registry rejects inconsistent run and engine statuses before promotion", async () => {
  const registry = createPortLogCapabilityRegistry({
    sourceRevision: "sha256:source-1",
    getRuleCheck: async () => ({
      ...completeResult("satisfied"),
      deterministic_result: {
        ...completeResult("satisfied").deterministic_result,
        engine: {
          ...completeResult("satisfied").deterministic_result.engine,
          status: "failed",
        },
      },
    }),
  });

  await assert.rejects(
    registry.invoke("portlog_rule_check", {
      checkId: PUMP_DISCHARGE_CHECK_ID,
      scopeEntityId: "P-101",
    }),
    /result\.status_mismatch/,
  );
});

test("registry rejects malformed coverage fact arrays", async () => {
  for (const malformedMissingFact of [null, "", 42]) {
    const registry = createPortLogCapabilityRegistry({
      sourceRevision: "sha256:source-1",
      getRuleCheck: async () => ({
        ...completeResult("satisfied"),
        deterministic_result: {
          ...completeResult("satisfied").deterministic_result,
          coverage: {
            ...completeResult("satisfied").deterministic_result.coverage,
            missing_facts: [malformedMissingFact],
          },
        },
      }),
    });

    await assert.rejects(
      registry.invoke("portlog_rule_check", {
        checkId: PUMP_DISCHARGE_CHECK_ID,
        scopeEntityId: "P-101",
      }),
      /result\.coverage_invalid/,
    );
  }

  const malformedRequiredFacts = createPortLogCapabilityRegistry({
    sourceRevision: "sha256:source-1",
    getRuleCheck: async () => ({
      ...completeResult("satisfied"),
      deterministic_result: {
        ...completeResult("satisfied").deterministic_result,
        coverage: {
          ...completeResult("satisfied").deterministic_result.coverage,
          required_facts: ["discharge path", null],
        },
      },
    }),
  });

  await assert.rejects(
    malformedRequiredFacts.invoke("portlog_rule_check", {
      checkId: PUMP_DISCHARGE_CHECK_ID,
      scopeEntityId: "P-101",
    }),
    /result\.coverage_invalid/,
  );
});