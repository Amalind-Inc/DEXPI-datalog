# Contributing

Thanks for looking. This is a small project with a specific idea in it, so
this document is mostly about how to run it and what a change is expected to
look like, rather than rules for their own sake.

## Reporting a bug or asking for something

Open a [GitHub issue](https://github.com/Harborfield/portlog/issues).

For a bug, the two most useful things are the DEXPI file that triggered it (or
one that reproduces it) and what you expected the answer to be. This tool makes
claims about engineering drawings; "it said X and X is wrong because Y" is a
better report than a stack trace, though a stack trace is welcome too.

Maintainers plan work in [Beads](https://github.com/Dicklesworthstone/beads_viewer),
a tracker committed under `.beads/`. That is an internal detail: you do not
need `br` installed to contribute, and issues you file are triaged from GitHub.

For anything security-related, see [SECURITY.md](SECURITY.md) and do not open a
public issue.

## Running it

The fastest way to see it work:

```bash
git clone --recurse-submodules https://github.com/Harborfield/portlog.git
cd portlog
docker compose up
```

`--recurse-submodules` matters: `pyDEXPI` does the XML-to-graph extraction and
is a submodule, so a plain clone fails while installing it. If you already
cloned without it, `git submodule update --init --recursive` fixes it.

## Developing without Docker

You need Python 3.12+, Node 22+, and Souffle 2.5.

```bash
# Souffle: https://souffle-lang.github.io/install
# macOS: brew install souffle
# Ubuntu: install the .deb from the Souffle releases page, as CI does

python3 -m venv .venv
.venv/bin/pip install -e ./pyDEXPI
.venv/bin/pip install -e ".[dev]"

cd frontend && npm ci && cd ..
```

Run the two processes in separate terminals:

```bash
HARBORFIELD_DEPLOYMENT_PROFILE=local PYTHONPATH=. \
  .venv/bin/python -m uvicorn pydexpi_datalog.web.asgi:app --port 8000

cd frontend && HARBORFIELD_DEPLOYMENT_PROFILE=local npm run dev
```

`HARBORFIELD_DEPLOYMENT_PROFILE` has no default in the backend, on purpose: a
hosted deployment that silently fell back to `local` would serve every user
from one workspace with no sign-in.

## Before you open a pull request

Run what CI runs. All of it is fast except the Docker job.

```bash
.venv/bin/ruff check .

HARBORFIELD_DEPLOYMENT_PROFILE=local  HARBORFIELD_QA_PROVIDER=scripted .venv/bin/python -m pytest -m "not slow"

cd frontend
npm run typecheck
npm test
npx oxlint
```

The suite also runs under `HARBORFIELD_DEPLOYMENT_PROFILE=hosted` against a real
libSQL server and a real MinIO. You do not need those locally -- the hosted
tests skip without them, and CI covers that leg -- but if you are changing
storage, the backends are two `docker run` commands and `tests/conftest.py`
prints them when they are missing.

`HARBORFIELD_QA_PROVIDER=scripted` forces the deterministic no-LLM provider, so
tests never need a model key and never make a network call.

`oxfmt` is not enforced. It currently fails on files that predate it, and a
check that cannot pass would be worse than none. Format the files you touch
(`npx oxfmt <files>`) and leave the rest alone.

## What a change is expected to look like

**Tests first, against behaviour.** Write a test that fails for the reason
you are about to fix, then make it pass. Prefer tests that go through a public
surface -- an API route, a CLI command, a pure function's real contract -- over
tests that assert on internals. A test that passes when the feature is broken
is worse than no test, so it is worth breaking your own code once to confirm
the test notices.

**Explain why in the code.** Comments here answer "why is it like this", not
"what does this line do". If a decision has a rejected alternative, that
alternative is usually the useful thing to write down.

**Architectural decisions go in `docs/adr/`.** If your change makes a choice
that a future reader could reasonably reverse without knowing what it cost,
add a short ADR next to the existing ones. They are prose, not a template.

**Domain vocabulary lives in `CONTEXT.md`.** If you introduce a term, or find
yourself avoiding one, that file is where it is settled.

**One concern per pull request.** A diff that fixes a bug and reformats a file
is two reviews wearing one hat.

## Commit messages

The body matters more than the subject. Say what changed and why the
alternative was rejected; assume the reader is you in six months, trying to
work out whether it is safe to change this.

Existing history uses a bead id as the subject prefix. You do not need one --
a plain descriptive subject is fine for an outside contribution.

## Licence

By contributing you agree that your contribution is licensed under the
[AGPL-3.0](LICENSE), the same terms as the rest of the project. Note that the
AGPL's network clause applies: if you run a modified version as a network
service, you have to offer its source to its users.
