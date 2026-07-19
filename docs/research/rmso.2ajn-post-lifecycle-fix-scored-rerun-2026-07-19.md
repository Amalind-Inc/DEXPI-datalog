# rmso.2ajn — Post-lifecycle-fix scored rerun of the preregistered matrix

Date: 2026-07-19
Bead: `pydexpi-datalog-1-2ajn`

## Result

**Run status: `COMPLETE`, formal accounting `COMPLETE`, zero invalid reasons.
Pre-registered architecture result: still `NO-GO / rethink` (neither arm 9/9),
but the margin moved decisively and the remaining failures are now fully
classified.**

- Arm A, graph-direct Python analysis: **6/9** corrected credits (was 4/9).
- Arm C, generate/execute/revise Soufflé: **8/9** credits (was 5/9).

This is the same locked `graph-direct-vs-souffle-v2` design, lock
(`testdata/benchmark/rmso_eval_lock_v2.json`), model
(`deepseek/deepseek-v4-flash`), nine-entry slice, budgets, and fail-closed
accounting as the 2026-07-18 redesigned run — executed after the Arm C
episode-lifecycle fixes landed (rmso.9 checkpoint auto-completion, rmso.10
wrap-proof receipt framing).

## Provider accounting

- Output: `.tmp/rmso-live-20260719-redesigned-04`
- KIRA checkout: `652dacbf14d29ea93a83c496ee91e0e5ba286721` (fresh re-clone)
- Episodes: 18 (9 per arm), sequential, no retry
- Accounting: complete for every episode; no unknown-cost calls; no policy
  violations; no spend-cap blocks
- Total paid cost: **USD 0.23370218856**
  - Arm A: USD 0.12002283364 (6 credits → USD 0.0200 per credit)
  - Arm C: USD 0.11367935492 (8 credits → USD 0.0142 per credit)
- Wall time: 51m45s end to end

## Per-episode matrix

| Question | Arm A | Arm C |
| --- | --- | --- |
| ha-e03-pump-p4713-retrieval | 1.0 | 1.0 |
| hq-equipment-pump-connectivity-large | 1.0 | 1.0 |
| hq-equipment-pump-connectivity-small | 1.0 | 1.0 |
| hq-nozzle-piping-attachment-large | 1.0 | 1.0 |
| hq-nozzle-piping-attachment-small | 1.0 | 1.0 |
| hq-permission-defeasible-control-large | 0.0 `malformed_submission` | 1.0 |
| hq-permission-defeasible-control-small | 0.0 `malformed_submission` | 1.0 |
| hq-valve-monitoring-reachability-large | 0.0 `verification_gate_rejected` | 0.0 `faithfulness_gate_failed` |
| hq-valve-monitoring-reachability-small | 1.0 | 1.0 |

## The lifecycle fixes worked

Every Arm C episode that previously failed as timeout-after-valid-checkpoint
flipped to full credit, exactly as the rmso.8 forensics predicted. No Arm C
episode in this run timed out, retried a provider call after an accepted
checkpoint, or lost a receipt to terminal wrapping. Arm C's episode cost is
now also *below* Arm A's despite executing an engine.

## The four remaining failures, classified

1. **Arm C, valve-monitoring large — genuine model failure, correctly
   caught.** The authored program used an over-broad valve label set. The
   counterfactual faithfulness probes rejected it: the small-size probe
   expected zero witnesses but the program produced one, and the large case
   emitted 11 witnesses against the 8 in ground truth. This is the
   faithfulness gate doing precisely its job; it is the only failure in the
   run attributable to model reasoning.

2. **Arm A, valve-monitoring large — missing lifecycle parity.** The agent
   produced a *correct* executed checkpoint (exact 8 witnesses; verifier
   reward 1; `analysis_replay.json` preserved), then kept exploring for 30
   model calls until `AgentTimeoutError` at 323s. Harbor's trial reward
   gate then rejected the episode. Root cause: `create_rmso_graph_direct_arm`
   uses the plain `TerminusKira` import path — the rmso.9 checkpoint
   auto-completion adapter is wired only into Arm C. This is the same defect
   class rmso.9 eliminated for Arm C.

3. **Arm A, both permission episodes — answer packaging, not judgment.** The
   model made the correct abstention judgment (`unanswerable`,
   `source_data_unavailable`) both times but serialized `witnesses` /
   `explanation` instead of `witness_ids` / `answer_text`. Arm C passed both
   permission controls because its abstention packaging is mechanical. The
   recurring lesson: every model-authored JSON surface eventually fails;
   every mechanically packaged surface holds.

## Interpretation against the locked decision table

Formally: Arm A no, Arm C no → `NO-GO / rethink`. Cost may not rescue either
arm under the locked rule.

Signal for the wayfinder (not a formal conclusion): Arm C now strictly
dominates Arm A — more credits (8 vs 6) at lower cost (USD 0.114 vs 0.120) —
and its single failure was a true authoring error that the mechanical gates
caught safely, while all three Arm A failures are harness/packaging defects
with known fixes. 17 of 18 episodes reached a semantically correct executed
conclusion or correct abstention; the benchmark's remaining gap to 9/9 is
concentrated in Arm A mechanics plus one Arm C authoring miss.

## Recommended follow-ups

1. **P1 — Arm A checkpoint parity:** wire the checkpoint-aware adapter (or an
   Arm A equivalent) into `create_rmso_graph_direct_arm` so a valid executed
   checkpoint auto-completes before the Harbor timeout.
2. **P1 — mechanical abstention packaging for Arm A:** the permission
   abstention answer should be checkpointed by a runner, not free-typed JSON.
3. After both land: rerun this slice once more. If Arm C also clears
   valve-monitoring large (prompt-side: the instruction already forbids
   over-approximation; this may simply be a per-run authoring variance), the
   decision table finally gets a clean read.

## Artifacts

- Run root: `.tmp/rmso-live-20260719-redesigned-04/`
- Summary: `.tmp/rmso-live-20260719-redesigned-04/rmso_live_summary.json`
- Arm reports: `arm-a/benchmark_report.json`, `arm-c/benchmark_report.json`
- Full OpenRouter ledger: `openrouter/` under the run root
