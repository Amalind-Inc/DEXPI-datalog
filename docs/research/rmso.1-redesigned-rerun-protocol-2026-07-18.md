# rmso.1 — Locked redesigned feasibility rerun protocol

- **Status:** locked after the incomplete diagnostic run and before any redesigned paid call
- **Bead:** `pydexpi-datalog-1-rmso.1`
- **Design revision:** `graph-direct-vs-souffle-v2`
- **Model:** `deepseek/deepseek-v4-flash`
**Purpose:** a post-diagnostic feasibility rerun, not an independent confirmatory benchmark

## Interpretation boundary

This protocol does not modify the original rmso.4 preregistration and does not validate
the incomplete run at `.tmp/rmso-live-20260718-scored-03`. The original run exposed both
accounting defects and a representation mismatch between the arms. Its outcomes are
diagnostic only.

The same nine questions are reused after their prior outcomes and traces were inspected.
That makes this a redesigned feasibility experiment, not a statistically independent
confirmation. A later product claim requires a fresh SME-certified holdout slice.

## Hypotheses

- **H1 — authoring feasibility:** V4 Flash can author faithful executable Souffle over
  canonical graph facts when setup and answer packaging are mechanical.
- **H2 — execution value:** over the same graph representation, the Souffle-capable arm
  qualifies when the Python-direct arm does not, or both qualify and Souffle has lower
  paid cost.
- **H3 — audit safety:** every qualifying answer has complete grounded and replayable
  observable support.

No conclusion may be produced when provider cost is unknown or the locked provider,
model, token, price, or routing policy was violated.

## Locked arms

Both arms receive the question, canonical `graph_facts.json`, and byte-identical
`graph_inspection.json`. The inspection artifact is answer-neutral: it contains every
node and edge identity, label, tag, edge label, and normalized `attr_name`, but no oracle,
verdict, derived answer, or precomputed witness set.

### Arm A — graph-direct Python agent

Arm A may use bounded `grep`, `head`, `sed`, and Python standard-library analysis. It
must submit `analysis.py`, replayed against `graph_facts.json`. It receives no raw XML,
Souffle engine, Datalog EDB/IDB files, rule packs, oracle, other episode, network, or
project reasoning code.

The supplied runner executes the script, validates witness IDs against graph scope, and
atomically checkpoints the replay and audit-shaped answer. The runner performs no
question-specific reasoning.

### Arm C — Souffle-capable agent

Arm C receives the same graph facts and inspection index plus their allowed Souffle EDB
and the topology IDB contract. It may author only portable IDB/query rules and execute
Souffle. It receives no raw XML, graph export, rule packs, oracle, other episode, network,
or project reasoning code.

The supplied starter declares the two allowed includes and `result_witness`. The runner
executes it, bounds diagnostics, validates result IDs against graph scope, and atomically
checkpoints an audit-shaped answer. Neither artifact contains question-specific rules.
The final program remains subject to UUID-literal rejection, unchanged cross-size replay,
counterfactual probes, and audit replay.

### Shared finish-first rule

Every successful execution replaces the provisional answer. A failed later revision
leaves the last successfully executed checkpoint intact. Only the final preserved
executable artifact and its replayed output may support the submitted conclusion.

## Shared live configuration

- Exact model `deepseek/deepseek-v4-flash`; no alternate-model fallback.
- Reasoning effort `high`; temperature `0`.
- OpenRouter provider routing sorted by price, with all parameters required and fallback
  limited to providers serving the pinned model.
- One scored episode per arm and entry; no episode retry, best-of-N, or replacement.
- Five-minute episode timeout; 8,192 combined completion-token ceiling.
- Frozen episode limits: 64 turns, 128 commands, 8,192 output tokens, 300-second agent
  timeout, and 60-second verifier timeout.
- Sequential episodes and arms, so every provider call has exactly one active
  `(arm_id, question_id)` attribution.
- Hard cumulative paid-call ceiling of USD 10 using worst-case pre-call reservation and
  the locked provider price ceilings.

## Fixed slice and scoring

The exact ordered nine-entry slice, SME-certified ground truth, witness precision,
recall, F1, `grounded_answer_credit`, exact qualification gate, permission abstention
rule, audit-trace gate, and Arm C faithfulness probes remain as specified in the original
rmso.4 protocol and source manifests. The replacement lock hashes those sources and this
document without copying ground truth.

An arm qualifies only if all nine episodes earn exact credit `1.0`, every support trace
is mechanically safe, both permission controls abstain, and every applicable Arm C core
program passes all faithfulness probes.

| Arm A qualifies | Arm C qualifies | Redesigned feasibility result |
| --- | --- | --- |
| No | No | `NO-GO / rethink` |
| Yes | No | Python-direct wins; do not justify Souffle |
| No | Yes | `GO`: execution capability is required on this slice |
| Yes | Yes | Lower total paid USD wins; exact tie goes to Python-direct |

The original large-only interpretation override is removed: both redesigned arms receive
the same graph representation and compact index. Any advantage is still limited to this
post-diagnostic slice until reproduced on a fresh holdout.

## Fail-closed provider accounting

Every gateway call must be archived with call number, arm ID, question ID, reservation,
locked request, response or transport error, provider metadata when available, token
usage, and reported cost.

- A successful provider response settles its reported billed cost before model,
  provider, or output-limit eligibility is checked. A rejected-but-billed response still
  counts toward episode, arm, run, and spend-cap totals.
- A response-less timeout, reset, or transport failure releases its reservation but is
  permanently marked `unknown_cost`; it is never treated as zero.
- A provider policy violation is preserved even when cost is completely known.
- Provider-ledger cost, rather than trajectory metadata, populates every episode's
  `cost_usd`; arm totals are the sum of attributed episode costs.
- Unknown cost, missing attribution, an unsettled reservation, or any model/provider/
  token/price policy violation makes the run-level formal status `INCOMPLETE`.
- An incomplete run must return a non-success CLI status and must not generate a GO,
  NO-GO, winner, or cost-per-credit decision.

## Required artifacts

Preserve the replacement lock and hashes; materialized manifest; exact arm inputs and
instructions; all Harbor trajectories and executable artifacts; every provider request,
response, error, reservation, attribution, and ledger record; per-episode and per-arm
provider accounting; audit and faithfulness results; and the fail-closed run summary.

## Preconditions for a paid rerun

1. Gateway tests prove billed rejection settlement, response-less unknown cost, and
   reservation release.
2. Every provider call is attributed to one episode and both arm reports obtain costs
   from that ledger.
3. Run-level status becomes `INCOMPLETE` for unknown cost, unsettled reservation, or any
   provider-policy violation.
4. The complete scripted/local-Souffle dry run and repository suite pass under this
   design revision.
5. The user explicitly authorizes the paid replacement and a never-used output directory.
