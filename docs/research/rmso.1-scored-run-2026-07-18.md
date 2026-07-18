# rmso.1 scored run — 2026-07-18

## Result

**Formal protocol status: `INCOMPLETE` (invalid live configuration/accounting).**

**Diagnostic decision if the invalidity is ignored: `NO-GO / rethink`.** Neither arm
qualified under the pre-registered all-nine rule. Arm A earned 0/9 grounded-answer
credits; Arm B earned 5/9.

The completed run is preserved locally at
`.tmp/rmso-live-20260718-scored-03`. It must not be overwritten or treated as a valid
GO/NO-GO run. The two earlier infrastructure-invalid attempts remain at `scored-01`
(relative Harbor paths; no model calls) and `scored-02` (OpenRouter HTTP 402; no
completions and zero spend).

## Frozen run

- Lock: `testdata/benchmark/rmso_eval_lock.json`
- Model: `deepseek/deepseek-v4-flash`
- Arms: `a-agentic:deepseek` and `c-souffle:deepseek`
- Episodes: 9 per arm, sequential, one episode per entry
- Episode limit: 300 seconds; verifier limit: 60 seconds
- Output limit requested: 8,192 completion tokens per call
- Cumulative spend cap: USD 10
- Started: `2026-07-18T06:45:11.654449+00:00`
- Completed: `2026-07-18T09:00:22.896660+00:00`

## Diagnostic arm outcomes

| Entry | Arm A credit | Arm B credit | Arm B faithfulness |
| --- | ---: | ---: | --- |
| `ha-e03-pump-p4713-retrieval` | 0 | 1 | not applicable |
| `hq-nozzle-piping-attachment-small` | 0 | 0 | no final program (timeout) |
| `hq-nozzle-piping-attachment-large` | 0 | 1 | passed |
| `hq-valve-monitoring-reachability-small` | 0 | 0 | no final program (timeout) |
| `hq-valve-monitoring-reachability-large` | 0 | 0 | no final program (timeout) |
| `hq-equipment-pump-connectivity-small` | 0 | 1 | passed |
| `hq-equipment-pump-connectivity-large` | 0 | 0 | no final program (timeout) |
| `hq-permission-defeasible-control-small` | 0 | 1 | correct abstention; no program required |
| `hq-permission-defeasible-control-large` | 0 | 1 | correct abstention; no program required |

Arm A timed out on six entries. Its shallow answer was rejected by the audit-trace gate,
and both permission-control submissions were malformed against the benchmark wire shape,
so none of its nine answers earned full credit. Arm B timed out on four entries. Its five
credited answers were trace-safe; both applicable credited core programs passed the
mechanical cross-size/counterfactual faithfulness gate, and both policy controls abstained
correctly.

Diagnostic aggregates:

| Metric | Arm A | Arm B |
| --- | ---: | ---: |
| Grounded-answer credit | 0/9 | 5/9 |
| Trace-safe credited answers | 0 | 5 |
| Episode timeouts | 6 | 4 |
| Input tokens reported by episodes | 2,628,308 | 2,070,541 |
| Output tokens reported by episodes | 94,024 | 98,173 |
| Episode wall time | 2,061.63 s | 1,957.92 s |

The all-nine qualification rule therefore rejects both arms. H1 did not hold across the
core slice, H2 did not hold because Arm B did not qualify, and no arm qualified for an H3
claim. Arm B's two correct abstentions are positive diagnostic evidence but cannot rescue
qualification.

## Why the formal status is `INCOMPLETE`

The pre-registered protocol makes missing provider cost incomplete and makes a provider
ineligible if it cannot enforce the 8,192-token output ceiling.

The gateway archived 270 requests, 267 HTTP-200 provider responses, and four error
artifacts. Three requests ended without provider responses (one read timeout and two
connection resets), so their final provider cost is unknown. The benchmark reports also
contain `cost_usd: null` per episode, preventing the required per-arm and per-episode cost
accounting.

For the 267 archived responses, provider-reported cost sums to USD **0.29847346716**.
The live summary reports USD **0.29654104212**. The exact USD **0.00193242504** difference
is call 92: the provider returned 8,193 completion tokens, one above the locked ceiling.
The gateway correctly rejected the response but did not settle its billed cost into the
summary counter. Because three response-less requests may also have been billed, even the
larger archived-response sum is only a known minimum, not a complete run cost.

Resolved providers across the 267 responses were StreamLake (185), GMICloud (75), and
DeepInfra (7), all serving the pinned V4 Flash model. The requested USD 10 cap was never
close to binding, but incomplete settlement means the summary counter is not sufficient
cost evidence.

## Required follow-up before another scored run

1. Make rejected-but-billed successful responses settle reported cost before failing the
   eligibility gate.
2. Define and test fail-closed accounting for upstream timeouts/resets; a run with unknown
   paid-call cost cannot complete.
3. Persist per-call episode/arm attribution and generate non-null per-episode and per-arm
   costs from gateway artifacts.
4. Fail the run summary (not merely the affected episode) when the provider violates the
   output ceiling or complete cost accounting is unavailable.
5. Revalidate provider enforcement before requesting product-owner approval for any new
   scored replacement. Do not reuse any existing output directory.

The separate post-run harness redesign and its interpretation boundary are recorded in
`rmso.1-agent-redesign-2026-07-18.md`.
