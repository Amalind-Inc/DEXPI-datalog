# Context

This repository turns DEXPI 1.3 source files into graph-mirrored facts and
then derives deterministic Souffle predicates for verification. The current
trust boundary is `pyDEXPI` for XML-to-graph extraction and this repository
for graph-to-facts export plus derived classification and utility layers.

## Language

**DEXPI 1.3 source file**:
A single DEXPI 1.3 XML export that acts as the authoritative engineering input
to this repository.
_Avoid_: DEXPI 2.0 input, semantic IR source

**pyDEXPI full graph**:
The upstream directed graph export produced from a DEXPI 1.3 source file by
`pyDEXPI` without project-owned semantic abstraction.
_Avoid_: canonical graph, normalized graph

**canonical base fact layer**:
The persisted project-owned fact export that mirrors the pyDEXPI full graph
with stable ordering and provenance.
_Avoid_: semantic IR, curated predicate layer

**graph-shaped fact export**:
A fact export whose stable unit is one extracted node, one extracted edge, or
one attribute attached to a node or edge.
_Avoid_: XML-shaped export, domain-shaped export

**generic attribute fact**:
A persisted fact that records an attribute as a key-value pair instead of
committing that attribute to a dedicated predicate name.
_Avoid_: typed base predicate

**graph-mirrored fact vocabulary**:
The deterministic logic fact vocabulary emitted from the canonical base fact
layer.
_Avoid_: rule-specific fact vocabulary, inferred fact vocabulary

**generic graph utility layer**:
The first derived Datalog layer built over the canonical base fact layer using
reusable graph predicates such as traversal, containment, adjacency, and
attribute filtering.
_Avoid_: operator rule layer, pump-specific logic layer

**classification policy**:
The repo-owned derived-logic policy that maps generic exported graph facts into
stable edge families and later semantic helpers.
_Avoid_: exporter schema, rule-specific hardcoding

**supported DEXPI 1.3 fixture corpus**:
The set of parseable DEXPI 1.3 training fixtures that the repository uses as
its broad regression and coverage surface for graph-mirrored export.
_Avoid_: fuzz corpus, random test input

**rule**:
One executable logical check evaluated against the fact layer and its derived
utility predicates.
_Avoid_: policy document, rule pack

**rule pack**:
A versioned collection of rule definitions and configuration used by the engine
to evaluate a run.
_Avoid_: document, single rule

**policy source document**:
A human-authored natural-language source such as a regulation, standard,
operator procedure, or internal compliance memo from which candidate rules may
be derived.
_Avoid_: executable rule pack

**rule-pack synthesis**:
The process of deriving a candidate executable rule pack from a policy source
document and associated examples.
_Avoid_: direct trusted execution

**manifest**:
The immutable run configuration that identifies the input source, rule pack
version, execution mode, and output destination for one run.
_Avoid_: input file, request

**finding**:
A single rule-evaluation result tied to a specific subgraph, with a severity,
evidence trail, and provenance.
_Avoid_: issue, anomaly blob

**finding severity**:
The project-facing classification used for rule evaluation results and review
artifacts.
Allowed values: `hard violation`, `soft advisory`, and `informational`.
_Avoid_: parser severity

**evidence trail**:
The structured record of the rule, facts, object identities, and context that
justify a finding or patch proposal.
_Avoid_: explanation only, free-text rationale

**patch proposal**:
A single atomic, reviewable edit generated for one finding.
_Avoid_: batch fix, implicit mutation

**validation state**:
The persisted status assigned to an affected connected subgraph, such as
valid, needs review, blocked, or conflicted.
_Avoid_: whole-file verdict

**review-only**:
A run mode that reports raw findings and evidence without producing patch
proposals.
_Avoid_: dry-run

**dry-run**:
A preflight mode that validates the run configuration, source file, and
structural derivations without emitting findings or patch proposals.
_Avoid_: review-only

**affected connected subgraph**:
The minimal connected portion of the engineering graph required to evaluate a
rule, justify a finding, and explain the proposed patch.
_Avoid_: full graph, arbitrary neighborhood

**pump discharge-path rule family**:
A class of verification rules that evaluates the downstream discharge-side
topology of a pump against required protection and control expectations.
_Avoid_: generic topology rule

**discharge neighborhood**:
The rule-bounded directed downstream path that starts at a pump discharge
connection and stops at the first terminating boundary of interest.
_Avoid_: whole plant neighborhood

**first unbranched downstream segment**:
The default evaluation scope for the initial pump discharge-path tracer-bullet.
It starts at the pump discharge connection and stops at the first branch or
terminal object.
_Avoid_: arbitrary downstream closure

**evaluation depth**:
The strict policy-defined traversal scope used when evaluating a topology rule.
Evaluation depth is owned by the rule pack and is not widened by the manifest
at runtime.
_Avoid_: user-expanded path depth

**discharge nozzle**:
The process nozzle of a centrifugal pump identified as the source of the first
outgoing downstream segment for rule evaluation.
_Avoid_: synthetic nozzle role

**inline continuity item**:
A simple in-line piping item that the verifier may ignore while traversing a
first unbranched downstream segment toward a required component.
_Avoid_: required boundary component

**branch boundary**:
The first downstream topology point at which more than one distinct
continuation path exists from the current path.
_Avoid_: any multi-edge node

**evaluation diagnostic**:
A diagnostic emitted when the verifier cannot determine or traverse the rule's
required evaluation scope from the source model with sufficient certainty.
_Avoid_: standards finding

**off-page bounded failure**:
A local standards failure emitted when the first unbranched downstream segment
reaches an off-page connector before the required component is found.
_Avoid_: generic traversal failure

**check-valve presence requirement**:
The initial tracer-bullet acceptance rule that a centrifugal pump discharge
path is satisfied by the presence of any downstream DEXPI `CheckValve`
subclass on the first unbranched downstream segment.
_Avoid_: generic valve requirement

**discharge check-valve requirement**:
The initial pump discharge-path tracer-bullet rule stating that the first
unbranched downstream segment from a centrifugal pump discharge must contain a
check valve before the first terminal object or branch.
_Avoid_: all pump rules

**strict rule severity**:
Any rule the operator has provided as a strict requirement produces a hard
violation by default unless the rule explicitly specifies a different severity.
_Avoid_: parser severity

**discharge segment finding identity**:
The stable verifier finding identity for the initial discharge check-valve
rule.
_Avoid_: transient finding id

**findings-only rule**:
A rule execution mode that emits findings and evidence without producing patch
proposals.
_Avoid_: auto-fix rule

**discharge rule evidence set**:
The minimum evidence required for every v1 discharge-rule finding.
_Avoid_: free-form explanation
