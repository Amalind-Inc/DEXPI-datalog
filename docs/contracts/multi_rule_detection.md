# Multi-Rule Detection

The verifier now supports running multiple rules against the same fixture set in
one detection pass.

## Current scope

- multiple rules can execute in one run
- multiple results can be reported for the same fixture
- overlapping graph regions can produce more than one finding

## Deferred scope

Hypothetical edit application and post-edit re-evaluation are explicitly
deferred.

The current output model records:

- `fixture_id`
- `results`
- `post_edit_reevaluation`

For multi-rule detection runs, `post_edit_reevaluation` is currently always
`deferred`.

## Current overlap example

The checked-in overlap example is:

- `testdata/verifier_suite/multi_rule_manifest.json`

It runs:

- `pump_discharge_check_valve`
- `pump_discharge_not_terminal_nozzle`

against the same natural `E06` discharge-path fixture and emits two
deterministic `hard_violation` results over the same discharge region.
