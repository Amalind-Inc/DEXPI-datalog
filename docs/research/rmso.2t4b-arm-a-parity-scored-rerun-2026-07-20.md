# rmso.2t4b — Scored rerun after Arm A parity fixes (32fw, kiir)

Date: 2026-07-20
Bead: `pydexpi-datalog-1-2t4b`

## Result

**Run status `COMPLETE`, formal accounting `COMPLETE`, zero invalid reasons.
Arm A qualified 9/9. Arm C did not (4/9). Locked decision-table row
(Arm A yes, Arm C no): "Python-direct wins; do not justify Souffle" — on this
slice, with the interpretation limits below.**

- Arm A, graph-direct Python analysis: **9/9** (was 4/9 → 6/9 → 9/9).
- Arm C, generate/execute/revise Soufflé: **4/9** (was 5/9 → 8/9 → 4/9).

Same locked `graph-direct-vs-souffle-v2` design, lock, model
(`deepseek/deepseek-v4-flash`), nine-entry slice, budgets, and fail-closed
accounting as the two prior scored runs. Between run 04 and this run, only
Arm A changed (32fw checkpoint auto-completion; kiir mechanical abstention
packaging). **Arm C was byte-for-byte frozen as the control.**

## Provider accounting

- Output: `.tmp/rmso-live-20260720-redesigned-05`
- KIRA checkout: `652dacbf14d29ea93a83c496ee91e0e5ba286721`
- Total paid cost: **USD 0.20009960404** (cap USD 10)
  - Arm A: USD 0.03371365028 → **USD 0.00375 per credit**
  - Arm C: USD 0.16638595376 → USD 0.04160 per credit
- Accounting complete on every episode; zero unknown-cost calls; zero policy
  violations. Wall time 40m40s.

## Per-episode matrix

| Question | Arm A | Arm C |
| --- | --- | --- |
| ha-e03-pump-p4713-retrieval | 1.0 (52s) | 0.0 `verification_gate_rejected` (26s) |
| hq-equipment-pump-connectivity-large | 1.0 (93s) | 0.0 `verification_gate_rejected` |
| hq-equipment-pump-connectivity-small | 1.0 (122s) | 1.0 |
| hq-nozzle-piping-attachment-large | 1.0 (91s) | 1.0 |
| hq-nozzle-piping-attachment-small | 1.0 (74s) | 1.0 |
| hq-permission-defeasible-control-large | 1.0 (49s) | 1.0 |
| hq-permission-defeasible-control-small | 1.0 (41s) | 0.0 `verification_gate_rejected` |
| hq-valve-monitoring-reachability-large | 1.0 (89s) | 0.0 `faithfulness_gate_failed` |
| hq-valve-monitoring-reachability-small | 1.0 (111s) | 0.0 `faithfulness_gate_failed` |

## The Arm A parity fixes worked exactly as designed

Every prior Arm A failure class is gone. The valve-monitoring-large episode —
lost last run to exploration past a correct checkpoint — completed in 89
seconds. Both permission controls completed in under 50 seconds through the
mechanical abstention helper. Total Arm A agent time for all nine episodes:
12 minutes. Nine for nine, every support trace mechanically safe, at a cost
of about a third of a US cent per credited answer.

## Arm C failure taxonomy (run 05)

Arm C ran unmodified; its regression from 8/9 to 4/9 decomposes as:

1. **ha-e03 — upstream KIRA parser crash (infrastructure).** The model emitted
   `commands` entries as strings; KIRA's `_parse_tool_calls` does
   `cmd.get("keystrokes")` and crashed with `AttributeError: 'str' object has
   no attribute 'get'` before any command executed (26s, 0 commands). Same
   defect class as the parser crash recorded in the rmso.8 forensics.
2. **hq-permission-defeasible-control-small — tool-call parse starvation
   (infrastructure/model-format boundary).** Every model tool call failed
   KIRA's argument parser; the agent produced dozens of turns with zero
   executed commands, never wrote the answer file, and the checkpoint cutoff
   force-finalized cleanly. The identical control passed in 53s for Arm C
   in the same run (large variant).
3. **hq-equipment-pump-connectivity-large — genuine failure to converge.**
   18 executed commands, never reached an accepted checkpoint before cutoff.
4. **Both valve-monitoring entries — genuine authoring failures, correctly
   caught.** Opposite direction from run 04: the authored program
   under-approximated (0 witnesses on probes expecting 8 and 1). The
   faithfulness gate rejected both.

## Interpretation

Formally, the locked table now reads: **Python-direct wins on this slice; the
Soufflé arm is not justified by these results.**

Three interpretation limits before treating that as an architecture verdict:

- **This is a third pass over the same nine questions.** The rerun protocol
  itself says a product claim requires a fresh SME-certified holdout slice.
  Arm A's 9/9 in particular now needs confirmation on unseen questions.
- **Arm C's cross-run variance (5/9 → 8/9 → 4/9 with zero code changes in the
  last transition) is itself a finding.** The engine-mediated arm has more
  failure surface: longer episodes, more commands, more tool-call parsing
  exposure, and a program-authoring step whose faithfulness varies run to
  run on a cheap model. Three of its five failures this run were upstream
  KIRA parse defects, which its command-heavy style is disproportionately
  exposed to.
- **Cost now favors Arm A by ~11x per credit** (USD 0.0037 vs 0.0416), the
  reverse of run 04. With both arms mechanically sound, the shorter
  graph-direct episodes are structurally cheaper.

What is genuinely settled: on this slice, with lifecycle mechanics equalized,
a cheap model **can** reliably author correct stdlib-Python graph analyses
under a five-minute replayable-audit contract — and could not reliably author
faithful Soufflé for the hardest (valve-reachability) family in any of the
three runs.

## Recommended follow-ups

1. Feed the wayfinder (rmso map): the H2 answer on this slice is negative —
   execution capability was not required; direct authored analysis with
   mechanical packaging qualified. Route the router/loop design work (rmso.5,
   rmso.6) accordingly.
2. A fresh SME-certified holdout slice before any product-level claim
   (already mandated by the rerun protocol).
3. Optional: report the two KIRA parse defects upstream (crash on string
   commands; argument-parse starvation); they bound every arm run under
   Terminus-KIRA.

## Artifacts

- Run root: `.tmp/rmso-live-20260720-redesigned-05/`
- Summary: `rmso_live_summary.json` (status COMPLETE, formal COMPLETE)
- Arm reports: `arm-a/benchmark_report.json`, `arm-c/benchmark_report.json`
- e03 crash traceback: preserved in the trial `result.json` under the arm-c
  harbor job directory
