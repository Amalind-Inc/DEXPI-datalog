# pydexpi-datalog-1

Prototype workspace for a manifest-driven dry-run pipeline over DEXPI XML.

## Current command

```bash
python3 -m pydexpi_datalog dry-run path/to/manifest.json
```

## Current test command

```bash
python3 -m unittest discover -s tests
```

## Verifier substrate

The verifier sits on top of DEXPI 1.3 source input, `pyDEXPI` full-graph
extraction, graph-mirrored fact export, and derived Souffle graph semantics.

```bash
./.venv/bin/python -m pydexpi_datalog export-facts \
  "TrainingTestCases/dexpi 1.3/example pids/E06 Pump, HeatExchanger, Nozzles Connected With PNS/E06V01-VER.EX01.xml" \
  --fixture-id e06-natural \
  --output-dir /tmp/pydexpi-export-facts

./.venv/bin/python -m pydexpi_datalog derive-graph-semantics \
  /tmp/pydexpi-export-facts/e06-natural/graph_facts.json \
  --output-dir /tmp/pydexpi-derived-graph-semantics
```
