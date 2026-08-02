# Engineer-Facing Grounded Answer Contract

## Purpose

PortLog answers questions about a prepared P&ID in process-engineering language. It keeps graph storage identifiers and execution details available for inspection, but does not use them as the primary explanation.

This contract governs presentation. It does not make example claims authoritative, add engineering facts, or weaken evidence validation. A final claim is authoritative only to the extent established by the governed tools and deterministic results for the active source.

## Result structure

The default result follows this order:

1. **Conclusion** — State the supported engineering claim directly.
2. **Basis** — State the observations or deterministic result that support the claim.
3. **Boundary** — State the material boundary only when it changes how the claim should be interpreted.
4. **Next implication** — State one bounded next action or clarification only when the result cannot stand alone.

Do not mechanically render a `Limitations` section. A boundary is part of the result only when it is material.

Every source-specific result has two independent dimensions:

- **Conclusion status**: `Established`, `Not established`, `Conflicting`, or `Not evaluated`.
- **Coverage**: `Complete`, `Partial`, or `Insufficient`.

The claim must be stated explicitly so that its status is unambiguous. For example:

> Claim: A downstream tagged item is reachable from T4750
> Conclusion: Not established · Coverage: Partial

Store both dimensions on the result. Show a status or coverage indicator in the collapsed view only when it materially qualifies the conclusion. Do not use `Not established` as shorthand for “does not exist.”

A short, fully supported answer can combine the conclusion and basis. Do not add empty sections or qualifications that do not change interpretation.

## Language

Prefer the most specific term established by the source:

- equipment tag, equipment item, pump, vessel, heat exchanger, valve;
- nozzle, piping connection, line, branch, flow path;
- upstream, downstream, connected to, reachable from;
- satisfies, does not satisfy, violation found, no violation found;
- prepared P&ID, loaded source, or active drawing.

Do not present `node`, `edge`, adjacency, graph traversal, internal predicate names, or generated object identifiers as engineering conclusions. Those terms can appear in execution details or provenance when a user asks to inspect them.

Do not replace a precise source term with a more specific engineering classification that the source did not establish. For example, say “equipment item” rather than “vessel” when the equipment type is unknown.

## Evidence, drawing focus, and provenance

Evidence is claim-linked rather than one undifferentiated list. Each conclusion or material qualification names the human-readable observations that support it.

Use labels that an engineer can relate to the drawing, such as:

- `Equipment T4750`
- `Nozzle N1 on T4750`
- `Piping connection from T4750/N1`
- `Validated rule: pump discharge isolation`

When no source label exists, use a neutral positional label such as `Unlabeled piping connection from T4750/N1`. Do not invent a tag.

Each evidence item may offer two distinct actions:

- **Show on drawing** — focus and highlight the cited objects without changing the question scope.
- **Use as scope** — explicitly make the cited object or path the scope of a subsequent question.

When possible, evidence highlights the corresponding objects and paths on the P&ID SVG. The drawing itself remains legible; only the evidence-overlay layer changes emphasis:

- current-answer evidence uses saturated highlights, solid strokes, and a subtle equipment fill or path halo;
- evidence from the previous answer becomes a neutral, subdued overlay after the next prompt is submitted;
- pinned evidence uses a distinct visual treatment from current-answer evidence.

The lifecycle is:

1. Answer A arrives: evidence A is current and fully emphasized.
2. The user drafts a follow-up: evidence A remains unchanged.
3. The user submits prompt B: evidence A becomes visibly stale while B is running.
4. Answer B arrives: evidence A is removed and replaced by B, or cleared when B has no SVG evidence. Pinned evidence persists until explicitly cleared.

The interface may provide **Pin evidence** and **Clear highlights** controls. Evidence that remains visible after a new answer must never look like support for that new answer.

Stable node, edge, witness, rule-run, or trace identifiers belong in expandable **Provenance** attached to the relevant evidence item. Raw identifiers do not appear in the answer body by default. Provenance supports audit and highlighting; it is not a substitute for an engineering explanation.

## Progressive disclosure

The result record has these result-dependent layers, in order:

1. **Result** — conclusion, material status or coverage, and compact evidence count.
2. **Evidence** — claim-linked human-readable observations, drawing locations, and trace paths.
3. **Evaluation** — the reproducible path from interpreted scope through selected capability, validation, execution, witnesses, and conclusion.
4. **Provenance** — source locations and stable identifiers attached to evidence.
5. **Technical details** — generated Datalog, relevant facts, returned rows, rule or query metadata, engine versions, and timing.

The setting may control the initial expansion:

- **Concise**: Result only, with material status or coverage and an evidence count.
- **Standard**: Result plus Evidence expanded.
- **Detailed**: Result, Evidence, Evaluation, and Provenance expanded; Technical details remain available.

A setting never hides evidence or a qualification that changes the meaning of the conclusion. Technical transparency is broadly available to users authorized for the project, but complete runtime logs, infrastructure details, unrelated source data, and other sensitive operational information remain permission-controlled. Secrets, credentials, tokens, environment variables, and private provider reasoning are never disclosed.

Technical details show relevant-result-first data rather than dumping the entire fact database. An advanced preference may expand the generated program, intermediate relations, matched and rejected candidates, query plan, compiler diagnostics, and detailed timings.

## Grounding and uncertainty

- Every source-specific conclusion must be supported by accepted evidence references or a deterministic run result.
- State the claim before its conclusion status. `Not established` means that the stated claim was not proven by the executed evidence; it does not mean the subject does not exist.
- Distinguish `Not evaluated` from `Not established`: the former means the relevant check did not run, while the latter means it ran without establishing the stated claim.
- Distinguish `Complete`, `Partial`, and `Insufficient` coverage. Do not imply that absence from returned evidence proves absence from the drawing.
- Distinguish “not found” from “found, but the requested relationship was not established.”
- Distinguish “no violation found” from proof that a design is universally safe or compliant.
- Preserve useful partial findings before stating a material boundary.
- Do not use model reasoning, prior answer prose, or a golden example as engineering evidence.
- Do not expose or request private model chain-of-thought. Inspectable evaluation records, tool calls, generated Datalog, validation outcomes, and deterministic traces are not chain-of-thought.

## Clarification and corrective action

An incomplete result is not always a clarification question. Preserve partial findings, state what prevents a definitive result, and request only the minimum information needed to proceed.

- **Bounded ambiguity** — when a small, defensible candidate set exists, show contextual choice chips such as `P-101 · Area 200` and `P-102 · Area 400`.
- **Missing user scope** — ask one high-value question, such as which process train or drawing area to evaluate.
- **Insufficient source or model data** — return a qualified result and a corrective next action, such as opening another drawing or resolving an off-page connector. Do not ask the engineer to choose between unsupported interpretations.
- **Conflicting evidence** — show the competing claims and their sources. Offer resolution choices only when selecting between them is legitimately the engineer’s responsibility; otherwise request source correction.

Avoid generic endings such as “Evidence is insufficient.” Do not claim to have searched the entire drawing unless the executed capability establishes that scope.

## Golden examples

These examples define desired presentation behavior. Their equipment tags and
findings are illustrative and are not source facts.

### Direct topology lookup

**Question**

What is connected to nozzle N1 on T4750?

**Result**

Nozzle N1 on T4750 is connected to an unlabeled piping connection.

**Conclusion:** Established · **Coverage:** Complete

**Basis**

- **Claim:** Nozzle N1 belongs to T4750.
  - Evidence: `Nozzle N1 on T4750` — **Show on drawing**
- **Claim:** N1 connects to a piping connection.
  - Evidence: `Piping connection from T4750/N1` — **Show on drawing**

The raw source identifiers are available under **Provenance** for each
evidence item.

### Multi-hop downstream question with a partial result

**Question**

What equipment is downstream of T4750?

**Result**

No downstream tagged item was established for T4750.

**Conclusion:** Not established · **Coverage:** Partial

**Basis**

- **Claim:** T4750 has five represented nozzle connections.
  - Evidence: `Equipment T4750`; `Nozzles N1, N3, N6, N7, and N8 on T4750`
- **Claim:** The available trace reaches immediate piping connections.
  - Evidence: `Five immediate piping connections`

**Boundary**

The available trace stops at those connection points. It does not establish
another tagged equipment item downstream. This result must not be phrased as
proof that no downstream equipment exists.

**Next implication**

A specific nozzle trace or the next drawing in the path is needed to continue.

### Successful deterministic verification

**Question**

Does every centrifugal pump have an isolation valve on its discharge path?

**Result**

No evaluated centrifugal pump lacks the required discharge isolation valve.

**Conclusion:** Established · **Coverage:** Complete

**Basis**

- **Claim:** The encoded discharge-isolation rule was evaluated for every
  represented centrifugal pump in scope.
  - Evidence: `Validated rule: pump discharge isolation`
- **Claim:** The deterministic result contains no violation.
  - Evidence: `Deterministic result: no violation found`

**Boundary**

This conclusion applies to the represented topology and the rule’s encoded
acceptance criteria. It is not a general certification of design safety or
regulatory compliance.

### Ambiguous identifier

**Question**

What is downstream of P-10?

**Result**

The requested equipment is ambiguous, so a downstream trace was not
evaluated.

**Conclusion:** Not evaluated · **Coverage:** Insufficient

**Basis**

- **Claim:** More than one equipment tag matches the requested identifier.
  - Evidence: `Candidate equipment P-101 · Area 200` —
    **Show on drawing**
  - Evidence: `Candidate equipment P-102 · Area 400` —
    **Show on drawing**

**Next implication**

Which equipment did you mean?

`[P-101 · Area 200]` `[P-102 · Area 400]`

The chips are appropriate because the candidate set is small and defensible.

### No matching identifier

**Question**

What is connected to T475O?

**Result**

No equipment tagged T475O was found in the prepared P&ID. A close match,
T4750, was found.

**Conclusion:** Not established · **Coverage:** Complete

**Basis**

- **Claim:** The exact tag T475O is present in the searched equipment index.
  - Evidence: `No exact tag match: T475O`
- **Claim:** Equipment T4750 is a close tag match.
  - Evidence: `Close tag match: T4750` — **Show on drawing**

**Next implication**

Did you mean T4750?

Do not inspect T4750’s connections until the engineer confirms that the close
match is intended.

## Acceptance criteria

A conforming result:

- leads with the supported engineering conclusion rather than a raw path;
- states the claim before its `Conclusion` status;
- stores separate `Conclusion` and `Coverage` dimensions;
- shows status or coverage in the collapsed result only when it materially
  qualifies interpretation;
- uses `Established`, `Not established`, `Conflicting`, and `Not evaluated`
  only with their stated claim;
- uses `Complete`, `Partial`, and `Insufficient` to describe the evaluated
  scope, not the confidence of the prose;
- preserves useful partial findings and states a material boundary without a
  mechanically repeated `Limitations` section;
- supplies human-readable, claim-linked evidence with drawing navigation;
- keeps raw graph identifiers out of the answer body by default;
- provides separate **Show on drawing** and **Use as scope** actions;
- follows the current-evidence, stale-overlay, replacement-or-clear SVG
  lifecycle, with pinned evidence visually distinct;
- distinguishes bounded ambiguity, missing user scope, insufficient source
  data, and conflicting evidence;
- uses choice chips only for a small, defensible candidate set;
- exposes the reproducible **Evaluation** record without requesting or
  displaying private chain-of-thought;
- progressively discloses **Result**, **Evidence**, **Evaluation**,
  **Provenance**, and **Technical details**;
- never treats these examples, model prose, or hidden reasoning as evidence;
  and
- never implies that an unestablished claim proves that its subject does not
  exist.

This contract does not prescribe the final visual styling, persistence policy
for expanded execution artifacts, or final user-facing label between
`Provenance` and `Sources`. Those are separate design decisions and must not
change the result, evidence, or grounding semantics defined here.
