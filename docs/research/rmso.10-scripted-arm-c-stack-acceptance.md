# RMSO.10: Unpaid Arm C stack acceptance episode

Date: 2026-07-19

## Outcome

**PASS after P0 fix (rerun below); the original run FAILED with a lifecycle
integration defect.** The scripted Arm C reasoning and
Souffle query were correct, but the checkpoint-aware KIRA adapter did not
recognize the successful helper receipt in the real wrapped terminal stream.
It therefore executed a command after the accepted checkpoint and attempted a
second provider call. Harbor aborted before verification.

This was a fully unpaid run. The OpenAI-compatible endpoint was a local
`ThreadingHTTPServer`; no OpenRouter or other paid model endpoint was used.

## Episode

- Question: `hq-nozzle-piping-attachment-small`
- Arm: `c-souffle:scripted-local`
- KIRA commit: `652dacbf14d29ea93a83c496ee91e0e5ba286721`
- Backend: Harbor Docker environment, Terminus-KIRA, local scripted provider,
  generated Arm C task, Souffle helper, and normal post-run artifact parser
- Budgets: 4 turns, 4 commands, 4,096 output tokens, 300-second agent timeout,
  60-second verifier timeout
- Replacement wall time: 41.810 seconds (Harbor trial timestamps span 34.766
  seconds; agent execution spans 18.451 seconds)
- Cost: $0; the local endpoint returned one scripted completion and rejected
  every subsequent request

The scripted completion appended a portable Datalog query to the preloaded
`analysis.dl` and ran the required helper. It also supplied a second command,
`printf SHOULD_NOT_RUN ...`, as a lifecycle assertion: that command must be
discarded after the first command establishes a valid checkpoint.

## What worked

The task was generated, built, and launched through the intended stack. The
first model-supplied command ran Souffle successfully. Its helper output was:

```json
{"ok": true, "rmso_checkpoint": "accepted", "witness_ids": ["7fdefa2f-5751-48eb-8c7c-34dd07cc16d3", "8b1fc943-32e4-417d-9358-703251ff1fa5", "e27d8412-bb29-4dc4-9b45-b2939867bdbd", "f3156923-be75-4fc1-8f08-7a7d022facff"]}
```

The four witnesses exactly match the preregistered ground truth. This shows
that the generated task, mounted graph facts, portable Datalog program,
Souffle engine, and provisional-answer helper all worked. The model-side work
was sufficient after one local provider response.

## What failed and why

Terminus-KIRA captures output from a fixed-width terminal. The long JSON
receipt wrapped in the middle of the third UUID:

```text
... "e27d8412-bb29-4dc4-
9b45-b2939867bdbd", ...
```

`_accepted_checkpoint()` currently parses each physical terminal line as an
independent JSON document. Neither wrapped fragment is valid JSON, so the
adapter treated the valid checkpoint as absent. Consequences:

1. The forbidden second command was sent to the terminal and persisted in the
   trajectory.
2. KIRA requested another completion instead of completing mechanically.
3. The local endpoint intentionally returned HTTP 500 for that unexpected
   paid-equivalent call; LiteLLM retried it, producing 16 total HTTP requests.
4. Harbor recorded `InternalServerError`, did not run the verifier, and copied
   neither `structured_answer.json` nor `analysis.dl` into final verifier
   artifacts.
5. The benchmark adapter returned `malformed_model_output` with
   `verification_gate_rejected`.

The 16 HTTP requests do **not** represent 16 reasoning turns or paid calls.
They are one intended local completion plus LiteLLM retries after the
unexpected second logical model call was deliberately rejected.

## Infrastructure-invalid setup attempt

The first launch used a scripted terminal command without a trailing newline.
KIRA concatenated its marker command to the helper argument as
`analysis.dlecho`, so the helper printed its usage message. That setup attempt
is infrastructure-invalid. A fresh output directory and corrected newline were
used for the replacement described above. The replacement reached a valid
Souffle checkpoint and exposed the separate terminal-wrapping defect.

## Recommended P0 fix

Make the mechanical receipt independent of witness-list length. The smallest
robust change is for `run_query.py` to print a short receipt on its own line,
for example:

```json
{"ok":true,"rmso_checkpoint":"accepted"}
```

Witnesses can be printed separately for human/model observation. The adapter
should continue requiring the fixed replay preflight; both the candidate run
and preflight will then emit a receipt that cannot wrap at ordinary terminal
widths. Add an integration-shaped test containing enough UUID witnesses to
force wrapping of the descriptive output, then rerun this exact scripted
episode. Acceptance requires one provider request, one executed model command,
the forbidden tail absent from the trajectory, Harbor reward 1, and exact
ground-truth witnesses after all Arm C gates.

## Artifacts

- Valid replacement attempt: `.artifacts/rmso.10-scripted-arm-c-replacement/`
- Infrastructure-invalid setup attempt: `.artifacts/rmso.10-scripted-arm-c/`
- Replacement summary: `.artifacts/rmso.10-scripted-arm-c-replacement/summary.json`
- Harbor trial result, trajectory, terminal pane, and job log are retained
  under the replacement episode's timestamped `jobs/` directory.

## P0 fix and passing rerun (2026-07-19)

The recommended fix was implemented in `pydexpi_datalog/benchmark/souffle_arm.py`:
`run_query.py` now prints the witness listing as a descriptive line and then a
short mechanical receipt on its own line, independent of witness-list length:

```json
{"witness_ids": ["..."]}
{"ok":true,"rmso_checkpoint":"accepted"}
```

The adapter's line-oriented `_accepted_checkpoint()` is unchanged; the receipt
frame (40 characters) can no longer wrap at ordinary terminal widths, and the
fixed replay preflight emits the same short receipt. A regression test,
`test_checkpoint_receipt_survives_fixed_width_terminal_wrapping`, runs the
generated helper with enough real witness IDs to force wrapping, hard-folds
every stdout line at 80 columns like the Terminus pane, and asserts the
adapter completes mechanically without executing the forbidden command or
calling the model again. The test reproduced the original failure before the
fix and passes after it; `tests/benchmark/` passes in full (252 tests).

The exact scripted episode was rerun through the same stack (fresh output
directory, KIRA re-pinned at `652dacbf14d29ea93a83c496ee91e0e5ba286721`).
All acceptance criteria passed:

- Exactly 1 provider request (previously 16 including LiteLLM retries).
- Exactly 1 executed model command in the trajectory; the forbidden
  `SHOULD_NOT_RUN` tail is absent from the trajectory and terminal pane (it
  appears only in the raw scripted `response.txt`, as proposed-but-discarded).
- The terminal pane shows the wrapped witness line and, on its own unwrapped
  physical line, `{"ok":true,"rmso_checkpoint":"accepted"}` — for both the
  candidate run and the mechanical preflight.
- Harbor reward 1 with the verifier executed.
- Verdict `violation_found` with exactly the four preregistered ground-truth
  witnesses after all Arm C gates, including the counterfactual faithfulness
  probes.
- Cost $0; wall time 35.718 seconds.

`usage.model_calls` reports 2 because the mechanical completion turn is
counted; the authoritative provider request count from the local endpoint is 1.

- Passing rerun artifacts: `.artifacts/rmso.10-scripted-arm-c-fixed/`
- Rerun summary: `.artifacts/rmso.10-scripted-arm-c-fixed/summary.json`
