# pydexpi-datalog-1

Prototype workspace for deterministic P&ID QA over DEXPI source files (version 1.3)

The OSS version is intended to work both as a standalone CLI and as a set of
small Python library modules that users can integrate into their own workflows.

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
| CLI product surface | `pydexpi_datalog/cli.py` | Parses arguments and delegates to workflow/library entry points. |
| OSS workflow policy | `pydexpi_datalog/workflow_policy.py`, `pydexpi_datalog/manifest.py` | Enforces one source file per run and BYOK model access assumptions. |
| DEXPI extraction and base facts | `pydexpi_datalog/export_facts.py`, `pydexpi_datalog/pipeline.py` | Uses `pyDEXPI` to build the full graph, then exports `graph_facts.json`. |
| Derived graph semantics | `pydexpi_datalog/derive_graph_semantics.py`, `pydexpi_datalog/datalog/idb/` | Builds `graph_facts.dl` and `derived_graph_semantics.dl`. |
| Deterministic queries | `pydexpi_datalog/query_derived_graph.py`, `queries/corpus/` | Runs supported QA queries over derived graph semantics. |
| Rule and review compatibility | `pydexpi_datalog/rule_evaluation.py`, `pydexpi_datalog/review_only.py`, `pydexpi_datalog/patch_proposals.py` | Legacy JSON rule and patch-proposal path retained for compatibility while graph-mirrored facts become the main model. |
| Legacy XML normalization | `pydexpi_datalog/legacy_xml_normalization.py`, `pydexpi_datalog/cache_execution.py` | XML-direct normalization used only by dry-run/review compatibility paths; it is not the primary internal model. |
| Logic requests and model access | `pydexpi_datalog/logic_requests.py`, `pydexpi_datalog/model_access.py` | Routes BYOK LLM-assisted logic requests while deterministic execution remains the answer source. |
| Artifacts and run state | `pydexpi_datalog/artifact_set.py`, `pydexpi_datalog/validation_state.py`, `pydexpi_datalog/suppressions.py` | Persists inspectable outputs, validation state, and suppressions. |
| Public library seams | `pydexpi_datalog/__init__.py`, `pydexpi_datalog/pipeline.py` | Exposes reusable stages for callers that do not want to shell out to the CLI. |

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
