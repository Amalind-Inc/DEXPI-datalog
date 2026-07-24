# 3qo.9.10 — Hybrid product holdout protocol

Status: product-owner approved for infrastructure (2026-07-24).
Bead: `pydexpi-datalog-1-3qo.9.10`.

## Purpose

Evaluate the released template-first hybrid grounded-QA path on an **unseen**
SME-certified slice — questions that are not in the frozen nine-entry RMSO v3
development matrix — before any production generalization claim.

## Sources

Questions are selected from already SME-certified manifests:

- `testdata/benchmark/hand_authored_manifest.json`
- `testdata/benchmark/harder_questions_manifest.json`

Certification bead: `pydexpi-datalog-1-rmso.7` (`product_owner_sme_approved`).

## Scope of this holdout

Included case tags:

- template fit / explicit class scope
- implicit / broad class scope
- piping scope
- instrumentation scope
- directed traversal (instrumentation actuation closure)

Explicitly deferred to a later ErgoAI / KRR routing project (not scored here):

- deontic abstention
- deliberate template no-fit
- generated-repair loops
- ambiguity clarification

## Arm under test

Released hybrid product path: `IncumbentArm` over `run_grounded_qa_turn` /
`TopologyTools` (automatic validated temporary Datalog; no read-only
confirmation pause).

## Accounting

Provider ledger required for live runs. Unknown cost or policy violation marks
the run incomplete. Scripted dry-runs may report zero cost.

## Generalization gate

No production generalization claim is allowed unless the preregistered gate
passes. The gate requires a complete holdout report with valid certification,
required case-tag coverage for this protocol's scope, preserved per-episode
artifacts, and a locked credit threshold on gating episodes.
