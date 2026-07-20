# rmso.3g4i - Matrix rerun: C-classic (fixed) vs Arm T, design-lock v3

Date: 2026-07-20
Bead: `pydexpi-datalog-1-3g4i` (parent design: `3av5`, implementation: `lx6p`)

## Result

Run status `COMPLETE`, formal accounting `COMPLETE`, zero invalid reasons,
zero policy violations. **Arm C 8/9, Arm T 5/9. Neither arm qualifies
(9/9 rule); decision table row (C yes/no, T yes/no) = (No, No) -> NO-GO,
same as every prior slice on this nine-question matrix.**

Locked design revision: `template-routed-vs-authored-v3`. Total spend
$0.2185 (cap $10), 51 minutes wall time, 18 episodes, all provider
accounting complete, zero unknown-cost or policy-violation calls.

| Question | Arm C (free-form Souffle) | Arm T (template-routed) |
|---|---|---|
| ha-e03-pump-p4713-retrieval | [OK] | [OK] |
| hq-nozzle-piping-attachment-small | [OK] | [OK] |
| hq-nozzle-piping-attachment-large | [OK] | [OK] |
| hq-valve-monitoring-reachability-small | [OK] | [FAIL] faithfulness |
| hq-valve-monitoring-reachability-large | [FAIL] faithfulness | [FAIL] faithfulness |
| hq-equipment-pump-connectivity-small | [OK] | [FAIL] timeout, no routing |
| hq-equipment-pump-connectivity-large | [OK] | [FAIL] timeout, no routing |
| hq-permission-defeasible-control-small | [OK] | [OK] |
| hq-permission-defeasible-control-large | [OK] | [OK] |

## What we learned

**1. Arm C is stable at 8/9 with all prior lifecycle fixes proven live.**
Zero receipt-framing losses, zero forbidden-command runs, zero provider
retry storms. The single failure, `hq-valve-monitoring-reachability-large`,
is the known faithfulness-gate rejection: the authored program's valve
scope doesn't survive replay against the frozen counterfactual probes.
This is the same failure family observed on every prior run through this
question - a genuine authoring-precision gap, not an infrastructure
defect, and now cleanly isolated as the *only* remaining Arm C failure
mode.

**2. Arm T's 5/9 splits into two distinct, non-overlapping failure
classes - neither one a template-authoring defect in the sense the
design worried about:**

- **Two faithfulness failures on the valve-monitoring family** (small
  *and* large - small failed this run, large fails on both arms every
  run). `route_trace.json` (lost from the archived job artifacts - see
  follow-up below) is missing, but `routing.json` survived: the model
  routed `guarded_reachability` with `target_labels` scoped too
  narrowly (`["GlobeValve"]` on the small case, a partial six-type
  set on the large case) instead of the full locked valve family
  (`BallValve`, `ButterflyValve`, `GlobeValve`, `OperatedValve`,
  `SwingCheckValve`, `SpringLoadedGlobeSafetyValve`). The verifier
  accepted the checkpoint (`reward.txt` = 1); the faithfulness gate
  caught it on replay against the real graph and the frozen probes.
  **This is exactly the "parameter binding is where the semantics
  live" risk from the design doc, now observed for real**: the
  template body was correct, the *bound labels* were wrong, and wrong
  labels are just as capable of producing a wrong verdict as wrong
  Datalog. Closed-world validation caught invalid labels; it cannot
  catch valid-but-incomplete label sets, because completeness is a
  semantic judgment the vocabulary alone doesn't encode.
- **Two verification-gate rejections on equipment-pump-connectivity**,
  both **before any routing was ever written** - `routing.json` was
  still the seeded empty template (`{"category": "", "parameters": {}}`)
  at cutoff, 22-23 model calls and 264s wall time spent with nothing
  checkpointed. This is a genuine reasoning/exploration-time failure
  independent of the template mechanics: the question requires
  bidirectional multi-hop piping-path reachability, and the model spent
  its full budget exploring the graph before ever committing to a
  routing category, rather than a template-fit problem (`reachability`
  covers the shape once source/target roles are picked correctly).

**3. Cross-arm agreement on the one hard question is a meaningful
result.** Both arms - one authoring Datalog freely, one binding
parameters into a frozen template - fail
`hq-valve-monitoring-reachability-large` the same way, on the same
question, run after run. That is evidence the difficulty lives in the
*question's semantic scoping*, not in either engine-arm's mechanics.

**4. Zero infrastructure regressions.** All lifecycle machinery held:
the checkpoint receipt, faithfulness replay, route_trace/run_query
delegation, mechanical abstention packaging (both permission questions
passed on both arms), provider accounting, and the retry/fallback
ladder (unexercised this run - no episode hit the validation-retry
budget or fell back to free-form authoring; every Arm T episode either
routed a template directly or ran out of time before routing at all).

## Follow-up filed

- **`route_trace.json` is not preserved in the archived job artifacts.**
  `build_rmso_template_harbor_task`'s `extra_workspace_files` lists
  `routing.json` and `analysis.dl` but not `route_trace.json`, so the
  path-tagging (`template` vs `abstention`, `program_sha256`) designed
  in lx6p slice 2 for mechanical fallback-episode detection is written
  inside the container but dropped before the report is written. Low
  severity (didn't affect grading; `routing.json` alone was enough to
  diagnose this run) but it defeats the intended provenance signal and
  should be fixed before the next scored rerun.
- **Valve-family label-set completeness is not mechanically checkable
  from the routing contract alone.** Worth exploring for `rmso.5`/`rmso.6`
  design work: either surface the full canonical label enumeration for
  the relevant category directly in the instruction (closer to Arm C's
  parity fix for permission questions), or add a mechanical
  cross-check between the model's claimed scope and the closed-world
  vocabulary's full membership for common "any of these classes"
  question phrasings.

## Complete provider accounting

- Output: `.tmp/rmso-live-20260720-v3` (not preserved; run artifacts are
  regenerated per invocation, same as prior spikes)
- Model: DeepSeek v4 Flash, both arms
- Locked design: `testdata/benchmark/rmso_eval_lock_v3.json`
  (`template-routed-vs-authored-v3`)
- Total spend: USD 0.218496
- Active reservations at completion: USD 0
- Provider-policy violations: 0
- Missing/unattributed attempts: 0
- Arm C: 101 provider calls, `create_souffle_arm` (`c-souffle`),
  cost USD 0.120435, `test_souffle_arm.py` regression evidence (all green)
- Arm T: 101 provider calls, `create_template_arm` (`t-template`),
  cost USD 0.098061, `test_template_arm.py` regression evidence (all green)
- Both arms live over the same EDB/IDB layers, with different
  engine-facing layers (bundled rule packs, ad-hoc Datalog authoring for
  C; locally proven template pack for T) - **locally proven today**
  (the 51 green tests execute Souffle through this exact lifecycle).
