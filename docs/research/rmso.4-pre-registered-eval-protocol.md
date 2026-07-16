# rmso.4 — Pre-registered grounded-verdict evaluation protocol

**Status:** locked before any scored live call  
**Bead:** `pydexpi-datalog-1-rmso.4`  
**Model:** `deepseek/deepseek-v4-flash`  
**Purpose:** a small feasibility proof, not a statistically powered benchmark

This protocol decides between two production-shaped methods:

- **Arm A — general-purpose agent:** a minimal read-only agent over raw DEXPI XML.
- **Arm B — logic-capable agent:** an agent over the canonical EDB/predicate contract
  that may author and execute Soufflé/Datalog.

The experiment asks whether logic capabilities make a cheap model shippably correct and
grounded. It does not require either arm to reproduce an oracle's proof text or deduction
order.

The final verdict and exhaustive result witnesses are the primary product outcome. A
correct outcome is nevertheless not shippable when its observable derivation contains a
fabricated premise, invalid inference, contradiction, prohibited source, or an
unreplayable evidence gap. High-consequence adoption requires both answer correctness and
an inspectable safe derivation.

No scored call may run until the product owner has certified the harder-question ground
truth in `rmso.7`, the counterfactual probes below are checked in and oracle-verified, and
the live configuration matches this document.

## Hypotheses

- **H1 — logic authoring feasibility:** V4 Flash can author a faithful executable program
  over the canonical EDB.
- **H2 — product value:** the logic-capable agent qualifies when the general-purpose
  agent does not, or both qualify and the logic-capable agent has lower cost per correct,
  grounded answer.
- **H3 — audit safety:** every qualifying answer has complete, grounded, replayable
  observable support, independent of which arm produced it.

A cheap but ungrounded answer is unshippable. Correctness and grounding qualify a method
before cost is allowed to choose between methods.

## Locked arms

### Arm A — general-purpose agent

Arm A receives the question and the complete raw DEXPI XML for that drawing.

Allowed:

- minimal `read`, `grep`, and sandboxed `bash` tools;
- writable temporary scratch space for scripts and intermediate results;
- chain-of-thought/internal reasoning and multiple model turns inside the episode.

Forbidden:

- network access;
- canonical `graph_facts`, EDB exports, topology IDB, Soufflé, rule packs, or existing
  project reasoning code;
- access to ground truth, oracle definitions, the other arm's artifacts, or another
  episode.

### Arm B — logic-capable agent

Arm B receives the question, canonical grounded EDB facts, and the allowed predicate
contract. It receives the same minimal shell/scratch capability plus Soufflé.

It may:

- author a query and rules;
- define arbitrary helper/derived **IDB** predicates from allowlisted EDB and other IDB
  predicates;
- execute, inspect diagnostics and output, and revise within the episode.

It may not invent EDB facts, read unapproved sources, hard-code hidden drawing UUIDs or
precomputed witness IDs, or submit an answer not produced by its executed final program.

## Shared live configuration

- Exact model: `deepseek/deepseek-v4-flash`; no model substitution or fallback model.
- Reasoning effort: `high`.
- Temperature: `0`.
- OpenRouter routing: explicit `provider.sort = "price"`, require support for all
  requested parameters, and allow fallback only between providers serving the same
  pinned V4 Flash model.
- Record the resolved model, provider, effective settings, usage, and price for every
  paid call.
- One scored episode per arm × entry; one final answer per episode.
- No fresh-episode retry, replay, best-of-N, or replacement of an incorrect, malformed,
  timed-out, or failed episode.
- Intermediate reasoning, tool use, program executions, and revisions are allowed inside
  the one episode.
- Hard wall-clock ceiling: **five minutes per episode**, measured from the first model
  call through final submission. Timeout earns zero credit; incurred cost still counts.
- The time ceiling, rather than a revision-count limit, is the binding loop boundary.
  Turn/command limits must be set high enough not to bind first and must be recorded.

A same-model OpenRouter provider fallback inside one API request remains part of the same
episode. It does not create another scored attempt.

## Fixed nine-entry slice

Every arm runs the same nine entries. The order must be fixed in the run artifact before
the first live call.

| Role | Question ID | Size | Expected verdict | Expected witnesses |
| --- | --- | --- | --- | ---: |
| Shallow control | `ha-e03-pump-p4713-retrieval` | unbucketed | `violation_found` | 1 |
| Exhaustive disjunctive join | `hq-nozzle-piping-attachment-small` | small | `violation_found` | 4 |
| Exhaustive disjunctive join | `hq-nozzle-piping-attachment-large` | large | `violation_found` | 3 |
| Directed multi-hop reachability | `hq-valve-monitoring-reachability-small` | small | `no_violation` | 0 |
| Directed multi-hop reachability | `hq-valve-monitoring-reachability-large` | large | `violation_found` | 8 |
| Undirected connectivity / hallucination resistance | `hq-equipment-pump-connectivity-small` | small | `no_violation` | 0 |
| Undirected connectivity / hallucination resistance | `hq-equipment-pump-connectivity-large` | large | `no_violation` | 0 |
| Permission/defeasible safety control | `hq-permission-defeasible-control-small` | small | `unanswerable` | 0 |
| Permission/defeasible safety control | `hq-permission-defeasible-control-large` | large | `unanswerable` | 0 |

The instrumentation-actuation pair is deliberately excluded as redundant reverse
traversal under this spike's cost constraint. The full 30-question `3q1` hand-authored
slice is reserved for a later funded validation run and cannot be added post hoc.

## Outcome scoring

For one episode, let `G` be the oracle result-witness set and `P` the returned
result-witness set.

```text
precision = |P ∩ G| / |P|
recall    = |P ∩ G| / |G|
F1        = 2 × precision × recall / (precision + recall)
```

Boundary rules are locked:

- `P = G = ∅` gives precision = recall = F1 = `1`;
- exactly one of `P` and `G` being empty gives F1 = `0`;
- an unknown/invented ID is part of `P`, is never creditable, and prevents exactness.

`verdict_match` is `1` when the returned verdict exactly equals the oracle verdict and
`0` otherwise.

```text
grounded_answer_credit = verdict_match × witness_F1
```

The score is path-independent. Result witnesses name the exhaustive violating or matching
objects, not an ordered proof trace. Distinct sound programs and derivations receive the
same outcome score.

## Proof support and engine faithfulness

Full outcome credit requires the exact result/rule witness set. Proof support is more
permissive: any grounded, subset-minimal valid derivation is acceptable. Premise order and
textual similarity to an oracle derivation are irrelevant. Unused grounded facts outside
the minimal support do not invalidate a valid proof; invented facts can never support it.

For exhaustive or negative conclusions, execution over the complete closed EDB supplies
the support rather than a small ordered list of positive premises.

An Arm B core program must also pass all applicable mechanical faithfulness checks:

1. Compile and execute over only the approved EDB/predicate contract and authored IDB.
2. Contain no hidden drawing UUID or precomputed witness literal that was not stated in
   the question.
3. Produce the exact oracle result on its episode drawing.
4. Run unchanged on the matched other-size drawing and produce that drawing's exact
   oracle result.
5. Pass deterministic, pre-committed counterfactual EDB probes whose expected changes are
   oracle-derived. These probes must reject vacuous always-empty, always-nonempty, or
   drawing-hard-coded programs.

The permission/defeasible entries require abstention and no executable verdict program.
The shallow control and Arm A have no cross-size program-faithfulness gate; their exact
outcome grounding still gates qualification.

No LLM judge, canonical program, or canonical proof sequence decides faithfulness.

## Verified audit trace

The benchmark does not claim access to a model's complete latent reasoning. It preserves
and grades the **observable audit trace**: model messages exposed by the provider, tool
calls, commands, scripts, files, source references, execution results, revisions, and the
dependency links the arm submits for its final claims.

Every final verdict claim and result witness must link to at least one replayable support
path. Each submitted support step must declare one of:

- a grounded source premise with an exact XML or EDB reference;
- an observed tool/execution result with its artifact reference; or
- a derived claim with explicit dependencies and the operation/rule that derives it.

Mechanical trace checks are architecture-neutral:

1. **Coverage:** every final verdict claim and witness has a support path.
2. **Grounding:** every cited source premise exists exactly in the allowed source.
3. **Replayability:** every script, query, or program used by a support path reproduces
   its cited intermediate and final results in the frozen sandbox.
4. **Dependency validity:** every derived claim follows from its declared grounded or
   replayed dependencies under the submitted operation/rule.
5. **Consistency:** no support step contradicts the frozen source, another required step,
   the final structured answer, or the permission/defeasible abstention boundary.
6. **Policy compliance:** no support path uses a prohibited source, tool, network call,
   hidden oracle artifact, or another episode.
7. **History integrity:** failed and superseded attempts remain in the transcript; the
   submitted support path must identify the final relied-upon artifacts without rewriting
   history into a post-hoc clean story.

A correct final answer is **trace-unsafe and does not qualify** if any required claim lacks
support or if any relied-upon support path contains an invented premise, invalid
dependency, contradiction, prohibited source, or unreplayable computation.

Trace presentation quality is reported separately and cannot rescue an incorrect or
trace-unsafe answer. Report at least: support coverage, grounded-premise rate, replay
success, invalid/unsupported relied-upon steps, total observable steps, superseded steps,
tool calls, trace tokens, and the size of the final relied-upon support subgraph. A shorter
trace is not automatically better; a smaller fully verified support subgraph is the
relevant cleanliness signal.

After mechanical grading, the SME may review anonymized Arm A/Arm B traces side by side
for process-engineer usability. Preference alone cannot change the benchmark verdict. A
concrete SME allegation of an unsafe step must be recorded, reproduced against the frozen
artifacts, and only changes qualification if the mechanical audit confirms it.

## Cost accounting and spend safety

Every paid inference call attributable to an episode counts, including initial calls,
internal reasoning, failed attempts, diagnostics, revisions, verification calls, and calls
that end in timeout, abstention, or malformed output.

Excluded from arm cost:

- deterministic benchmark grading and local oracle replay;
- unmetered local Soufflé execution;
- SME work and benchmark-development work.

Tokens, model calls, wall time, and local executions are reported separately. Missing
provider cost makes the run incomplete; it is never interpreted as `$0`.

For arm `a`:

```text
total_credit(a) = Σ episode_credit
north_star(a)   = total_paid_USD(a) / total_credit(a)
```

If total credit is zero, the north-star is positive infinity.

The full scored run has a hard **$10 cumulative paid-call ceiling**. Do not start another
paid call after recorded cumulative spend reaches the cap. An already-running call may
produce only its bounded in-flight overage. If the cap prevents all 18 episodes from
finishing, preserve the artifacts and report `INCOMPLETE`; do not compute a GO verdict
from a selected subset. Raising the cap requires explicit product-owner approval.

## Qualification and decision rule

An arm qualifies only if every one of its nine episodes earns credit `1.0`. Therefore:

- every verdict is correct;
- every result-witness set is exact;
- both permission/defeasible entries abstain correctly;
- there are no invented or extra result witnesses;
- every final claim and witness has a complete grounded, replayable, mechanically valid
  observable support path with no relied-upon unsafe step;
- for Arm B, every applicable core program also passes the mechanical faithfulness gate.

Partial precision/recall/F1 remains diagnostic but cannot make an arm shippable.

| Arm A qualifies | Arm B qualifies | Pre-registered result |
| --- | --- | --- |
| No | No | `NO-GO / rethink`: neither method is shippable |
| Yes | No | General-purpose agent wins; do not justify the logic engine |
| No | Yes | `GO`: logic capabilities are required on this slice |
| Yes | Yes | Lower USD per grounded-answer credit wins |

When both qualify, each has total credit `9`, so the north-star comparison is equivalent
to comparing total paid USD. Cost is never allowed to rescue a method that failed
qualification. If both qualifying arms have exactly equal reported cost, the
general-purpose agent wins on parsimony: the logic substrate added no measured outcome,
audit-safety, or cost advantage.

## Required run artifacts

The run is auditable only if it preserves:

- frozen question order and manifest/source hashes;
- exact prompts, tool policy, model/provider settings, and environment identifiers;
- per-call tokens, costs, resolved provider, timestamps, and errors;
- per-episode transcripts, command/tool history, wall time, and final structured answer;
- submitted claim-to-support dependency links and the mechanically reduced final support
  subgraph;
- Arm B's final executed program, all observed diagnostics, execution outputs, unchanged
  cross-size replay, and counterfactual-probe results;
- per-episode verdict match, precision, recall, F1, credit, and qualification reason;
- per-episode trace coverage, grounding, replay, dependency-validity, consistency, policy,
  history-integrity, and cleanliness diagnostics;
- aggregate cost, credit, north-star, spend-cap status, and mechanically generated verdict.

## Implementation prerequisites — no live run before these are green

1. Change every RMSO live-arm mapping from V4 Pro to
   `deepseek/deepseek-v4-flash` and assert the exact resolved model in tests.
2. Add the identical OpenRouter routing/reasoning/sampling parameters to both arms and
   record the resolved provider per call.
3. Make the five-minute timeout bind both agentic arms and ensure timeout degrades to a
   scored zero-credit episode rather than crashing or retrying.
4. Enforce the cumulative $10 guard before each paid call.
5. Materialize the exact nine-entry selection without duplicating mutable ground truth;
   fail if a source manifest changes or `rmso.7` lacks SME certification.
6. Add precision/recall/F1/credit fields without replacing the existing exact-set grade.
7. Implement and freeze the mechanical cross-size and counterfactual faithfulness probes.
8. Extend the answer artifact with claim-to-support dependency links and implement the
   architecture-neutral trace checks without using an LLM judge.
9. Dry-run the complete path with scripted providers and local Soufflé; one non-scored live
   infrastructure smoke may validate connectivity/billing, but it may not reuse a scored
   entry or create a replacement attempt.
