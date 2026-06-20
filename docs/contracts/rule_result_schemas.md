# Rule Result Schemas

These result schemas are the stable machine-readable reporting surface for the
first pump discharge-path rule family.

## Result types

- `pass`
- `hard_violation`
- `bounded_failure_off_page`
- `evaluation_diagnostic`

## Shared required fields

Every result artifact currently requires:

- `schema_version`
- `result_type`
- `rule_id`
- `message`
- `subject.pump_id`
- `subject.discharge_nozzle_id`
- `evidence.traversed_objects`
- `evidence.traversed_edges`
- `evidence.boundary.kind`
- `evidence.boundary.object_id`

## Shared evidence spine

All four result shapes use the same evidence backbone:

- `subject`
  - identifies the pump and discharge nozzle context
- `evidence.traversed_objects`
  - ordered path objects with object id and class
- `evidence.traversed_edges`
  - ordered traversed edges using `source_id`, `target_id`, `edge_key`
- `evidence.boundary`
  - the path stop or outcome boundary that explains the result
- `evidence.matched_objects`
  - the matched downstream component objects, if any

## Result-shape notes

### `pass`

- boundary kind is `matched_required_component`
- matched object is the required downstream component that satisfied the rule

### `hard_violation`

- boundary kind is the first local boundary reached before satisfaction
- matched objects are empty

### `bounded_failure_off_page`

- boundary kind is `off_page_connector`
- includes `evidence.uncertainty_text`

### `evaluation_diagnostic`

- boundary kind records the unresolved evaluation cause, such as
  `unresolved_discharge_nozzle`
- no standards finding is implied

## Checked-in examples

- `testdata/report_examples/pass.json`
- `testdata/report_examples/hard_violation.json`
- `testdata/report_examples/bounded_failure_off_page.json`
- `testdata/report_examples/evaluation_diagnostic.json`
