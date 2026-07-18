# rmso.1 redesigned scored run — 2026-07-18

## Result

**Run status: `COMPLETE`. Pre-registered architecture result: `NO-GO / rethink`.**

The explicitly authorized matrix ran every one of the nine locked entries once through
both redesigned arms. Neither arm qualified under the frozen all-nine rule:

- Arm A, graph-direct Python analysis: **4/9 corrected credits**.
- Arm C, generate/execute/revise Soufflé: **5/9 credits**.

The decision table requires 9/9 for qualification. Because both arms failed, cost and
partial-score differences cannot rescue either architecture or justify further product
investment from this slice.

## Complete provider accounting

- Output: `.tmp/rmso-live-20260718-redesigned-03`
- Locked design: `graph-direct-vs-souffle-v2`
- Model: `deepseek/deepseek-v4-flash`
- Episodes: 18 (9 per arm), sequential, no episode retry
- Provider requests: 249
- Provider responses: 249 HTTP 200
- Unknown-cost calls: 0
- Active reservations at completion: USD 0
- Provider-policy violations: 0
- Missing-attribution attempts: 0
- Spend-cap-blocked attempts: 0
- Total paid cost: **USD 0.24677421676000016**
- Arm A: 101 calls, USD 0.0795806204
- Arm C: 148 calls, USD 0.16719359636
- Providers: GMICloud 230, DeepInfra 10, StreamLake 9

The executor summary is `status=complete`, `formal_status=COMPLETE`, with an empty
`invalid_reasons` list and complete accounting for all 18 episodes.

## Mechanically corrected episode results

| Entry | Arm A | Arm C |
| --- | ---: | ---: |
| Shallow P-4713 retrieval | 1 | 1 |
| Nozzle attachment, small | 0 | 1 |
| Nozzle attachment, large | 0 | 1 |
| Valve reachability, small | 1 | 0 |
| Valve reachability, large | 1 | 0 |
| Equipment connectivity, small | 1 | 0 |
| Equipment connectivity, large | 0 | 0 |
| Permission/defeasible control, small | 0 | 1 |
| Permission/defeasible control, large | 0 | 1 |
| **Total** | **4/9** | **5/9** |

Arm A failed both nozzle questions through agent timeout, failed large equipment through
a KIRA `AttributeError`, and produced malformed final submissions on both policy controls.
Its shallow, both reachability, and small equipment answers were exact and trace-safe.

Arm C's shallow and both nozzle answers were exact and trace-safe. Both nozzle programs
also passed all frozen paired-drawing and counterfactual faithfulness probes. Both
reachability and both equipment episodes timed out and receive zero. Arm C correctly
abstained, with mechanically safe policy support, on both permission/defeasible controls.

## Timer-adapter correction

The live executor's initially written reports were Arm A 2/9 and Arm C 5/9. The Arm A
small and large reachability episodes were marked `timed_out` by the outer Python
subprocess guard, even though Harbor persisted exception-free final submissions and
verifier reward 1. Their Harbor agent-execution intervals were respectively:

- 284.830618 seconds; and
- 297.150189 seconds.

Both are inside the protocol's five-minute interval measured from the first model call
through final submission. The outer guard had started earlier, during container setup,
and expired before Harbor finished verifier/finalization work. The frozen artifacts were
therefore regraded offline through the same answer replay, trace, and witness gates; no
model was called and no episode was retried. Corrected reports are preserved under
`.tmp/rmso-live-20260718-redesigned-03/posthoc-regrade`.

The process guard now allows the task's separate environment, agent, and verifier phase
budgets plus a bounded finalization grace. Harbor's task-level 300-second agent timeout
remains unchanged and continues to override any partial verifier reward. This prevents
container setup or post-submission grading from consuming the model's preregistered
reasoning interval.

The correction changes Arm A from 2/9 to 4/9 but does not change qualification or the
pre-registered `NO-GO / rethink` result.

## Interpretation

The redesigned comparison removed Arm A's raw-XML handicap and materially improved it,
but neither architecture was reliable enough for the frozen slice. Arm C demonstrated
faithful, executable Datalog on the nozzle family and sound abstention on both policy
controls. It did not complete either reachability or equipment family within five
minutes. Arm A solved both reachability cases but failed the nozzle family and both
policy controls.

This is evidence for narrower capability components, not for shipping either complete
reasoning path. Under the pre-registration, the engine does not earn a GO.

## Preserved artifacts

- Run summary: `.tmp/rmso-live-20260718-redesigned-03/rmso_live_summary.json`
- Original Arm A report: `.tmp/rmso-live-20260718-redesigned-03/arm-a/benchmark_report.json`
- Original Arm C report: `.tmp/rmso-live-20260718-redesigned-03/arm-c/benchmark_report.json`
- Corrected offline reports: `.tmp/rmso-live-20260718-redesigned-03/posthoc-regrade/`
- Exact provider request/response archive: `.tmp/rmso-live-20260718-redesigned-03/openrouter/`

The run directory is immutable evaluation evidence and must not be resumed, overwritten,
or relabeled as a different attempt.
