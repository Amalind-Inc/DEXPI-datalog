# RMSO redesigned run: failure forensics

**Date:** 2026-07-18  
**Run:** `.tmp/rmso-live-20260718-redesigned-03`  
**Scoring authority:** corrected post-hoc reports for [Arm A](../../.tmp/rmso-live-20260718-redesigned-03/posthoc-regrade/arm-a/benchmark_report.json) and [Arm C](../../.tmp/rmso-live-20260718-redesigned-03/posthoc-regrade/arm-c/benchmark_report.json)

## Executive finding

The formal result remains 4/9 for Arm A and 5/9 for Arm C. Neither arm met the
pre-registered 9/9 qualification rule, so the architecture decision remains
`NO-GO / rethink`.

That result does **not** mean the model was unable to reason about half of the
questions. Of the nine failed episodes:

- four had an exact, executed, verifier-accepted checkpoint, but Harbor later
  timed out the episode;
- two made the correct policy-boundary judgment but serialized the answer in
  the wrong JSON shape;
- one crashed in the KIRA tool-call parser before it could investigate the
  graph; and
- only two reached the deadline without a correct checkpoint.

Thus 7/9 formal failures do not demonstrate inability to determine the semantic
answer. Across the full matrix, 15/18 episodes either formally passed, produced
an exact executed checkpoint, or expressed the correct abstention. In a
sixteenth episode—Arm A small nozzle—the archived model reasoning identified
the exact four witnesses, but an upstream error truncated the tool call before
it could become an executed artifact. This is evidence that both methods are
improvable. It is not evidence that either is currently reliable enough under
the locked five-minute, replayable-audit contract.

## What “failure” means here

The benchmark deliberately tests a system contract, not only final-answer
semantics. A creditable episode must finish on time, produce the canonical
answer schema, ground its claims in an executed artifact when required, pass
the audit-trace gates, and—where applicable—pass Datalog faithfulness probes.
The protocol makes timeout, malformed output, trace unsafety, and failed
faithfulness independently disqualifying; see the [pre-registered protocol](rmso.4-pre-registered-eval-protocol.md).

The corrected reports are the authority for credit. A Harbor `reward.txt` of 1
inside a timed-out trial is evidence that a correct checkpoint existed, not a
formal pass. The artifact parser intentionally gives the persisted
`AgentTimeoutError` precedence over a partial verifier reward in
[`parse_harbor_artifacts`](../../pydexpi_datalog/benchmark/agentic_arm.py).

## Complete corrected outcome matrix

| Entry | Arm A | Arm C |
| --- | --- | --- |
| Shallow P-4713 retrieval | pass | pass |
| Nozzle attachment, small | **fail: correct reasoning, no checkpoint + timeout** | pass |
| Nozzle attachment, large | **fail: correct checkpoint + timeout** | pass |
| Valve reachability, small | pass | **fail: correct checkpoint + timeout** |
| Valve reachability, large | pass | **fail: correct checkpoint + timeout** |
| Equipment connectivity, small | pass | **fail: correct checkpoint + timeout** |
| Equipment connectivity, large | **fail: tool parser crash** | **fail: no checkpoint + timeout** |
| Permission control, small | **fail: malformed schema** | pass |
| Permission control, large | **fail: malformed schema** | pass |
| **Total** | **4/9** | **5/9** |

The run itself was complete and fully accounted: 18 episodes, 249 settled
provider responses, no unknown costs or policy violations, and total cost
USD 0.24677421676. Those facts are recorded in the immutable
[`rmso_live_summary.json`](../../.tmp/rmso-live-20260718-redesigned-03/rmso_live_summary.json)
and the [scored-run report](rmso.1-redesigned-scored-run-2026-07-18.md).

## Failure-by-failure analysis

### Arm A: nozzle attachment, small

**Formal result:** fail. Expected `violation_found` with four witnesses; the
corrected report records `malformed_model_output` with no witnesses.

**What happened:** Harbor raised `AgentTimeoutError` at exactly 300 seconds.
There is no structured answer, and the verifier reports that
`/workspace/structured_answer.json` was missing. The agent executed only five
terminal commands. It began with a bounded `head`, then ignored the instruction
to use bounded inspection and issued full `cat` commands for both graph files.
It nevertheless identified the exact four expected witnesses in the next
model response. That response ended with `finish_reason="error"`, embedded HTTP
504 `Upstream idle timeout exceeded`, and a truncated `execute_commands`
argument just as it began writing `analysis.py`. Harbor then reached its own
deadline while awaiting HTTP. Evidence:

- [trial result](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-nozzle-piping-attachment-small/jobs/2026-07-18__18-40-34/benchmark-hq-nozzle-piping-attac__rcKXdWH/result.json)
- [trajectory](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-nozzle-piping-attachment-small/jobs/2026-07-18__18-40-34/benchmark-hq-nozzle-piping-attac__rcKXdWH/agent/trajectory.json)
- [raw call 12 response](../../.tmp/rmso-live-20260718-redesigned-03/openrouter/call-0012-response.json)
- [verifier output](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-nozzle-piping-attachment-small/jobs/2026-07-18__18-40-34/benchmark-hq-nozzle-piping-attac__rcKXdWH/verifier/test-stdout.txt)
- [task instruction](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-nozzle-piping-attachment-small/tasks/benchmark-hq-nozzle-piping-attachment-small/instruction.md)

**Diagnosis:** artifact-completion failure despite correct semantic reasoning.
The upstream idle timeout is directly causal in this episode; the unbounded
inspection inflated the next prompt and left the agent without an early
checkpoint. Only three responses in the 249-call archive contain this embedded
error shape (calls 3, 12, and 104), and calls 3 and 104 occurred in passing
episodes, so it is a local cause rather than a global explanation. Confidence
is high.

### Arm A: nozzle attachment, large

**Formal result:** fail because of timeout precedence.

**What happened:** the agent did solve the problem. The verifier-preserved
answer says `violation_found` and lists exactly the three expected UUIDs; the
executed Python replay agrees, and Harbor wrote `reward.txt = 1`. The agent then
called `task_complete`, but the trial also persisted an `AgentTimeoutError` at
the five-minute boundary. The corrected report therefore gives zero. Evidence:

- [trial result](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-nozzle-piping-attachment-large/jobs/2026-07-18__18-45-34/benchmark-hq-nozzle-piping-attac__8SXveLh/result.json)
- [correct checkpoint](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-nozzle-piping-attachment-large/jobs/2026-07-18__18-45-34/benchmark-hq-nozzle-piping-attac__8SXveLh/verifier/structured_answer.json)
- [executed replay](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-nozzle-piping-attachment-large/jobs/2026-07-18__18-45-34/benchmark-hq-nozzle-piping-attac__8SXveLh/verifier/analysis_replay.json)
- [trajectory](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-nozzle-piping-attachment-large/jobs/2026-07-18__18-45-34/benchmark-hq-nozzle-piping-attac__8SXveLh/agent/trajectory.json)

**Diagnosis:** semantic reasoning and executed evidence succeeded; deadline
delivery failed. Eighteen completed model calls consumed about 277.3 seconds,
including one 153.9-second call, leaving almost no budget for tools and final
submission. Confidence: high.

### Arm A: equipment connectivity, large

**Formal result:** fail. No judgment or checkpoint was produced.

**What happened:** the first model response supplied `commands` as a string
containing malformed DSML-like text rather than the expected list of command
objects. KIRA's `_parse_tool_calls` path then attempted `.get` on that string
and crashed with `AttributeError: 'str' object has no attribute 'get'`. This
happened after one provider call and before any command executed. Evidence:

- [trial result and traceback](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-equipment-pump-connectivity-large/jobs/2026-07-18__19-03-51/benchmark-hq-equipment-pump-conn__M7uMtfv/result.json)
- [malformed first response](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-equipment-pump-connectivity-large/jobs/2026-07-18__19-03-51/benchmark-hq-equipment-pump-conn__M7uMtfv/agent/episode-0/response.txt)

**Diagnosis:** integration/parser robustness failure. It provides no evidence
for or against the model's ability to answer the graph question. Confidence:
high.

### Arm A: permission control, small

**Formal result:** fail as `malformed_submission`.

**What happened:** the semantic judgment is correct: `unanswerable`, no
witnesses, and `source_data_unavailable`, with the prescribed policy-abstention
operation. The JSON used `witnesses` instead of `witness_ids`, `explanation`
instead of `answer_text`, and `support_graph` instead of `support`. The canonical
parser requires the `verdict`, `witness_ids`, and `posture` fields and otherwise
degrades safely to `malformed_model_output`; see
[`parse_structured_answer`](../../pydexpi_datalog/benchmark/direct_arm.py).
Evidence:

- [submitted checkpoint](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-permission-defeasible-control-small/jobs/2026-07-18__19-04-18/benchmark-hq-permission-defeasib__YqGJGj3/verifier/structured_answer.json)
- [permission instruction](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-permission-defeasible-control-small/tasks/benchmark-hq-permission-defeasible-control-small/instruction.md)

**Diagnosis:** schema packaging failure, not policy reasoning failure. The
permission-specific prompt described the desired fields in prose and showed
only the inner support graph, rather than providing one complete canonical
JSON object. That ambiguity plausibly contributed. Confidence is high about
the schema failure and medium-high about the prompt-shape contribution.

### Arm A: permission control, large

**Formal result:** fail as `malformed_submission`.

**What happened:** again the semantic judgment and abstention operation are
correct. This answer used `witnesses` and `explanation`, and placed `steps` and
`claims` at the top level instead of under `support`. It also took 26 command
batches and 28 model calls to package an answer whose policy conclusion was
given explicitly by the task. Evidence:

- [submitted checkpoint](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-permission-defeasible-control-large/jobs/2026-07-18__19-05-26/benchmark-hq-permission-defeasib__zc8nEjo/verifier/structured_answer.json)
- [trajectory](../../.tmp/rmso-live-20260718-redesigned-03/arm-a/harbor/hq-permission-defeasible-control-large/jobs/2026-07-18__19-05-26/benchmark-hq-permission-defeasib__zc8nEjo/agent/trajectory.json)

**Diagnosis:** schema packaging failure plus avoidable agent-loop work. The
semantic result was not in doubt. Confidence: high for schema, medium for why
the loop took so many turns.

### Arm C: valve reachability, small

**Formal result:** fail because of timeout precedence.

**What happened:** an executed Soufflé query produced the exact expected
`no_violation` checkpoint with no witnesses, and Harbor wrote reward 1. The
agent continued with a manual Python reachability verification and was still
waiting on a model call when the 300-second timer expired. Twenty-three
completed provider calls consumed about 268.8 seconds. Evidence:

- [trial result](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-valve-monitoring-reachability-small/jobs/2026-07-18__19-18-31/benchmark-hq-valve-monitoring-re__AuVF7hG/result.json)
- [correct checkpoint](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-valve-monitoring-reachability-small/jobs/2026-07-18__19-18-31/benchmark-hq-valve-monitoring-re__AuVF7hG/verifier/structured_answer.json)
- [executed Datalog](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-valve-monitoring-reachability-small/jobs/2026-07-18__19-18-31/benchmark-hq-valve-monitoring-re__AuVF7hG/verifier/analysis.dl)
- [final trajectory](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-valve-monitoring-reachability-small/jobs/2026-07-18__19-18-31/benchmark-hq-valve-monitoring-re__AuVF7hG/agent/trajectory.json)

**Diagnosis:** the engine logic succeeded, but the agent did not stop after a
valid executed checkpoint. Confidence: high.

### Arm C: valve reachability, large

**Formal result:** fail because of timeout precedence.

**What happened:** the executed checkpoint contains the exact eight expected
witnesses and Harbor reward 1. The agent spent additional time improving
`answer_text` and checking output files. Twenty completed provider calls used
about 262.2 seconds; the episode expired while waiting on another call.
Evidence:

- [trial result](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-valve-monitoring-reachability-large/jobs/2026-07-18__19-23-32/benchmark-hq-valve-monitoring-re__UrvvjK9/result.json)
- [correct checkpoint](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-valve-monitoring-reachability-large/jobs/2026-07-18__19-23-32/benchmark-hq-valve-monitoring-re__UrvvjK9/verifier/structured_answer.json)
- [executed Datalog](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-valve-monitoring-reachability-large/jobs/2026-07-18__19-23-32/benchmark-hq-valve-monitoring-re__UrvvjK9/verifier/analysis.dl)

**Diagnosis:** semantic and engine execution success, followed by unnecessary
polishing inside a hard deadline. Confidence: high.

### Arm C: equipment connectivity, small

**Formal result:** fail because of timeout precedence.

**What happened:** the executed Datalog produced the exact expected
`no_violation` checkpoint and Harbor reward 1. Before that, the transcript shows
file-permission confusion and repeated attempts to rewrite `analysis.dl`; after
success, the agent continued manual verification. Nine completed provider calls
consumed about 276.6 seconds, dominated by calls of 69.0 and 151.0 seconds.
Evidence:

- [trial result](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-equipment-pump-connectivity-small/jobs/2026-07-18__19-28-32/benchmark-hq-equipment-pump-conn__FhkqHTu/result.json)
- [correct checkpoint](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-equipment-pump-connectivity-small/jobs/2026-07-18__19-28-32/benchmark-hq-equipment-pump-conn__FhkqHTu/verifier/structured_answer.json)
- [executed Datalog](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-equipment-pump-connectivity-small/jobs/2026-07-18__19-28-32/benchmark-hq-equipment-pump-conn__FhkqHTu/verifier/analysis.dl)
- [trajectory](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-equipment-pump-connectivity-small/jobs/2026-07-18__19-28-32/benchmark-hq-equipment-pump-conn__FhkqHTu/agent/trajectory.json)

**Diagnosis:** engine logic succeeded. Provider tail latency was the dominant
measured budget consumer, amplified by avoidable file churn and post-checkpoint
verification. Confidence: high.

### Arm C: equipment connectivity, large

**Formal result:** fail. Expected `no_violation`; no valid structured answer was
preserved and verifier reward was 0.

**What happened:** the agent used 36 command batches and repeatedly inspected
edge attributes, rewrote Datalog, executed attempts, and fell back to manual
graph traversal. The trial timed out while Harbor was sending a terminal
command, not while waiting for a model response. The 29 completed provider calls
already consumed about 278.9 seconds. The last response was still exploring
connectivity and no accepted checkpoint existed. Evidence:

- [trial result](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-equipment-pump-connectivity-large/jobs/2026-07-18__19-33-34/benchmark-hq-equipment-pump-conn__whThosA/result.json)
- [trajectory](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-equipment-pump-connectivity-large/jobs/2026-07-18__19-33-34/benchmark-hq-equipment-pump-conn__whThosA/agent/trajectory.json)
- [verifier failure](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-equipment-pump-connectivity-large/jobs/2026-07-18__19-33-34/benchmark-hq-equipment-pump-conn__whThosA/verifier/test-stdout.txt)
- [task instruction](../../.tmp/rmso-live-20260718-redesigned-03/arm-c/harbor/hq-equipment-pump-connectivity-large/tasks/benchmark-hq-equipment-pump-connectivity-large/instruction.md)

**Diagnosis:** genuine completion failure. The available facts were sufficient—the
other arm solved the same entry—but this episode never converged from inspection
to a verified query. The likely causes are an overly exploratory generate/revise
loop, Datalog/file-edit friction, and a provider-latency budget with no reserved
finalization margin. Confidence is high on non-completion and medium on the
relative contribution of those causes.

## Cross-cutting root causes

### 1. The agent treats the deadline as unlimited until it abruptly expires

Five failures were Harbor timeouts. In four, a correct checkpoint already
existed. Completed model-call time alone was 262–277 seconds in four of those
episodes, leaving almost no tool or submission margin. The most damaging
behavior was continuing to inspect, manually re-verify, or polish after the
bounded helper had produced an accepted checkpoint.

**Confidence: high.** The trial results, per-call timing metadata, checkpoints,
and last tool actions all agree.

### 2. Instructions encourage finish-first, but the runtime does not enforce it

Both helpers atomically write a provisional structured answer after successful
execution: [`RMSO_RUN_QUERY_HELPER`](../../pydexpi_datalog/benchmark/souffle_arm.py)
for Arm C and the analogous Python replay helper generated by
[`agentic_arm.py`](../../pydexpi_datalog/benchmark/agentic_arm.py) for Arm A.
This protected the evidence, but it did not stop the agent loop. A later timeout
correctly invalidated the episode under the protocol.

**Confidence: high.** Four exact checkpoints were lost solely to timeout
precedence.

### 3. Provider tail latency magnifies every unnecessary turn

The timeout episodes were not uniformly compute-bound. Examples include a
153.9-second call in Arm A large nozzle and 69.0- and 151.0-second calls in Arm C
small equipment. Reachability episodes accumulated roughly 262–269 seconds
across many calls. Even good logic cannot reliably finish if exploration is
allowed to consume almost all 300 seconds.

**Confidence: high for measured latency; medium for whether a different provider
would materially improve end-to-end qualification.** That requires a controlled
experiment.

### 4. The permission prompt and canonical parser disagree in specificity

The general grounded tasks show the full canonical submission shape. The
permission instruction describes fields in prose and shows only the inner
support graph. Both Arm A permission answers chose plausible but noncanonical
field names; both Arm C episodes happened to choose the canonical shape and
passed. The parser is intentionally strict and fail-closed.

**Confidence: high that schema mismatch caused both zeros; medium-high that the
prompt presentation caused the mismatch.**

### 5. Tool-call parsing is brittle at an external-model boundary

One malformed model tool call crashed KIRA because a string reached code that
assumed a command object. A robust boundary should reject the bad call and let
the model repair it, not terminate the episode.

**Confidence: high.** The response and traceback are direct evidence.

### 6. Arm C pays a high interaction tax to author a small query

The failed Arm C episodes used 18–36 command batches and very large cumulative
contexts. The agent repeatedly rediscovered the EDB schema, inspected helper
files already explained in the prompt, struggled with file editing, and manually
rechecked engine output. This is workflow inefficiency, not an inherent failure
of Datalog.

**Confidence: high that the interaction tax exists; medium that any single
proposed simplification will eliminate it.**

## Trace safety and Datalog faithfulness

- Every formal pass in the corrected reports has `audit_trace.trace_safe=true`,
  full support coverage, grounded-premise rate 1.0, dependency validity, and
  replay success 1.0.
- The four timed-out correct checkpoints must **not** be called formal trace-safe
  passes. Their checkpoint structures and verifier results were correct, but the
  timeout gate prevented final audit-trace credit.
- Arm C's two passing nozzle programs passed the frozen paired-drawing and
  counterfactual faithfulness probes. This is direct evidence that portable,
  non-hard-coded Datalog can work for that family.
- The timed-out Arm C reachability and equipment programs did not receive final
  faithfulness-gate credit. Even when their current-drawing checkpoint was
  exact, current-drawing correctness alone does not establish portable program
  faithfulness.
- Arm A has no cross-size Datalog faithfulness gate; it is judged through exact
  outcome grounding and the audit trace.

## Prioritized improvements

### P0 — Stop immediately on a valid executed checkpoint

Make the helper's successful checkpoint a runtime termination condition. Once
the checkpoint passes a local schema/replay preflight, the agent should call
completion and the harness should ignore further model-generated exploration.
Reserve an explicit finalization margin—for example, prohibit new exploratory
calls after 240 seconds and force submission from the latest valid checkpoint.

**Tests:**

1. An integration test where the agent creates a valid checkpoint, then asks to
   run more tools; assert that the episode terminates with the checkpoint.
2. A fake-provider latency test with a valid checkpoint at 230 seconds; assert
   completion before the 300-second agent deadline.
3. A no-checkpoint case at the cutoff; assert a clear forced-finalization reason
   and zero, rather than silent continuation.

### P0 — Make policy abstention schema-safe by construction

Give both arms a complete canonical JSON template, not an inner fragment. Better,
provide a tiny helper that atomically writes the prescribed abstention artifact,
just as the execution helpers write grounded checkpoints. Do not relax the
fail-closed parser to accept arbitrary aliases; that would hide contract drift.

**Tests:**

1. Generate both permission tasks and assert their instructions contain
   `witness_ids`, `answer_text`, and `support: {steps, claims}` in one complete
   object.
2. Execute the policy helper and pass its output through
   `parse_structured_answer` and the audit-trace validator.
3. Keep negative tests for `witnesses`, `explanation`, top-level `steps`, and
   `support_graph` so malformed aliases still fail closed.

### P0 — Harden KIRA tool-call validation

Validate the entire tool-call payload before iterating commands. If `commands`
is not a list of objects, return a bounded tool error to the model and permit one
repair turn. Track the repair as an integration event; do not silently coerce
DSML-like text into shell input.

**Tests:**

1. Replay the exact malformed Arm A equipment-large response and assert no
   `AttributeError` escapes.
2. Assert that a structured error is returned to the agent and that a corrected
   second tool call executes.
3. Fuzz command payload types (`str`, `null`, object, mixed list) at the adapter
   boundary.

### P1 — Reduce Arm C to a one-edit/one-run workflow

Preload an editable `analysis.dl` in `/workspace` with the includes, output
relation, and reusable topology predicates already present. Provide a short EDB
schema card and examples of only the allowed predicates. Remove the need to copy
a read-only template and discourage reading helper implementation files. Add a
bounded syntax-check command that reports one concise diagnostic.

**Tests/experiments:**

1. Offline replay against the nine frozen tasks with a scripted model stub that
   writes and executes exactly once; verify task packaging and faithfulness.
2. A/B the current prompt against the one-edit prompt on unpaid or local model
   runs, measuring calls-to-first-valid-checkpoint, command batches, and elapsed
   time.
3. Re-run the frozen counterfactual faithfulness gate on every generated program;
   do not trade speed for hard-coded IDs or drawing-specific logic.

### P1 — Enforce bounded inspection and context budgets

Reject or rewrite obvious full-file reads of the large graph artifacts. Supply
purpose-built read-only inspection commands for label lookup, edge filtering,
and node/edge counts, returning bounded JSON. Track cumulative prompt tokens and
prevent repeated inclusion of unchanged terminal output.

**Tests/experiments:**

1. A command-policy test that blocks `cat` of known large inputs but permits
   `grep`, `head`, `sed`, and bounded query helpers.
2. A trajectory regression asserting the small nozzle task reaches first script
   execution without printing either full graph file.
3. Compare input tokens, completed calls, and time-to-checkpoint before and after
   terminal-output deduplication.

### P1 — Instrument time-to-checkpoint separately from time-to-finish

Persist timestamps for first valid checkpoint, last valid checkpoint,
`task_complete`, agent timeout, verifier start/end, provider latency, and tool
latency. The present artifacts allow reconstruction, but not always exact
allocation—especially for an interrupted provider request.

**Tests:** deterministic fake-clock tests for each phase and a report-level test
that classifies `semantic_checkpoint_then_timeout` separately from
`no_checkpoint_timeout` while preserving the formal zero.

### P2 — Test provider latency as a controlled variable

Only after the workflow fixes, compare the same locked tasks using fixed model,
temperature, prompts, and budgets across providers or routing policies. Primary
metrics should be p50/p95 call latency, first-valid-checkpoint rate by 240
seconds, and formal qualification—not prose quality. This experiment requires
fresh authorization because it makes paid calls; this document proposes it but
does not run it.

## Recommended next evaluation sequence

1. Implement P0 fixes and the offline regression suite.
2. Run the entire matrix with deterministic/fake providers to prove timeout,
   schema, parser, trace, and faithfulness mechanics.
3. Run a small unpaid/local pilot to measure calls and time-to-checkpoint.
4. Freeze a new protocol version only if the method changes materially.
5. With explicit approval, run one fresh paid matrix—no reuse or retry of this
   preserved attempt—and report both formal credit and diagnostic component
   rates.

The component rates should be reported separately: semantic checkpoint,
deadline completion, canonical submission validity, executed-artifact validity,
audit-trace safety, and Datalog faithfulness. The all-nine qualification rule can
remain the production-readiness gate; the component rates explain what to fix.

## Conclusion

Both arms are plausible engineering directions. Arm A already solved both
reachability tasks and small equipment connectivity; Arm C produced portable,
faithful Datalog for both nozzle tasks and handled both policy controls safely.
The failures cluster around orchestration: deadline management, unnecessary
turns after success, schema construction, tool-call validation, and Datalog
authoring ergonomics.

The correct conclusion is therefore narrower than “the models cannot answer the
questions”: **the current agent systems do not yet package answers reliably under
the five-minute auditable-execution contract.** The preserved artifacts identify
specific, testable improvements that could make either arm substantially
stronger without weakening the benchmark's safety requirements.
