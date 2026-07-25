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

## Setup

Requires Python 3.12+ (developed and tested on 3.14) and
[Souffle](https://souffle-lang.github.io/) on `PATH` for rule evaluation.

```bash
git submodule update --init --recursive   # pyDEXPI + DEXPI TrainingTestCases
python3 -m venv .venv
.venv/bin/pip install -e ./pyDEXPI         # not on PyPI; vendored as a submodule
.venv/bin/pip install -e ".[dev]"
```

## Current command

```bash
python3 -m pydexpi_datalog dry-run path/to/manifest.json
```

## Validation

```bash
.venv/bin/ruff check .                                    # lint
PYDEXPI_QA_PROVIDER=scripted .venv/bin/python -m pytest   # every test
```

`pytest` runs the whole suite, benchmark included, which takes about ten
minutes. For the edit loop, deselect the slow half explicitly:

```bash
PYDEXPI_QA_PROVIDER=scripted .venv/bin/python -m pytest -m "not slow"
```

That reports how many tests it deselected, so the slow suite is skipped by
choice rather than by accident. `PYDEXPI_QA_PROVIDER=scripted` pins the
deterministic zero-LLM provider so no test reaches a real model.

Configuration lives in `pyproject.toml`; no `PYTHONPATH` is needed. Do not
use `python -m unittest discover`: it collects only `unittest`-style tests
and silently ignores the pytest-style ones.

## Running the web UI

The web UI is a Next.js frontend backed by a FastAPI server. You will need an
LLM provider credential (OpenAI, OpenRouter, Anthropic, or Gemini) to use
logic requests — store it in a `.env` file that the frontend reads at startup.

**Start the backend:**

```bash
PYDEXPI_DEPLOYMENT_PROFILE=local PYTHONPATH=. PYDEXPI_REVIEW_ARTIFACT_ROOT=.tmp/review-sessions \
  .venv/bin/python -m uvicorn pydexpi_datalog.web.asgi:app \
  --host 127.0.0.1 --port 8000
```

`PYDEXPI_DEPLOYMENT_PROFILE` has no default and the server will not start
without it. `local` keeps every artifact on this machine with no accounts and
no sign-in surface at all (ADR 0016).

**Start the frontend** (separate terminal):

```bash
cd frontend
npm run dev
```

Then open `http://localhost:3000` in a browser.

### Running the hosted profile

The hosted profile signs users in and scopes every review session, artifact,
and authored rule pack to the signed-in account. Sign-in is
[Better Auth](https://better-auth.com) inside the Next app; the Python backend
is a resource server that verifies the JWT against the JWKS Next publishes, so
no account data or password ever reaches Python.

A hosted deployment keeps nothing on the instance. The session index lives in
a shared [libSQL](https://turso.tech/libsql) database and review artifacts
live in an S3-compatible bucket, so both survive a redeploy and are the same
for every instance. libSQL is SQLite's own dialect over a network: one schema
and one migration set serve both profiles, which is why the local path cannot
rot into a demo while hosted grows features.

Install the extras, create the account tables once, then start both processes:

```bash
pip install -e ".[hosted]"      # libsql + boto3; the local profile needs neither

export PYDEXPI_DEPLOYMENT_PROFILE=hosted
export BETTER_AUTH_URL=http://localhost:3000
export BETTER_AUTH_SECRET="$(openssl rand -base64 32)"   # required in hosted
export PYDEXPI_BYOK_SECRET="$(openssl rand -base64 32)"  # encrypts saved keys

(cd frontend && node scripts/migrate-auth.mjs)

# A libSQL database. Turso hosts them; this runs one locally.
docker run -d -p 8080:8080 ghcr.io/tursodatabase/libsql-server:latest

# An S3-compatible bucket. Any provider works; this runs MinIO locally.
docker run -d -p 9000:9000 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
  quay.io/minio/minio:latest server /data
# ...then create the bucket once, with `mc`, the console, or your provider.

# Backend: the three OIDC settings must agree with BETTER_AUTH_URL above.
PYTHONPATH=. \
  PYDEXPI_OIDC_ISSUER=$BETTER_AUTH_URL \
  PYDEXPI_OIDC_AUDIENCE=$BETTER_AUTH_URL \
  PYDEXPI_OIDC_JWKS_URL=$BETTER_AUTH_URL/api/auth/jwks \
  PYDEXPI_LIBSQL_URL=http://127.0.0.1:8080 \
  PYDEXPI_S3_BUCKET=pydexpi \
  PYDEXPI_S3_ENDPOINT_URL=http://127.0.0.1:9000 \
  PYDEXPI_S3_ACCESS_KEY_ID=minioadmin \
  PYDEXPI_S3_SECRET_ACCESS_KEY=minioadmin \
  .venv/bin/python -m uvicorn pydexpi_datalog.web.asgi:app --port 8000
```

Against managed services, set `PYDEXPI_LIBSQL_URL` to the Turso database URL
with `PYDEXPI_LIBSQL_AUTH_TOKEN`, and point the `PYDEXPI_S3_*` settings at
AWS, Cloudflare R2, or Backblaze B2. Both credentials are optional: a
`libsql-server` on a private network may not want a token, and a deployment
with an instance role has no S3 keys to give. The service, not this code,
decides whether it needs authenticating.

| Setting | Required | Meaning |
| --- | --- | --- |
| `PYDEXPI_LIBSQL_URL` | yes | Session catalog and provider-key database |
| `PYDEXPI_LIBSQL_AUTH_TOKEN` | no | Token, when the database wants one |
| `PYDEXPI_S3_BUCKET` | yes | Bucket holding review artifacts |
| `PYDEXPI_S3_ENDPOINT_URL` | no | Unset means AWS S3 itself |
| `PYDEXPI_S3_ACCESS_KEY_ID` | no | Unset uses boto3's credential chain |
| `PYDEXPI_S3_SECRET_ACCESS_KEY` | no | As above |
| `PYDEXPI_S3_REGION` | no | Defaults to `us-east-1` |
| `PYDEXPI_BYOK_SECRET` | yes | Encrypts saved model credentials |

The backend refuses to start if the OIDC settings, `PYDEXPI_LIBSQL_URL`,
`PYDEXPI_S3_BUCKET`, or `PYDEXPI_BYOK_SECRET` are missing, rather than coming
up unauthenticated, writing sessions and artifacts onto a disk the next
redeploy throws away, or storing a user's model credential in the clear.
Artifact downloads are handed out as presigned URLs, so bytes travel from the
bucket to the browser without passing through the API.

### Saved model credentials

The hosted profile stores each signed-in user's model provider key encrypted
in the shared database, so a key entered on one device is there on the next
(ADR 0014). Generate the secret once and set it identically on every
instance -- a key saved by one instance must decrypt on the others:

```bash
export PYDEXPI_BYOK_SECRET="$(openssl rand -base64 32)"
```

Losing it is not a data-loss event: every user simply re-enters their key.
Rotating it has the same effect, and saved credentials report that they no
longer decrypt rather than failing quietly.

The local profile stores no credentials at all. Keys stay in the browser, as
ADR 0014 describes, and `/api/provider-keys` answers 404 there on purpose.

To check a hosted deployment really does isolate two accounts:

```bash
.venv/bin/python scripts/hosted_auth_smoke.py
```

Running the test suite under the hosted profile needs both services;
`tests/conftest.py` prints the commands if either is missing.

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
