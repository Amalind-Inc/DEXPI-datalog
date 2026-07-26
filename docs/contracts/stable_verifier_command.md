# Stable Verifier Seams

Verification is not the foundational contract seam in this repository.
Verification sits on top of:

1. a DEXPI 1.3 source fixture
2. `pyDEXPI` full-graph extraction
3. graph-mirrored fact export
4. derived Souffle classification and graph utility layers

## Foundational seam

The foundational stable seam is the graph export flow:

```bash
./.venv/bin/python -m pydexpi_datalog export-facts \
  "TrainingTestCases/dexpi 1.3/example pids/E06 Pump, HeatExchanger, Nozzles Connected With PNS/E06V01-VER.EX01.xml" \
  --fixture-id e06-natural \
  --output-dir /tmp/portlog-export-facts
```

This command runs from one DEXPI 1.3 source fixture to persisted
graph-mirrored facts.

## Derived-logic seam

The next architectural seam is the derived Souffle layer that classifies edge
families and provides generic graph utility predicates. That layer is specified
separately in [Derived Graph Semantics Contract](./derived_graph_semantics.md).

## Verifier seam

The current stable verifier-facing command for the tracer-bullet workflow is:

```bash
./.venv/bin/python -m pydexpi_datalog verify-raw-fixture \
  "TrainingTestCases/dexpi 1.3/example pids/E06 Pump, HeatExchanger, Nozzles Connected With PNS/E06V01-VER.EX01.xml" \
  --output-dir /tmp/portlog-verify-e06
```

This command should be understood as a consumer of the lower seams, not as the
primary architectural center.

## Persisted verifier artifacts

For the command above, the output directory contains:

- `E06V01-VER.EX01.graph_facts.json`
- `E06V01-VER.EX01.derived_graph_semantics.dl`
- `E06V01-VER.EX01.result.json`

## Checked-in verifier examples

Passing example artifact:

- `testdata/verifier_suite/expected/pass_c01_local_segment.json`

Failing example artifact:

- `testdata/verifier_suite/expected/hard_violation_e06_natural.json`

## Fixture-suite command

For the broader tracer-bullet suite, the stable suite command is:

```bash
./.venv/bin/python -m pydexpi_datalog verify-suite \
  testdata/verifier_suite/manifest.json \
  --output-dir /tmp/portlog-verify-suite
```
