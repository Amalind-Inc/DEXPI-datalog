# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the major version is `0`, the command-line interface, the HTTP API, the
fact-export format, and the derived predicate names may all change in a minor
release. Anything depending on them should pin a version.

## [Unreleased]

## [0.1.0] - 2026-07-25

First tagged release. The project existed for six weeks before this tag, so
this entry describes what is in it rather than what changed since a previous
version.

### Determinism and the fact substrate

- Export a DEXPI 1.3 source file to a graph-mirrored fact layer
  (`graph_facts.json`) with stable ordering and provenance, and from there to
  executable Souffle (`export-facts`, `derive-graph-semantics`).
- Derive graph and topology semantics as Datalog over that layer, so an answer
  is the output of a program rather than a model's recollection.
- Answer questions only from generated Datalog over approved predicates.
  Requests that the predicates cannot express are reported as missing facts or
  policy rather than guessed at.

### Review workflow

- Web UI for single-file review: upload a DEXPI file, inspect the rendered
  schematic, ask questions, and see the evidence behind each answer.
- Rule packs that carry advisory guidance and executable rules separately, so
  pasted regulatory text informs a walkthrough without silently becoming a
  compliance verdict.
- Interactive rule authoring, where a drafted rule is confirmed once and then
  reused.
- A governed execution trace for each turn, retained as artifacts.

### Deployment

- Two profiles from one codebase. `local` keeps everything on the operator's
  machine with no accounts and no network services. `hosted` signs users in
  and scopes every session, artifact, and authored rule pack to an account.
- `docker compose up` brings up the hosted stack -- app, libSQL, object
  storage -- creating its bucket and generating its secrets on first run.
- Hosted persistence: a libSQL session catalog and S3-compatible artifact
  storage, so nothing the backend owns is lost on redeploy.

### Accounts and credentials

- Sign-in with email and password, and optionally Google or Apple, through
  [Better Auth](https://better-auth.com). The Python backend is a resource
  server that verifies a JWT against the published JWKS; no password or
  account record reaches it.
- Password reset over SMTP, offered only when a mail relay is configured.
- Bring-your-own-key model access. In `local`, keys stay in the browser. In
  `hosted`, a saved key is encrypted at rest with AES-256-GCM, bound to its
  owner and provider so a copied row cannot be decrypted by another user.

### Benchmarking

- Commands to run a question manifest through scripted or live arms, generate
  a synthetic truth-by-construction slice, and aggregate runs into a report
  under a locked decision rule (`run-benchmark`, `synthetic-slice`,
  `results-report`, `live-matrix`).

### Known limitations

- Sign-up does not verify email addresses.
- The hosted profile keeps its accounts database on the instance's own disk,
  so it should be run as a single instance with a persistent volume.
- Projects and chats are not persisted; the catalog holds review sessions and
  provider keys only.
- One DEXPI source file per run.
- Not audited, and not suitable for verifying production P&ID documents.

[Unreleased]: https://github.com/Amalind-Inc/DEXPI-datalog/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Amalind-Inc/DEXPI-datalog/releases/tag/v0.1.0
