# Stable Verifier Command

The current stable product seam for the tracer-bullet verifier is:

```bash
./.venv/bin/python -m pydexpi_datalog verify-raw-fixture \
  "TrainingTestCases/dexpi 1.3/example pids/E06 Pump, HeatExchanger, Nozzles Connected With PNS/E06V01-VER.EX01.xml" \
  --output-dir /tmp/pydexpi-verify-e06
```

This command runs from one raw selected DEXPI XML input fixture to persisted
report artifacts.

## Persisted raw-input artifacts

For the command above, the output directory contains:

- `E06V01-VER.EX01.graph_facts.json`
- `E06V01-VER.EX01.result.json`

## Checked-in verifier examples

Passing example artifact:

- `fixtures/verifier_suite/expected/pass_c01_local_segment.json`

Failing example artifact:

- `fixtures/verifier_suite/expected/hard_violation_e06_natural.json`

## Fixture-suite command

For the broader tracer-bullet suite, the stable suite command is:

```bash
./.venv/bin/python -m pydexpi_datalog verify-suite \
  fixtures/verifier_suite/manifest.json \
  --output-dir /tmp/pydexpi-verify-suite
```

This is the persisted artifact seam that later slices build on.
