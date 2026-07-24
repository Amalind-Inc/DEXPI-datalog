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
## Why Datalog over SQL?
The primary reason is that our data is not tabular. Instead,
it is graph-like. A lot of questions that we anticipate 
plant operators and process engineers asking require recursion.
SQL can perform recursion, but it is painful. We either change our
data to be tabular, which honestly doesn't make much sense or we
change our querying paradigm from that of a declaritive query language
to a logic programming one. 


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

## Running the web UI

The web UI is a Next.js frontend backed by a FastAPI server. You will need an
LLM provider credential (OpenAI, OpenRouter, Anthropic, or Gemini) to use
logic requests — store it in a `.env` file that the frontend reads at startup.

**Start the backend:**

```bash
PYTHONPATH=. PYDEXPI_REVIEW_ARTIFACT_ROOT=.tmp/review-sessions \
  .venv/bin/python -m uvicorn pydexpi_datalog.web.asgi:app \
  --host 127.0.0.1 --port 8000
```

**Start the frontend** (separate terminal):

```bash
cd frontend
npm run dev
```

Then open `http://localhost:3000` in a browser.

## End-to-end screenshot test

`frontend/screenshot.mjs` drives the full logic-request flow with Playwright
against the E06 training fixture (pump + heat exchanger P&ID). It uploads the
file, sends a natural-language question, confirms the generated Datalog, runs
it, and prints the evidence summary.

Prerequisites: backend running on port 8000, frontend running on port 3000,
and an LLM provider configured in the frontend `.env`.

```bash
cd frontend
node screenshot.mjs
```

Screenshots are written to `frontend/03-confirmation.png` (authored-rule /
direction-review confirmation surfaces when present) and
`frontend/04-after-run.png` (after the grounded answer appears). Read-only
template and temporary generated-query execution no longer pause for
confirmation.

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
