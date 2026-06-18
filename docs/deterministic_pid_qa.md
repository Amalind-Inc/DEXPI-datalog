# Deterministic P&ID QA Seam

This document describes the first deterministic P&ID QA seam built around DEXPI
1.3 graph facts, derived Datalog, the query corpus, and deterministic query
artifacts.

The product rule is strict: deterministic query output is the source of truth for
P&ID QA and compliance answers. Natural-language systems may help later, but
they do not answer compliance questions on their own.

## Fact Layers

`graph_facts.json` is the canonical base fact layer. It mirrors the pyDEXPI full
graph as stable graph-shaped facts: extracted nodes, extracted edges, and generic
attributes. It remains the auditable boundary for extraction output.

`derived_graph_semantics.dl` is the enriched derived graph semantics layer. It is
executable Datalog generated from the canonical base fact layer. This layer
exposes object identity and labels with predicates such as `node/1`,
`node_label/2`, `node_tag/2`, and `node_proteus_id/2`; it also classifies graph
edges into reusable utility predicates such as `reference_edge/3`,
`candidate_topology_edge/3`, `reachable/2`, and `downstream_reference/2`.

The derived layer is repository-owned interpretation logic. It can evolve as the
query library learns from real questions, but it does not replace
`graph_facts.json` as the canonical base fact layer.

## Execution Seam

Python is the Python orchestration Adapter. It loads query corpus metadata,
generates the narrow query Datalog for a supported query, combines that query
with `derived_graph_semantics.dl`, invokes the deterministic engine, renders
terminal output, and writes inspectable artifacts.

Souffle is the current deterministic engine. Query results are persisted as
`query_result.json`, the exact combined Datalog program is persisted as
`combined_query.dl`, and raw engine output is kept under
`internal/souffle-output/`.

ErgoAI is documented only as a future engine candidate. It is not a current
dependency, and no current answer depends on ErgoAI execution.

## LLM Boundary

LLMs are deferred. Future LLM integration may classify a natural-language
question, route it to a deterministic query, or explain deterministic results in
plain language.

LLMs may not produce compliance answers without deterministic query outputs.
They also may not invent missing query results, bypass deterministic execution,
or infer unsupported pump-discharge behavior when the query corpus says required
facts or predicates are missing.

## Query Corpus Lifecycle

Each query corpus entry lives under `queries/corpus/` and has its own lifecycle.

`supported_deterministic` entries have an implemented deterministic query path.
The command may execute them through Souffle and persist successful, failed, or
warning-bearing artifacts.

`unsupported_missing_predicates` entries are first-class product outputs. They
represent important questions that cannot execute yet because the derived graph
semantics layer is missing required predicates. Running them through the same CLI
and `--output-dir` seam returns a structured unsupported artifact instead of a
misleading answer.

`future_candidate` entries keep harder questions visible without pretending they
are ready. They can record missing predicates, missing facts or policy, expected
future result sets, and engine candidates.

This lifecycle lets the project grow from real QA questions: raw graph facts to
stable engineering predicates, reusable path predicates, and eventually promoted
validation templates.

## Predicate-Library Roadmap

`direct_process_connection/2` is the first CodeQL-style predicate-library
experiment. It derives an experimental process-facing relation from direct
`sourceItem` and `targetItem` references and can be compared against
`downstream_reference/2` and recursive `reachable/2`.

`direct_process_connection/2` is useful comparison evidence, but it is
experimental and not yet trusted process-flow semantics. Current artifacts should
say whether it appears equivalent to, broader than, narrower than, or only partly
overlapping lower-level predicates on representative fixtures.

Future predicate-library work should only promote new predicates when a real
query or rule needs them and persisted artifacts show what the new predicate adds.
