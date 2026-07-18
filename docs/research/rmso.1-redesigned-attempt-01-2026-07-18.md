# rmso.1 redesigned paid attempt 01 — 2026-07-18

## Status

**Formal status: `INCOMPLETE` — infrastructure-invalid.**

The attempt is preserved at `.tmp/rmso-live-20260718-redesigned-01`. It is not
evaluation evidence, must not be overwritten, and produced no architecture verdict.

## What happened

The paid replacement was explicitly authorized and launched with
`rmso_eval_lock_v2.json` from commit `afbc08ad`. The executor began Arm A and completed
the shallow episode with an API error, then began the small nozzle episode. Inspection of
the archived responses showed the same gateway rejection on every successful provider
response, so the run was manually stopped to avoid unnecessary paid calls.

OpenRouter returned resolved provider identity in the top-level `provider` field and in
`openrouter_metadata.endpoints.available[*].selected`. The new gateway validator expected
the earlier mocked `openrouter_metadata.selected_provider` field. It therefore settled
each reported billed cost correctly, then rejected an otherwise eligible response for
"missing" provider metadata.

This is a gateway compatibility defect, not model or task evidence.

## Preserved accounting

- Provider requests: 9
- Provider responses: 9 HTTP 200
- Unknown-cost calls: 0
- Known paid cost: USD 0.0019106756
- Completion tokens: 2,299 total; maximum 340 on one call
- Providers: GMICloud 4, DeepInfra 3, StreamLake 2
- Shallow entry: 5 calls, USD 0.001092986
- Small nozzle entry: 4 calls, USD 0.0008176896
- Completed benchmark reports: 0
- Summary: `status=failed`, `formal_status=INCOMPLETE`, `KeyboardInterrupt`

No output-ceiling, spend-cap, attribution, or unknown-cost failure occurred. All nine
reported costs were settled in the provider ledger before rejection.

## Corrective action

The gateway now accepts the observed top-level OpenRouter `provider` field while retaining
compatibility with the earlier `openrouter_metadata.selected_provider` shape and rejecting
missing or conflicting identities. A regression test reproduces the exact archived live
shape. Interrupted summaries also retain accounting/policy invalid reasons alongside the
execution interruption.

Any replacement requires another explicit approval and another never-used output
directory. It must not resume or reuse this attempt.
