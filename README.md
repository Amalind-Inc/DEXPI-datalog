# DEXPI-datalog

An open source tool for deterministic P&ID QA over DEXPI source files (version 1.3)

This OSS version is intended to work both as a standalone CLI/TUI/GUI tool and as a set of
small Python library modules that users can integrate into their own workflows.

`DEXPI-datalog` is a precursor to further professional and enterprise grade tools that
`Amalind Inc.` plans to produce. This tool is simply a demo tool, and I would not recommend
using it as a way to verify the validity of production P&ID documents. Try this out, see if 
you like it, and let us know what you like, don't like, and what you would change. 

## OSS scope

OSS supports one DEXPI source file per run, but a run may target a selected
source node or affected connected subgraph inside that file. This keeps the
single-file product boundary explicit while leaving room for future multi-page
or professional workflows.

LLM-assisted logic requests are part of the OSS scope, but model access is BYOK:
users supply their own provider credentials. Managed model access, app-managed
credits, batch/multi-file workflows, and advanced professional techniques are
future product work rather than assumptions in the OSS pipeline.

## Pipeline

The deterministic verifier and logic-request workflow sit on this substrate:

```text
DEXPI source file
  -> pyDEXPI full graph
  -> canonical base fact layer / graph_facts.json
  -> graph-mirrored fact vocabulary / graph_facts.dl
  -> derived graph semantics / derived_graph_semantics.dl
  -> rule evaluation, deterministic queries, or logic-request execution
  -> findings, diagnostics, and persisted artifacts
```

`pyDEXPI` owns DEXPI XML-to-graph extraction. This repository owns the
graph-to-facts export, derived Souffle graph semantics, rule/query evaluation,
logic-request orchestration, and persisted artifacts. We plan to implement
our own DEXPI XML to facts engine, however at this time we use `pyDEXPI`.

## Library and CLI use

The CLI is a thin product surface over reusable Python workflows. OSS
users who want the whole flow can run commands; users who want only part of the
pipeline should be able to import the relevant library seam, such as fact export,
derived graph semantics, rule evaluation, or logic-request orchestration.

The architectural rule is:

```text
Core modules do engineering work.
Workflow modules enforce product policy.
CLI modules parse arguments and write or print artifacts.
```

## Project structure

The codebase is organized around P&ID QA pipeline seams rather than one large
command module:

| Seam | Where to look | Notes |
| --- | --- | --- |
| CLI product surface | `pydexpi_datalog/cli/` | Parses arguments and delegates to workflow/library entry points. |
| OSS workflow policy | `pydexpi_datalog/workflow/` | Manifests, dry-run orchestration, run locks, and one-source-file/BYOK policy. |
| DEXPI extraction and base facts | `pydexpi_datalog/export/` | Uses `pyDEXPI` to build the full graph, then exports `graph_facts.json`. |
| Derived graph semantics | `pydexpi_datalog/semantics/` | Builds `graph_facts.dl` and `derived_graph_semantics.dl`; reusable IDB lives under `semantics/datalog/`. |
| Verification | `pydexpi_datalog/verification/` | Deterministic fixture verification over graph-mirrored facts and derived semantics. |
| Logic requests and model access | `pydexpi_datalog/llm/` | Routes BYOK LLM-assisted logic requests while deterministic execution remains the answer source. |
| Artifacts and schemas | `pydexpi_datalog/artifacts/` | Persists inspectable outputs and validates result schemas. |
| Public library seams | `pydexpi_datalog/__init__.py`, `pydexpi_datalog/workflow/pipeline.py` | Exposes reusable stages for callers that do not want to shell out to the CLI. |

Tests mirror the same seams under `tests/`: `workflow/`, `export/`,
`semantics/`, `verification/`, `llm/`, and `artifacts/`.

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
These commands show the current explicit artifact seam from a DEXPI source file
to `graph_facts.json`, then from `graph_facts.json` to executable derived graph
semantics.

```bash
./.venv/bin/python -m pydexpi_datalog export-facts \
  "TrainingTestCases/dexpi 1.3/example pids/E06 Pump, HeatExchanger, Nozzles Connected With PNS/E06V01-VER.EX01.xml" \
  --fixture-id e06-natural \
  --output-dir /tmp/pydexpi-export-facts

./.venv/bin/python -m pydexpi_datalog derive-graph-semantics \
  /tmp/pydexpi-export-facts/e06-natural/graph_facts.json \
  --output-dir /tmp/pydexpi-derived-graph-semantics
```
