# rmso.11 — Arm T: prebuilt Datalog template arm (design-lock revision v3)

Date: 2026-07-20
Bead: `pydexpi-datalog-1-3av5` (design) → `lx6p` (implementation) → `3g4i` (matrix rerun)
Status: APPROVED (product owner, 2026-07-20) — decisions resolved below.

## Motivation

Three scored runs say the constraint is not "can a cheap model author
Datalog" (one genuine authoring failure in 27 Arm C episodes; everything else
was runtime/lifecycle, now fixed in rmso.9/.10, 1dgs, 2r3d). The constraint is
economic and organizational:

- Per-question free-form authoring makes every answer a fresh proof
  obligation, reviewed by nobody in production.
- SMEs will not read logic programs. The reviewable surface must be a
  natural-language rule description plus a parameter binding — never Datalog.
- The compliance questions SMEs actually ask cluster into a small number of
  query shapes. Authoring is the exception path, not the main path.

Arm T tests the amortization hypothesis directly: **one-time internal review
of a template pack + per-answer parameter validation beats per-answer program
authoring on cost and reliability, at equal correctness.**

## Episode contract

1. Model reads the question and `graph_inspection.json` (same inputs as Arm C).
2. Model emits one routing JSON (its only authored surface):

   ```json
   {"category": "<template id>",
    "parameters": {"<slot>": ["<label>", ...], ...}}
   ```

3. Runner validates: category must exist; every label parameter must be drawn
   from the drawing's closed vocabulary in `graph_inspection.json`; enum slots
   (edge kind, direction) must match the template's declared domain.
   - Invalid → corrective feedback listing the violating values and the
     nearest valid vocabulary; bounded retries (2).
4. Runner renders the template (pure textual substitution into a frozen,
   reviewed `.dl` body), executes it through the **existing** `run_query.py`
   checkpoint lifecycle — receipt framing, starter guard, mechanical
   completion, faithfulness replay of the rendered program, counterfactual
   probes all unchanged.
5. Permission/defeasible questions: the router's only correct output is
   `{"category": "policy_abstention"}` → existing mechanical abstention
   helper. A verdict-shaped answer on these is graded as a violation.

## Template pack v1

Frozen, internally reviewed, shipped with an SME-facing one-line description
each. Slots are typed: `label_set` (validated vocabulary), `edge_kind` (enum),
`direction` (enum).

| id | question shape | core rule shape |
|---|---|---|
| `entity_lookup` | does X exist / find all X | `witness(N) :- node_label(N, L), member-of label_set.` |
| `attachment` | who owns / what is attached | `reference_edge` lookup over role enum (`sourceItem`, `targetItem`, …) |
| `reachability` | is A connected to B | transitive closure over `graph_edge` between two label sets |
| `guarded_reachability` | can A reach B / is B monitored by A | closure + negation: members of target set NOT reached from source set |
| `class_count` | how many X / threshold | aggregation over a label set with comparator slot |
| `policy_abstention` | permission / defeasible control | no program — mechanical abstention |

The valve-monitoring family (our only genuine authoring failure) becomes
`guarded_reachability` with `source_set = ["ProcessInstrumentationFunction"]`
and a `target_set` the model must bind — and the binding is now *validated*:
labels that do not exist in the drawing are rejected before execution. The
run-04 over-approximation failure mode becomes mechanically checkable.

## Fallback ladder

`template → free-form authoring (C-classic path) → abstention`, with fallback
events recorded per episode. **Fallback rate is a first-class metric**: if the
router routinely fails to fit questions into the pack, the amortization thesis
collapses and Arm A deserves the slice. No silent fallback: the routing JSON
and the fallback reason are preserved in the trajectory.

## Metrics (per cell, unchanged grader)

- correct grounded credit (existing gates, exact witnesses)
- cost per credit; wall time
- **fallback rate** and reason taxonomy
- parameter-repair rate (retries consumed on validation feedback)

## Matrix (one variable per cell)

| cell | model | arm | question answered |
|---|---|---|---|
| 1 | flash | C-classic + all fixes | was 4-5/9 mechanics? (predicted yes) |
| 2 | flash | Arm T | routing vs authoring at equal model |
| 3 (optional) | v4 pro | C-classic | is residual authoring variance model capability? |

Cells run sequentially; cell 3 only if cell 1 leaves genuine authoring
failures on the table. Product-level claims still require the fresh
SME-certified holdout slice regardless of outcome (third pass over the same
nine questions is diagnostic only).

## Resolved decisions (product owner, 2026-07-20)

1. **Template pack v1**: the six templates as specified.
2. **Fallback policy**: free-form authoring IS the production fallback, so
   the eval measures the production ladder (template → authoring →
   abstention). Fallback episodes are tagged and reported separately: the
   headline includes them; the router-coverage table excludes them so pack
   coverage stays readable.
3. **Cell 3 (v4 pro)**: decided after cell 1 results.
4. **Parameter-validation retry budget**: 2.

Status: APPROVED — lock v3 cut as `testdata/benchmark/rmso_eval_lock_v3.json`
(same nine entries, budgets, and accounting contract as v2; design revision
`template-routed-vs-authored-v3`; Arm T added alongside A and C-classic).
