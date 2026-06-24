# ADR 0001: OSS v1 Web Review Shell

Status: Accepted

## Context

The OSS v1 single-file review workflow needs a user-facing path where a process
engineer can upload one DEXPI XML file, inspect a topology panel, ask a logic
request, review a restatement, execute deterministic logic, and inspect evidence.

The repository now has repository-owned deterministic workflow seams for session
preparation, visible source scope, provider-neutral BYOK settings, route-first
Improve, restatement-first confirmation, deterministic execution, and topology
evidence highlighting. Those seams should remain owned by Python package code
rather than by a chat UI framework.

The Chainlit evaluation found that Chainlit can quickly demonstrate upload,
coarse job status, assistant actions, and simple custom elements. It also found
that the stock Chainlit shell does not satisfy the primary product needs for a
typed React/TypeScript frontend, graph-library topology workspace, and dense
P&ID-centered review layout.

## Decision

Use a repository-owned Python backend API plus a React/TypeScript frontend as the primary OSS v1 product architecture.

Chainlit is allowed only as a minimal prototype shell. It may be used to exercise
the Python workflow quickly, but it is not the primary product frontend.

The primary frontend should be a dedicated frontend that can use TSX components,
typed API contracts, and a graph visualization library such as Cytoscape.js for
the topology panel.

## Required Backend Boundaries

The backend must preserve repository-owned deterministic workflow seams:

- Session preparation accepts one DEXPI XML file and produces temporary session
  artifacts.
- All workflow calls use explicit session IDs.
- Long-running actions are shaped as review workflow jobs with coarse status and
  optional stage text.
- The full-page P&ID acceptance corpus remains the workflow regression target.
- The topology panel consumes a compact topology-view model and semantic
  evidence-highlight payloads, not raw pyDEXPI graph internals.
- Provider-neutral BYOK settings expose provider, model, and configured status
  while preserving the zero-secret-leak boundary.
- Logic-request artifacts, deterministic result artifacts, diagnostics, and
  evidence stay reproducible without requiring hidden chat history.

## Frontend Validation

Frontend work must be tested through user-visible behavior, not only backend
state models.

The minimum frontend smoke test should use Playwright or equivalent browser
automation to prove that the UI can:

- upload a real DEXPI XML file from the full-page P&ID acceptance corpus;
- show disabled query controls before readiness;
- show ready state after preparation completes;
- render the topology panel from the topology-view model;
- select a visible source scope;
- submit a logic request;
- show Improve, confirmation, deterministic answer, and expandable evidence
  states;
- show topology evidence highlighting from deterministic artifacts;
- display provider/model/configured status without displaying credential values.

Live OpenRouter calls are useful as an optional smoke test for provider
connectivity and model JSON behavior. They must not be required for normal CI.
Normal frontend and backend CI should keep using deterministic fake providers.

## Chainlit Prototype Role

Chainlit can still be useful for a minimal prototype shell:

- AskFileMessage can collect a DEXPI XML upload.
- TaskList can show session-preparation progress.
- Action callbacks can trigger Improve, confirmation, execution, and selected
  rule-pack execution.
- CustomElement can display a simple topology summary or side panel.

This prototype is a learning tool. It should not become the durable product
surface unless the team explicitly reverses this ADR.

## Migration Path

If Chainlit prototype work becomes constraining, follow this migration path by
keeping the Python workflow classes and replacing only the shell:

1. Expose the existing workflow methods through a small backend API.
2. Move upload, job polling, topology rendering, provider settings, Improve,
   confirmation, execution, and evidence highlighting into the dedicated
   React/TypeScript frontend.
3. Keep Chainlit scripts as optional demos or remove them once the dedicated
   frontend covers the same Playwright smoke workflow.

## Consequences

The product path requires frontend work earlier than a pure backend prototype
would. That is intentional: uploading XML, selecting topology scope, confirming a
restatement, and inspecting evidence are user workflows, and they must be proven
in a real UI.

The backend workflow code remains valuable because it gives both Chainlit and the
dedicated frontend the same deterministic substrate. The frontend decision does
not move deterministic QA logic into browser code or into the LLM provider.
