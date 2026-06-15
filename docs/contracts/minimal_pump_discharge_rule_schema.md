# Minimal Pump Discharge Rule Schema

This schema is intentionally narrow. It exists only for the first tracer-bullet
pump discharge-path rule family and is not a general-purpose verifier rule
language.

## Architectural position

This YAML surface sits above two lower layers:

1. the persisted graph-mirrored base fact layer from
   [Graph-to-Facts Contract](./graph_to_facts.md)
2. the derived Souffle classification and utility predicates from
   [Derived Graph Semantics Contract](./derived_graph_semantics.md)

The pump discharge YAML does not replace those layers. It depends on them.

## Scope

The current YAML surface is limited to discharge-path rules rooted in real
DEXPI 1.3 pump examples from this repository.

## Allowed top-level fields

- `schema_version`
- `rule_family`
- `rule_id`
- `description`
- `applies_to`
- `require`
- `boundary_behavior`
- `severity`

## Required fields

- `rule_id`
- `applies_to.subject_class`
- `require.component_class`

## Current supported shape

```yaml
schema_version: 1
rule_family: pump_discharge_path
rule_id: pump_discharge_check_valve
description: >
  A centrifugal pump discharge path must contain a downstream check valve on
  the first unbranched downstream segment.
applies_to:
  subject_class: CentrifugalPump
  start_from: discharge_nozzle
  traversal_scope: first_unbranched_downstream_segment
require:
  component_class: CheckValve
  allow_intermediate_classes:
    - Pipe
    - PipeReducer
boundary_behavior:
  off_page: bounded_failure_off_page
  terminal_before_match: hard_violation
severity: hard_violation
```

## Notes

- This format is operator-facing YAML, not raw Datalog.
- Compilation currently produces Souffle-style facts for the minimal rule
  parameters.
- Generic graph classification and recursive traversal are not encoded in this
  YAML shape. They belong to the lower derived Souffle layers.
