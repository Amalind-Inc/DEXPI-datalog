# rmso.1 redesigned paid attempt 02 — 2026-07-18

## Status

**Formal status: `INCOMPLETE` — infrastructure/scoring-adapter invalid.**

The attempt is preserved at `.tmp/rmso-live-20260718-redesigned-02`. It is not
evaluation evidence, must not be overwritten or resumed, and produced no architecture
verdict.

## What happened

The paid replacement was explicitly authorized and launched in a fresh directory with
`rmso_eval_lock_v2.json` from commit `fa8038ca`. The pinned KIRA checkout was
`652dacbf`, and the preflight checks for the corrected live OpenRouter provider shape
passed.

The provider gateway remained healthy. Arm A completed three episodes with persisted
verifier reward 1.0: the shallow retrieval, small nozzle, and large nozzle entries. The
small reachability episode failed inside KIRA while parsing a model-produced terminal
command (`AttributeError: 'str' object has no attribute 'get'`).

The large reachability episode exposed a scoring-adapter defect. Harbor persisted both:

- `verifier_result.rewards.reward = 1.0`; and
- `exception_info.exception_type = "AgentTimeoutError"` after the 300-second agent
  timeout.

The RMSO protocol requires a timed-out episode to score zero. The local Harbor artifact
adapter read `reward.txt` but did not inspect the trial's `result.json`, so it could have
credited the partial verifier result. The run was manually stopped before further paid
work. This is a scoring-boundary defect, not valid model or architecture evidence.

## Preserved accounting

- Provider request reservations: 74
- Settled provider responses: 73 HTTP 200
- Unsettled reservations at stop: 1
- Settled, known paid cost: USD 0.0665550122
- Completion tokens in settled responses: 45,883 total; maximum 3,782 on one call
- Providers in settled responses: GMICloud 42, StreamLake 29, DeepInfra 2
- Provider policy violations: 0
- Gateway response errors before stop: 0
- Completed benchmark reports: 0
- Summary: `status=failed`, `formal_status=INCOMPLETE`, `KeyboardInterrupt`

The USD 0.0665550122 value is the settled known minimum, not a claim of complete total
cost. The interrupt left call 74 reserved without a response artifact, so the summary
correctly includes `unsettled_provider_reservation` and `execution_failure`. No result
from this attempt may be used in the formal comparison.

## Corrective action

The Harbor artifact adapter now treats any persisted agent-level exception as an episode
failure that overrides a partial verifier reward. `AgentTimeoutError` additionally sets
the episode's `timed_out` usage flag. A regression test reproduces the contradictory
Harbor artifacts (`reward.txt = 1` plus `AgentTimeoutError`) and requires reward 0.

Any replacement requires another explicit approval and another never-used output
directory. It must not resume or reuse this attempt.
