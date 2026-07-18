# rmso.1 agent redesign after the incomplete scored run

## Status

This is a post-run redesign record. It does not amend the preregistered protocol or
turn `.tmp/rmso-live-20260718-scored-03` into valid evaluation evidence. Any future
paid comparison using this design needs a fresh protocol/lock, explicit approval, and
a new output directory after the accounting defects recorded in
`rmso.1-scored-run-2026-07-18.md` are resolved.

## What the logs showed

The observed failures were not well explained by a simple lack of reasoning ability.

- Arm A received raw XML even though the questions and witness contract were defined
  over graph UUIDs and normalized graph-edge attributes. For the inspected nozzle
  item, the expected witness UUIDs did not occur in the raw XML. Arm A therefore had
  to reconstruct a graph identity mapping that its input did not contain.
- Several episodes reached a useful conclusion or a working intermediate artifact,
  then exhausted the episode while inspecting, revising, or manually constructing the
  final audit-shaped JSON.
- Unbounded whole-file output consumed context without improving the decision. The
  large graph artifacts were especially costly when printed rather than queried.
- Arm C paid avoidable setup cost recreating a standard Souffle module and manually
  translating engine output into the submission schema.

These are harness and interface defects mixed with model performance. They prevent a
clean inference about whether direct reasoning or engine-mediated reasoning is better.

## Revised comparison

Both arms now receive the same stable, answer-neutral `graph_inspection.json`. It
contains all node and edge identities plus the normalized fields needed for targeted
inspection, but contains no oracle, derived verdict, or precomputed witness set.

Arm A is now graph-direct:

- inputs: canonical `graph_facts.json` and the shared inspection index;
- method: standard-library Python and bounded `grep`/`head`/`sed` inspection;
- executable artifact: `analysis.py`, replayed against `graph_facts.json`;
- no raw XML, Souffle engine, rule packs, or hidden project reasoning code.

Arm C keeps its engine-mediated distinction:

- inputs: the same canonical graph facts and inspection index, plus the allowed
  Souffle EDB and topology IDB layers;
- method: a supplied portable `analysis.dl` skeleton and real Souffle execution;
- executable artifact: the unchanged query module, still subject to UUID-literal,
  counterfactual, cross-size, replay, and audit-trace gates;
- no raw XML, graph export, rule packs, oracle, or hidden project reasoning code.

The causal contrast is therefore Python-direct reasoning versus authored Souffle over
the same graph information, rather than raw-XML reconstruction versus normalized facts.

## Finish-first execution contract

Each arm receives a small mechanical runner:

- Arm A runs `python3 /input/run_analysis.py /workspace/analysis.py`.
- Arm C runs `python3 /input/run_query.py /workspace/analysis.dl`.

On every successful execution, the runner validates the output IDs against graph scope
and atomically replaces a replay artifact and/or `structured_answer.json` with a
complete audit-shaped checkpoint. A later successful revision replaces the checkpoint;
a failed later revision leaves the last executed answer intact. Diagnostics are bounded
to avoid flooding model context.

This separates semantic work from mechanical packaging and addresses the observed case
where an episode had enough information to answer but timed out before submission.

## Interpretation boundary

This redesign should make both arms stronger. It deliberately makes Arm A much stronger
by removing an identity/provenance handicap. Arm C is strengthened through cheaper
inspection, a starter query, bounded execution diagnostics, and automatic packaging—not
through answer-specific rules or examples.

A future result may answer the architecture question only if the new design is frozen
before calls and the cost/output-limit accounting gaps from the incomplete run are also
closed. Until then, the earlier 0/9 versus 5/9 is diagnostic only.
