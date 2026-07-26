# PortLog

An open source tool for deterministic P&ID QA over DEXPI source files (version 1.3)

[![CI](https://github.com/Harborfield/portlog/actions/workflows/ci.yml/badge.svg)](https://github.com/Harborfield/portlog/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/Harborfield/portlog?label=release&sort=semver)](https://github.com/Harborfield/portlog/releases)

This OSS version is intended to work both as a standalone CLI/TUI/GUI tool and as a set of
small Python library modules that users can integrate into their own workflows.

`PortLog` is a precursor to further professional and enterprise grade tools that
`Harborfield` plans to produce. This tool is simply a demo tool, and I would not recommend
using it as a way to verify the validity of production P&ID documents. Try this out, see if 
you like it, and let us know what you like, don't like, and what you would change. 

## Quickstart

The whole stack -- web UI, review backend, Souffle, database, object storage --
in one command:

```bash
git clone --recurse-submodules https://github.com/<your-fork>/portlog.git
cd portlog
docker compose up
```

Then open <http://localhost:3000>, create an account, and upload a DEXPI 1.3
file. There is one in `TrainingTestCases/` if you do not have one to hand.

`--recurse-submodules` is not optional: `pyDEXPI` does the XML-to-graph
extraction and is a submodule, so a plain `git clone` gives you an empty
directory and a build that fails while installing it.

The stack generates its own secrets on first run and keeps them, along with
your accounts, in a Docker volume. `docker compose down` keeps that volume;
`docker compose down -v` deletes it, and with it every account and every
saved model credential.

**On Apple Silicon the first run is slow.** Souffle publishes no arm64 binary,
so the image is `linux/amd64` and runs under emulation. It works; it is not
quick. Native amd64 servers pay none of this.

To run without Docker -- as a CLI, a library, or a local web UI with no
accounts and no services -- see [Setup](#setup) and
[Running the web UI](#running-the-web-ui).

Contributions, bug reports, and the security policy:
[CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md),
[CHANGELOG.md](CHANGELOG.md).

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
HARBORFIELD_QA_PROVIDER=scripted .venv/bin/python -m pytest   # every test
```

`pytest` runs the whole suite, benchmark included, which takes about ten
minutes. For the edit loop, deselect the slow half explicitly:

```bash
HARBORFIELD_QA_PROVIDER=scripted .venv/bin/python -m pytest -m "not slow"
```

That reports how many tests it deselected, so the slow suite is skipped by
choice rather than by accident. `HARBORFIELD_QA_PROVIDER=scripted` pins the
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
HARBORFIELD_DEPLOYMENT_PROFILE=local PYTHONPATH=. HARBORFIELD_REVIEW_ARTIFACT_ROOT=.tmp/review-sessions \
  .venv/bin/python -m uvicorn pydexpi_datalog.web.asgi:app \
  --host 127.0.0.1 --port 8000
```

`HARBORFIELD_DEPLOYMENT_PROFILE` has no default and the server will not start
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

The review backend keeps nothing on the instance. The session index and saved
model credentials live in a shared [libSQL](https://turso.tech/libsql)
database and review artifacts live in an S3-compatible bucket, so all three
survive a redeploy and are the same for every instance. libSQL is SQLite's
own dialect over a network: one schema and one migration set serve both
profiles, which is why the local path cannot rot into a demo while hosted
grows features.

> **Run one instance for now.** The accounts database is still a
> `better-sqlite3` file on the instance, and Better Auth's JWT signing keys
> live in it. A second instance would have its own users and its own signing
> keys, so sign-ins would not carry across and a redeploy would discard every
> account. Give the instance a persistent volume and point `HARBORFIELD_AUTH_DB`
> at it. Moving accounts onto the shared database is tracked separately.

Install the extras, create the account tables once, then start both processes:

```bash
pip install -e ".[hosted]"      # libsql + boto3; the local profile needs neither

export HARBORFIELD_DEPLOYMENT_PROFILE=hosted
export BETTER_AUTH_URL=http://localhost:3000
export BETTER_AUTH_SECRET="$(openssl rand -base64 32)"   # required in hosted
export HARBORFIELD_BYOK_SECRET="$(openssl rand -base64 32)"  # encrypts saved keys

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
  HARBORFIELD_OIDC_ISSUER=$BETTER_AUTH_URL \
  HARBORFIELD_OIDC_AUDIENCE=$BETTER_AUTH_URL \
  HARBORFIELD_OIDC_JWKS_URL=$BETTER_AUTH_URL/api/auth/jwks \
  HARBORFIELD_LIBSQL_URL=http://127.0.0.1:8080 \
  HARBORFIELD_S3_BUCKET=portlog \
  HARBORFIELD_S3_ENDPOINT_URL=http://127.0.0.1:9000 \
  HARBORFIELD_S3_ACCESS_KEY_ID=minioadmin \
  HARBORFIELD_S3_SECRET_ACCESS_KEY=minioadmin \
  .venv/bin/python -m uvicorn pydexpi_datalog.web.asgi:app --port 8000
```

Against managed services, set `HARBORFIELD_LIBSQL_URL` to the Turso database URL
with `HARBORFIELD_LIBSQL_AUTH_TOKEN`, and point the `HARBORFIELD_S3_*` settings at
AWS, Cloudflare R2, or Backblaze B2. Both credentials are optional: a
`libsql-server` on a private network may not want a token, and a deployment
with an instance role has no S3 keys to give. The service, not this code,
decides whether it needs authenticating.

| Setting | Required | Meaning |
| --- | --- | --- |
| `HARBORFIELD_LIBSQL_URL` | yes | Session catalog and provider-key database |
| `HARBORFIELD_LIBSQL_AUTH_TOKEN` | no | Token, when the database wants one |
| `HARBORFIELD_S3_BUCKET` | yes | Bucket holding review artifacts |
| `HARBORFIELD_S3_ENDPOINT_URL` | no | Unset means AWS S3 itself |
| `HARBORFIELD_S3_ACCESS_KEY_ID` | no | Unset uses boto3's credential chain |
| `HARBORFIELD_S3_SECRET_ACCESS_KEY` | no | As above |
| `HARBORFIELD_S3_REGION` | no | Defaults to `us-east-1` |
| `HARBORFIELD_BYOK_SECRET` | yes | Encrypts saved model credentials |

The backend refuses to start if the OIDC settings, `HARBORFIELD_LIBSQL_URL`,
`HARBORFIELD_S3_BUCKET`, or `HARBORFIELD_BYOK_SECRET` are missing, rather than coming
up unauthenticated, writing sessions and artifacts onto a disk the next
redeploy throws away, or storing a user's model credential in the clear.
Artifact downloads are handed out as presigned URLs, so bytes travel from the
bucket to the browser without passing through the API.

#### Password reset

Better Auth implements the reset itself -- the token, its hour-long expiry,
its single use, and the exchange. The only thing it cannot supply is delivery,
so set an SMTP relay and "Forgot your password?" appears on the sign-in page.
Set none of these and the link is not offered, because a reset that silently
fails to send is worse than none.

| Setting | Required | Meaning |
| --- | --- | --- |
| `SMTP_HOST` | to send mail | Relay hostname |
| `SMTP_FROM` | to send mail | Address the message comes from |
| `SMTP_PORT` | no | Defaults to 587 |
| `SMTP_USER` | no | Omit for a relay that wants no credentials |
| `SMTP_PASSWORD` | no | Required if `SMTP_USER` is set |
| `SMTP_SECURE` | no | Implicit TLS; inferred for port 465 |

A partial configuration fails the sign-in page naming what is missing, rather
than hiding the feature. To try it without a relay, run a throwaway mailbox:

```bash
docker run -d -p 2025:1025 -p 8025:8025 axllent/mailpit
export SMTP_HOST=127.0.0.1 SMTP_PORT=2025 SMTP_FROM=portlog@example.com
```

Mail lands at <http://localhost:8025> instead of being delivered.

Configuring SMTP also turns on **email verification**, because the two are
the same capability: Better Auth refuses a sign-in from an unverified address
only if it can send a link to fix that. So with a relay configured, sign-up
issues no session until the address is confirmed, and a sign-in attempt
before then resends the link rather than dead-ending. Following it verifies
the address and signs the user in.

With no relay, sign-up and sign-in behave as they always have and addresses
are not verified -- which is the right default for a single-operator install,
and the wrong one for anything with a public URL. Configure SMTP before you
put an instance somewhere strangers can reach it.

#### Signing in with Google or Apple

Email and password is always available and needs no external service. Google
and Apple are additive, and are configuration rather than code: set both
variables of a pair and a button appears on the sign-in page; set neither and
the page renders email and password alone.

| Setting | Meaning |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Google OAuth client id |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `APPLE_CLIENT_ID` | Apple Services ID |
| `APPLE_CLIENT_SECRET` | Apple client secret, which is a signed JWT |

Setting one variable of a pair fails the sign-in page with a message naming
the other. That is deliberate: a half-configured provider that silently
rendered no button would leave you with nothing to search for.

Register this redirect URI with the provider, matching `BETTER_AUTH_URL`:

```
http://localhost:3000/api/auth/callback/google
```

**Google** accepts `http://localhost` redirect URIs, so it can be tried on a
local install with nothing but a Google Cloud project.

**Apple cannot.** It requires an HTTPS redirect URI on a domain you own, so
it cannot be exercised against `localhost` at all. It also needs a paid
Apple Developer account, and its "client secret" is not a fixed string but an
ES256 JWT signed with a `.p8` key that Apple caps at six months -- so a
deployment offering Apple needs somewhere to regenerate and redeploy that
value on a schedule. Nothing here generates it for you.

### Saved model credentials

The hosted profile stores each signed-in user's model provider key encrypted
in the shared database, so a key entered on one device is there on the next
(ADR 0014). Generate the secret once and set it identically on every
instance -- a key saved by one instance must decrypt on the others:

```bash
export HARBORFIELD_BYOK_SECRET="$(openssl rand -base64 32)"
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

### Deploying to a server

`docker-compose.yml` on its own is a laptop default: it publishes a MinIO
console with a known password and serves plain HTTP. Deploy with the
production overlay instead, which terminates TLS, publishes nothing but the
proxy, and turns every credential default into a required variable.

You need a host with Docker, and a DNS `A` record pointing your domain at it.
Ports 80 and 443 must be reachable -- Let's Encrypt validates over both.

```bash
git clone --recurse-submodules https://github.com/Harborfield/portlog.git
cd portlog

cat > .env <<'EOF'
HARBORFIELD_PUBLIC_HOST=harborfield.live
BETTER_AUTH_URL=https://harborfield.live
TLS_CONTACT_EMAIL=you@example.com
MINIO_ROOT_USER=pidadmin
MINIO_ROOT_PASSWORD=generate-a-real-one
EOF
chmod 600 .env

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Caddy requests a certificate on first start, so the first request can take a
few seconds. After that, <https://harborfield.live> serves the app and plain
HTTP redirects to it.

`BETTER_AUTH_URL` must be the public URL. Sign-in redirects, password-reset
links, and OAuth callbacks are all built from it, and it is what makes the
session cookie `__Secure-`. Pointing it at `localhost` on a deployed instance
produces links that lead back to the server's own loopback.

The image is `linux/amd64`. Most servers are; an arm64 host would need Souffle
built from source.

#### What to keep

Three named volumes hold everything that cannot be rebuilt:

| Volume | Contents | If you lose it |
| --- | --- | --- |
| `app-state` | Accounts, and the generated secrets | Every account, and every saved model credential becomes undecryptable |
| `minio-data` | Review artifacts | Uploaded drawings, facts and traces |
| `libsql-data` | Session index and saved credentials | The list of reviews, and stored model keys |

`caddy-data` holds certificates; losing it only forces re-issuance, which
Let's Encrypt rate-limits, so it is worth keeping too.

Back them up while the stack is stopped, which avoids copying a database
mid-write:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop
for v in app-state minio-data libsql-data; do
  docker run --rm -v "portlog_${v}:/from" -v "$PWD/backup:/to" \
    alpine tar czf "/to/${v}.tar.gz" -C /from .
done
docker compose -f docker-compose.yml -f docker-compose.prod.yml start
```

Set `BETTER_AUTH_SECRET` and `HARBORFIELD_BYOK_SECRET` in `.env` if you would
rather hold them yourself than have the container generate them into
`app-state`. Doing so is what lets you move the deployment to another host
without invalidating sessions and saved keys.

#### Updating

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The account schema migrates on start. Take a backup first: nothing here rolls
a migration back.

#### Before inviting anyone

Sign-up is open to anyone who can reach the URL. With SMTP configured they
must confirm their address before the account works, which stops one person
registering another's email but does not stop anyone registering. If you want
a closed instance, put it behind a private network or a proxy that
authenticates before PortLog sees the request.

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
  --output-dir /tmp/portlog-export-facts

./.venv/bin/python -m pydexpi_datalog derive-graph-semantics \
  /tmp/portlog-export-facts/e06-natural/graph_facts.json \
  --output-dir /tmp/portlog-derived-graph-semantics
```
