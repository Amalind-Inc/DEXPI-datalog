# Context

## canonical engineering IR
The project-owned intermediate representation used to normalize parser output
before fact export and validation.
The canonical engineering IR is a lossless superset of the source DEXPI data
and preserves vendor/source IDs, engineering tags, and other source metadata
needed for traceability.

## raw parser output
The data pyDEXPI returns directly before this repository adapts it into the
canonical engineering IR. It is the upstream evidence layer used to locate
parser-originated errors.

## adapter diagnostics
Warnings and errors produced while converting raw parser output into the
canonical engineering IR. The project attaches these diagnostics to the IR
rather than returning them as a separate result.
Diagnostics may represent hard failures or soft ambiguities, and each entry
must carry a severity.

## diagnostic severity
A fixed set of allowed values used by adapter diagnostics to classify
hard failures versus soft ambiguities.
Allowed values: `info`, `warning`, `error`.
An `error` severity does not prevent the canonical engineering IR from being
produced.

## diagnostic code
A stable machine-readable identifier attached to each adapter diagnostic in
addition to its human-readable message.
Diagnostic codes use namespaces to distinguish parser-originated issues from
adapter-originated issues.
Namespaces: `parser.*`, `normalizer.*`, and `loader.*`.

## finding severity
The project-facing classification used for rule evaluation results and review
artifacts.
Allowed values: `hard violation`, `soft advisory`, and `informational`.

## evidence trail
The explicit justification attached to every finding and patch proposal.
An evidence trail records the primary rule, supporting facts, affected object
identities, and the proposed edit so the result remains auditable.

## patch proposal
A single atomic suggested edit produced for one finding.
Patch proposals may add or modify topology, attributes, and metadata, but do
not perform deletions in the initial workflow.

## rule pack
A versioned collection of rule definitions and configuration separate from
the engine code.
Rule packs carry operational scope and may optionally carry provenance
metadata such as jurisdiction, standard, and version.

## operational scope
The required applicability boundary for a rule pack.
Operational scope uses plant, unit, and equipment scope to decide where a rule
applies.

## provenance metadata
Optional rule-pack metadata that identifies the policy source and revision.
Examples include jurisdiction, standard, and version.

## manifest
The immutable run configuration that identifies the input source, rule pack
version, execution mode, and output destination for one run.

## rule pack
A versioned collection of rule definitions and configuration used by the
engine to evaluate a run.

## finding
A single rule-evaluation result tied to a specific subgraph, with a severity,
evidence trail, and provenance.

## evidence trail
The structured record of the rule, facts, object identities, and context that
justify a finding or patch proposal.

## patch proposal
A single atomic, reviewable edit generated for one finding.

## validation state
The persisted status assigned to an affected connected subgraph, such as
valid, needs review, blocked, or conflicted.

## review-only
A run mode that reports raw findings and evidence without producing patch
proposals.

## dry-run
A preflight mode that validates the run configuration, source file, and
structural derivations without emitting findings or patch proposals.

## affected connected subgraph
The minimal connected portion of the engineering graph required to evaluate a
rule, justify a finding, and explain the proposed patch.
