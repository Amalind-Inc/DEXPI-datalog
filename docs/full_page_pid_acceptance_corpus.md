# Full-Page P&ID Acceptance Corpus

This document defines the acceptance corpus and success matrix for the OSS v1
user-facing logic-request review workflow.

The acceptance target is full-page DEXPI 1.3 P&ID review behavior, not tiny XML
fragments. Small fragments may still be used for narrow parser-error tests, but
they do not count toward OSS v1 product acceptance.

## Acceptance Corpus

The primary acceptance corpus is selected from the public DEXPI 1.3 training
documents already present in `TrainingTestCases/dexpi 1.3/example pids`. These
documents already have checked-in graph-fact outputs under
`testdata/graph_contract/corpus`.

| ID | Source document | Classification | Coverage role | Current graph-fact baseline |
| --- | --- | --- | --- | --- |
| `c01-reference-pid` | `C01 DEXPI Reference P&ID/C01V04-VER.EX01.xml` | public full-page reference P&ID | broad reference sheet; simple pump/valve/line and mixed equipment topology | 214 nodes, 376 edges |
| `c02-process-column-basf` | `C02 Process Column (BASF)/C02V03-VER.EX02.xml` | public full-page process P&ID | process column, equipment hierarchy, fuller plant topology | 87 nodes, 146 edges |
| `c03-piping-equinor` | `C03 Piping (Equinor)/C03V04-VER.EX02.xml` | public full-page piping P&ID | piping-centered topology and line traversal | 52 nodes, 98 edges |
| `e06-pump-heat-exchanger-pns` | `E06 Pump, HeatExchanger, Nozzles Connected With PNS/E06V01-VER.EX01.xml` | public DEXPI 1.3 P&ID example | pump plus heat-exchanger with nozzle and piping-network-system connectivity | 18 nodes, 21 edges |
| `i06-flow-control-valve` | `I06 CCR flow indication and high alarm, flow control, control valve/I06V01-VER.EX01.xml` | public DEXPI 1.3 P&ID example | instrumentation/control-heavy topology with control valve | 25 nodes, 44 edges |
| `p04-pipe-intersection` | `P04 Pipe With Intersection/P04V01-VER.EX01.xml` | public DEXPI 1.3 P&ID example | branching or merging topology through a pipe intersection | 12 nodes, 15 edges |
| `e03-pump-incomplete-review` | `E03 Pump With Nozzles/E03V01-VER.EX01.xml` | public DEXPI 1.3 P&ID example | intentionally limited/incomplete review case for missing downstream context diagnostics | 5 nodes, 4 edges |

The first three documents are the full-page stress set. The remaining documents
are targeted drawing-sheet acceptance documents that cover required product
behaviors not isolated cleanly in the larger sheets. They count for OSS v1
acceptance because they are complete DEXPI 1.3 example sheets for their
respective topology or instrumentation concept.

Do not create a synthetic full-page P&ID for v1 until the session-preparation or
topology-view work proves that the public corpus cannot exercise a required
behavior. If that happens, keep the public document as a regression input and
add the synthetic document as a new acceptance-corpus row with its generation
method and expected topology documented.

## Document-Level Expected Outcomes

| ID | Preparation | Topology expectation | Logic-request expectation | Rule-pack expectation | Evidence and diagnostics expectation |
| --- | --- | --- | --- | --- | --- |
| `c01-reference-pid` | succeeds through graph facts and derived graph semantics | broad topology model with stable IDs for mixed equipment, valves, instrumentation, piping nodes, and reference edges | supports whole-file connectivity request; supports selected-source request once a selectable process object is chosen | can be used as a source example for pump-discharge positive and negative adapted verifier cases; no automatic rule-pack execution after upload | answer evidence must reference topology IDs that resolve to canonical base facts; upload diagnostics are empty on success |
| `c02-process-column-basf` | succeeds through graph facts and derived graph semantics | process-column-centered topology with equipment hierarchy and process-facing relationships | supports whole-file connectivity request and unsupported hydraulic-calculation routing | no required v1 pump-discharge result; rule-pack surface should show no selected execution until user action | evidence checks focus on topology ID resolution and absence of invented unsupported answers |
| `c03-piping-equinor` | succeeds through graph facts and derived graph semantics | piping-centered topology suitable for line traversal and intersection review | supports whole-file connectivity request and selected-source downstream review | no required v1 pump-discharge result; useful later for piping rule-pack expansion | evidence path payloads must be representable even when selected queries return sparse or empty results |
| `e06-pump-heat-exchanger-pns` | succeeds through graph facts and derived graph semantics | compact pump-to-heat-exchanger topology with PNS/nozzle connectivity | supports selected-source downstream review from pump or nozzle scope | natural E06 pump-discharge verifier case is expected to produce the existing hard-violation result; adapted E06 case is expected to produce the existing pass result | evidence should include matched pump/discharge objects or diagnostic context matching deterministic verifier artifacts |
| `i06-flow-control-valve` | succeeds through graph facts and derived graph semantics | instrumentation/control-heavy topology with control valve and CCR indication/alarm/control relationships | supports whole-file connectivity request; selected-source request should preserve visible source scope around instrumentation/control objects | no required v1 rule-pack result; rule-pack controls remain explicit and opt-in | evidence highlighting must handle instrumentation/control objects, not only equipment and piping |
| `p04-pipe-intersection` | succeeds through graph facts and derived graph semantics | branching or merging topology through a pipe intersection | supports selected-source downstream review from an intersection-adjacent object | no required v1 rule-pack result; useful later for branching path checks | evidence path payloads must preserve multiple matched path IDs when branching exists |
| `e03-pump-incomplete-review` | succeeds through graph facts and derived graph semantics | intentionally sparse pump/nozzle topology | unsupported or missing-context requests should stop with missing-capability or diagnostic artifacts | natural E03 verifier case is expected to produce the existing evaluation diagnostic | diagnostics must be structured and exportable; no best-effort answer may be invented |

The current verifier-suite artifact expectations are the baseline for rule-pack
behavior until the web workflow introduces a persisted rule-pack package:

- `hard_violation_e06_natural` remains the natural full-document E06 violation
  baseline.
- `pass_e06_added_check_valve` remains the adapted E06 positive baseline.
- `evaluation_diagnostic_e03_natural` remains the natural E03 diagnostic
  baseline.
- C01-derived adapted cases remain valid rule behavior examples, but they do not
  replace the full C01 document as the web upload acceptance input.

## Required Invalid Inputs

Invalid inputs are not part of the full-page corpus, but they are required for
upload diagnostics:

| ID | Input shape | Expected primary diagnostic |
| --- | --- | --- |
| `invalid-non-xml` | a plain-text or binary file uploaded as a P&ID | rejected as non-XML |
| `invalid-non-dexpi-xml` | well-formed XML without DEXPI 1.3 structure | rejected as unsupported or non-DEXPI XML |
| `invalid-parser-failure` | malformed or parser-hostile XML | rejected with normalized parser failure and expandable raw details |

## Success Matrix

Every implementation bead in the OSS v1 web workflow should trace its tests or
manual validation back to this matrix.

| Capability | Acceptance gate |
| --- | --- |
| Session preparation | Each primary full-page document runs through XML to pyDEXPI full graph to `graph_facts.json` to `graph_facts.dl` to `derived_graph_semantics.dl`. |
| Determinism | Running the same accepted document 3 times produces stable object IDs and byte-identical or schema-equivalent deterministic artifacts. |
| Topology model | The topology-view model uses stable canonical base fact IDs, contains curated process-topology relationships, and avoids exposing the raw graph dump as the default view. |
| Topology ID resolution | 100% of topology-view IDs resolve back to canonical base facts or documented derived semantics. |
| Readiness gating | Logic request controls remain disabled until session preparation succeeds. |
| Upload diagnostics | Invalid input cases return normalized diagnostics; raw parser details are expandable rather than primary. |
| Canned whole-file request | At least one canned whole-file topology QA logic request can be refined, confirmed, executed, and answered on at least 3 accepted documents. |
| Canned selected-scope request | At least one canned selected-source-scope topology QA logic request can be refined, confirmed, executed, and answered on at least 3 accepted documents. |
| Unsupported request | At least one canned unsupported request stops with a structured missing-capability artifact instead of generated Datalog or an invented answer. |
| Rule-pack query | At least one selected rule-pack query runs on at least 3 accepted or adapted-from-accepted documents, only when explicitly selected. |
| Evidence | 100% of successful answers and rule-pack results include deterministic evidence artifacts. |
| Evidence highlighting | Every highlighted topology ID exists in the topology-view model and exactly matches deterministic evidence source scope, matched objects, or paths. |
| Provider credentials | A fake sentinel credential appears 0 times in API responses, Chainlit messages, app-controlled logs, job results, audit artifacts, and exports. |
| Export | Explicit exports include enough deterministic artifacts to reproduce answer provenance and include 0 occurrences of the sentinel credential. |
| Timing | Upload-to-ready timing is measured and recorded for every accepted document; thresholds should be set after the first baseline run. |

## Canned Requests

Use these requests as stable acceptance inputs. Exact generated Datalog is not
specified here; it belongs to downstream workflow and logic-request artifacts.

| ID | Request | Scope | Expected route |
| --- | --- | --- | --- |
| `whole-file-connectivity-summary` | "What process equipment appears connected by the process topology in this P&ID?" | whole file | topology QA logic request |
| `selected-source-downstream-review` | "Starting from this selected object, what downstream process objects are reachable?" | visible selected source scope | topology QA logic request |
| `unsupported-hydraulic-calculation` | "Calculate the pressure drop and required pump head for this line." | whole file or selected source | missing capability |

## Expected Artifact Set

For each accepted document, a successful session-preparation run should expose or
eventually export:

- uploaded DEXPI 1.3 source metadata
- `graph_facts.json`
- `graph_facts.dl`
- `derived_graph_semantics.dl`
- readiness metadata
- topology-view model
- job status and stage history
- diagnostics, if any

For each confirmed logic request, a successful run should expose or eventually
export:

- route decision
- visible source scope
- provider/model metadata without credentials
- generated Datalog
- Datalog-grounded restatement
- confirmation record
- deterministic result artifact
- grounded logic-request answer
- evidence payload suitable for topology highlighting

## V1 Decisions

1. Targeted E/P/I/P documents count as OSS v1 acceptance documents when they are
   complete DEXPI 1.3 example sheets for their topology or instrumentation
   concept. The C-series documents remain the full-page stress set.
2. Synthetic full-page P&IDs are deferred until a concrete coverage gap is found
   in the public corpus.
3. Upload-to-ready performance thresholds are intentionally unset until the first
   measured Chainlit/session-preparation baseline. The first implementation must
   record timings; a later bead can turn those baselines into thresholds.
