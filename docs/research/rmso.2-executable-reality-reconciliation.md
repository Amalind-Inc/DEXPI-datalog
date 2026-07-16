# rmso.2 — What grounded reasoning actually runs end-to-end today

One-page reconciliation of ADR 0008, `37x.22.34`, `3qo`, and `311` against the working
tree (verified 2026-07-16: code inspection + 51 passing seam tests + `souffle` at
`/opt/homebrew/bin/souffle`). Bead: `pydexpi-datalog-1-rmso.2`.

## Headline: ADR 0008's "nothing runs Soufflé" snapshot is superseded — by implementation

ADR 0008 (and `37x.22.34`'s problem statement) recorded that *at decision time* the only
real `souffle` invocation was a narrow lookup in `source_selection.py`, rule packs were
Python traversal, and `propose_temporary_datalog` was a two-shape regex shim. **That state
no longer holds.** The `37x.22.34` sub-tasks have landed the "one shared engine" the ADR
pinned:

| Path | Executable NOW | Seam |
| --- | --- | --- |
| Shared engine | **Yes** — `run_souffle_program(program_text) -> {relation: rows}`; raises `SouffleExecutionError` (`missing_souffle` / `souffle_execution_failed`), never silent-empty | `pydexpi_datalog/semantics/souffle_runner.py` |
| Bundled rule packs | **Yes** — real Soufflé; `bundled_rule_pack.py` delegates to `verification/souffle_rule_pack.py` (`run_souffle_program` at :88, :228). `python_traversal` is gone from production; it survives only as a contract-equivalence test name | `evaluate_bundled_rule(...)` |
| Ad-hoc `propose_temporary_datalog` | **Yes** — validated program is concatenated with `build_graph_facts_datalog(EDB)` + `load_graph_topology_idb()` + loaded rule-pack IDB (read-only, per ADR 0008's contract) and executed on real Soufflé (`topology_tools.py:509-510`). Regex remains for *validation/decl handling only*, not execution. Errors are explicit, not "no matching objects" | `_temporary_datalog_answer_ids` via `run_grounded_qa_turn` |
| Source resolution | Yes (unchanged, narrow) | `llm/source_selection.py:49-57` |
| Benchmark Arm C | **Composition ready, container path unproven** — task builder mounts pre-rendered `/input/graph_facts.dl` + `/input/graph_topology_semantics.dl` + rule-pack markdown, Dockerfile installs `souffle` (souffle-lang apt), `require_executed_program=True` rejects submissions without the executed program. But CI never builds the image (`souffle_arm.py:59-61`) and `test_souffle_arm.py` is scripted, no Docker; live validation was deferred when the 3q1.14 matrix paused on OpenRouter credits | `benchmark/souffle_arm.py::build_souffle_harbor_task` / `create_souffle_arm` |

Test evidence (all green, 3.9s): `test_souffle_rule_pack.py`, `test_bundled_rule_pack.py`
(the regression net ADR 0008 planned), `test_discharge_line_min_diameter.py`,
`test_temporary_datalog.py`, `test_souffle_arm.py` — 51 passed.

## The real-Soufflé-over-EDB mechanism rmso.1 reuses

Two live candidates, both over the same EDB/IDB layers — with different evidence strength:

1. **In-process `run_souffle_program`** + `build_graph_facts_datalog(artifact)` +
   `load_graph_topology_idb()` — **locally proven today** (the 51 green tests execute real
   Soufflé through this seam). No Docker, same layers; the right tool for rmso.1's
   roundtrip/faithfulness checks and blind mechanical grading, and the safe default for
   the spike's execute step.
2. **Benchmark Arm C harness** (`create_souffle_arm` -> `HarborKiraEpisodeRunner` +
   `build_souffle_harbor_task`) — the full author→execute→observe→revise loop with
   sandboxed `souffle`, per-drawing pre-rendered EDB, episode/budget/transcript
   accounting, and the executed-program audit artifact. **Reusable composition, but the
   Harbor container path is not yet proven executable**: CI runs scripted providers with
   no Docker calls, and the image build awaits the resumed 3q1.14 live matrix. Use it for
   the agentic-loop shape; do not treat it as validated infrastructure until one live
   episode completes.

## Per-source reconciliation

- **ADR 0008**: decision fully realized (one engine, two trust tiers, no read-only gate
  exception, `to_number()` numeric predicate per `test_discharge_line_min_diameter`). Its
  *description of then-current reality* is historical; do not cite it as the present state.
- **`37x.22.34`**: implementation substantially landed (rule packs, ad-hoc execution,
  explicit validation errors, dynamic predicate contract). Remaining open value is in its
  UI/gate-wiring children, not the execution core rmso needs.
- **`3qo`**: its routing/validation/repair/confirmation concepts now have working product
  counterparts; rmso.5/rmso.6 should extract requirements from it, not rebuild.
- **`311`**: deontic compilation remains unbuilt/future — unchanged; rmso.3 characterizes
  whether our rules force that expressivity.

## Consequence for the map

rmso.1's blocking assumption — "a real Soufflé-over-EDB mechanism exists to reuse" — is
**confirmed at the engine seam** (`run_souffle_program`, locally proven) and **available as
composition** for the agentic loop (Arm C, pending one live episode). The spike needs zero
engine-infrastructure work: default to `run_souffle_program` for execution and graded
verification; adopt the Arm C loop shape, validating its container path as a spike step if
the agentic form is used.
