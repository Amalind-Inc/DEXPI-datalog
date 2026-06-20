# Deterministic P&ID QA Seam

This document describes the deterministic P&ID QA seam built around DEXPI 1.3
graph facts, derived Datalog, BYOK logic requests, and deterministic execution
artifacts.

The product rule is strict: deterministic execution output is the source of truth
for P&ID QA and compliance answers. Natural-language systems may draft, restate,
route, and explain, but they do not answer compliance questions on their own.

## Fact Layers

`graph_facts.json` is the canonical base fact layer. It mirrors the pyDEXPI full
graph as stable graph-shaped facts: extracted nodes, extracted edges, and generic
attributes. It remains the auditable boundary for extraction output.

`graph_facts.dl` is the generated Datalog EDB artifact. It is produced from the
canonical base fact layer and records graph-mirrored facts such as `node/1`,
`node_attribute/3`, `graph_edge/3`, and `graph_edge_attribute/5`.

`pydexpi_datalog/semantics/datalog/idb/graph_topology_semantics.dl` is the reusable
Datalog IDB. It owns graph topology semantics over the generated EDB, including
object aliases such as `node_label/2`, edge-family classification such as
`reference_edge/3`, and graph utility predicates such as
`candidate_topology_edge/3`, `reachable/2`, and `downstream_reference/2`.

`derived_graph_semantics.dl` is the combined executable Datalog artifact for
current callers. It assembles generated EDB plus reusable IDB so a generated
logic-request query can execute against one file.

The derived layer is repository-owned interpretation logic. It can evolve as the
query library learns from real questions, but it does not replace
`graph_facts.json` as the canonical base fact layer.

## Execution Seam

Python is the orchestration adapter. It generates Datalog EDB from
`graph_facts.json`, assembles EDB plus reusable IDB, resolves any selected source
node through derived graph semantics, records logic-request context, and writes
inspectable artifacts. LLM-assisted logic requests draft the narrow Datalog query
and English restatement; deterministic execution remains the answer source.

Souffle is the current deterministic engine. Executed logic-request results
should persist the generated Datalog, deterministic result sets, diagnostics, and
raw engine output needed to reproduce the answer.

ErgoAI is documented only as a future engine candidate. It is not a current
dependency, and no current answer depends on ErgoAI execution.

## Source Node Selection

OSS workflows process one DEXPI source file per run. Logic requests may target
one selected source node inside that file by source ID, tag, or Proteus ID.

`--source-id` is the exact graph object identifier for debugging and tests.
`--source-tag` and `--source-proteus-id` are human-facing selectors resolved
through the combined `derived_graph_semantics.dl` artifact using `node_tag/2` and
`node_proteus_id/2`. Source selection does not introduce multi-file or multi-page
context; artifacts record the resolution scope as a single DEXPI source file.

Selector failures are structured diagnostics. Missing selectors, no matches,
multiple matches, and conflicting selectors are reported without defaulting to an
arbitrary first graph node.

## LLM Boundary

LLM-assisted logic requests are in scope, but model access is BYOK. The model may
help classify a natural-language request, draft Datalog against the approved
predicate contract, produce an English restatement, and explain deterministic
results.

LLMs may not produce compliance answers without deterministic execution outputs.
They also may not invent missing result sets, bypass deterministic execution, or
infer unsupported pump-discharge behavior when required facts or predicates are
missing.

## Logic-Request Lifecycle

A logic request starts as natural language and may include optional source-node
selection. The workflow records route, model-access metadata, source context,
diagnostics, and any generated Datalog/restatement pair.

Generated Datalog is not a trusted answer. It must be inspectable, constrained to
the approved predicate contract, and executed by the deterministic engine before
the result can be used for QA.

Unsupported requests should return missing-capability diagnostics rather than a
best-effort answer. Those diagnostics are roadmap input for future derived graph
semantics and predicate-library work.

## Predicate-Library Roadmap

`direct_process_connection/2` is the first CodeQL-style predicate-library
experiment in `graph_topology_semantics.dl`. It derives an experimental
process-facing relation from direct `sourceItem` and `targetItem` references and
can be compared against `downstream_reference/2` and recursive `reachable/2`.

`direct_process_connection/2` is useful comparison evidence, but it is
experimental and not yet trusted process-flow semantics. Current artifacts should
say whether it appears equivalent to, broader than, narrower than, or only partly
overlapping lower-level predicates on representative fixtures.

Future predicate-library work should only promote new predicates when a real
query or rule needs them and persisted artifacts show what the new predicate adds.
