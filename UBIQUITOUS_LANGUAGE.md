# Ubiquitous Language

## Source and model

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **DEXPI source file** | A single XML export that acts as the engineering source input for one run. | Input file, XML file, diagram file |
| **pyDEXPI full graph** | The NetworkX graph returned by `pyDEXPI` from one DEXPI source file. | Parsed graph, upstream model |
| **Canonical base fact layer** | The project-owned graph-mirrored fact artifact, `graph_facts.json`, exported from the pyDEXPI full graph. | Internal graph, normalized graph |
| **Legacy XML normalization** | The XML-direct compatibility seam used by older dry-run and review paths. It is not the primary project model. | Primary model, graph facts |
| **Affected connected subgraph** | The minimal connected portion of the engineering model needed to evaluate one rule result and explain it. | Neighborhood, local graph, scope slice |

## Execution and policy

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Manifest** | The immutable run configuration that declares how one DEXPI source file should be processed. | Config, input file, request |
| **Dry-run** | A preflight execution mode that validates the manifest, source file, and structural derivations without findings or patch proposals. | Preflight, validation-only run |
| **Review-only** | A run mode that emits raw findings with evidence but no patch proposals. | Read-only mode, inspect-only |
| **Rule pack** | A versioned collection of rule definitions and configuration used to evaluate a run. | Ruleset, policy file, pack |
| **Operational scope** | The plant, unit, and equipment applicability boundary attached to a rule pack or rule. | Scope, engineering scope |
| **Provenance metadata** | Optional policy-source metadata such as jurisdiction, standard, and version. | Standard info, policy context |

## Findings and corrections

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Finding** | A single rule-evaluation result tied to one affected connected subgraph. | Issue, hit, anomaly result |
| **Finding severity** | The project-facing classification of a finding as hard violation, soft advisory, or informational. | Alert level, priority |
| **Evidence trail** | The structured justification that records the rule, facts, identities, and context behind a finding or patch proposal. | Explanation, audit note |
| **Patch proposal** | A single atomic, reviewable edit generated for one finding. | Fix, autocorrection, patch |
| **Validation state** | The persisted status of an affected connected subgraph after evaluation and suppression decisions. | Result state, review state |
| **Waiver** | An explicit, structured exception that suppresses a finding after rule resolution without deleting its history. | Exception, override, suppression rule |

## Diagnostics and artifacts

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Adapter diagnostics** | Warnings and errors attached during conversion from source artifacts into project-owned facts or compatibility normalization outputs. | Parse logs, conversion notes |
| **Diagnostic code** | The stable machine-readable identifier attached to a diagnostic. | Error key, warning ID |
| **Artifact** | A persisted output record produced by a run, such as a dry-run summary, finding set, or patch set. | Output file, result file |
| **Artifact store** | The engine-owned persistent location for immutable run artifacts. | Output folder, results directory |

## Relationships

- A **Manifest** drives exactly one run over one **DEXPI source file**.
- A **DEXPI source file** is loaded as the **pyDEXPI full graph**, then exported to the **Canonical base fact layer**.
- A compatibility **Rule pack** may still evaluate against **Legacy XML normalization** until it is migrated to graph-mirrored facts.
- A **Finding** belongs to exactly one **Affected connected subgraph**.
- A **Finding** may produce at most one **Patch proposal** in the initial workflow.
- A **Waiver** suppresses a **Finding** only after rule resolution and does not erase the original **Finding**.
- A **Validation state** belongs to an **Affected connected subgraph**, not to the entire source file.
- An **Artifact** records the results of a run and preserves its **Evidence trail** and **Diagnostic code** values.

## Example dialogue

> **Dev:** "For this **Manifest**, do I point to multiple XML files or one **DEXPI source file**?"
>
> **Domain expert:** "One **DEXPI source file** per **Manifest**. Batch processing is out of scope for now."
>
> **Dev:** "When the **Rule pack** fires, is the **Finding** attached to the whole plant?"
>
> **Domain expert:** "No. Each **Finding** belongs to one **Affected connected subgraph** so the **Evidence trail** stays focused."
>
> **Dev:** "If an engineer approves an exception, does the **Waiver** replace the **Finding**?"
>
> **Domain expert:** "No. The **Waiver** suppresses the visible result, but the original **Finding** remains in the **Artifact** history."

## Flagged ambiguities

- "graph" was repeatedly used to mean both the pyDEXPI output and the project-owned fact model. Use **pyDEXPI full graph** for extraction output and **Canonical base fact layer** for `graph_facts.json`.
- "input file" was used to mean both the **Manifest** and the **DEXPI source file**. These are distinct: the **Manifest** declares the run, while the **DEXPI source file** is the engineering source input.
- "preflight" and "dry-run" were both used for the same concept. Use **Dry-run** as the canonical term.
- "exception", "override", and "waiver" were used interchangeably. Use **Waiver** for the structured suppression record.
- "patch", "fix", and "autocorrection" were used loosely. Use **Patch proposal** for the reviewable output, and avoid implying automatic application.
