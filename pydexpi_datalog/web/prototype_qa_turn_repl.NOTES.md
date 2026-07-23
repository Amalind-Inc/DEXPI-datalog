# prototype_qa_turn_repl.py -- notes

## Question it answered

Does the full template-first hybrid grounded-QA turn flow (template routing,
faithfulness gating, generated fallback, structured trace) feel right end to
end when driven by a real LLM over the terminal?

## Verdict

Mostly yes structurally (routing/gating/trace all fire and compose the way
the beads describe), but two real gaps surfaced from actually driving it by
hand rather than reading the code:

1. **The "hybrid" template path has ~0 room for model inference.**
   `_validate_equipment_without_pump_path` (pydexpi_datalog/qa/trusted_templates.py)
   validates by literal keyword/phrase matching against the raw request text
   (every class name plus magic phrases like "in either direction" must
   appear verbatim) and requires an *exact* full-catalog set match on
   bindings rather than a graph-grounded subset. None of that contract is
   disclosed to the model via the tool description in capability_manifest.py.
   Filed as `pydexpi-datalog-1-3qo.9.11`.

2. **A single faithfulness-gate rejection can sink an answerable question.**
   The gate rejects and explicitly tells the model to revise and retry, but
   nothing forces a retry -- observed live: the model got one rejection (an
   intent-declaration mismatch, not a wrong query), had 14 of 20 rounds left,
   and just answered instead of retrying, landing on
   `faithfulness.no_faithful_program` for a question that was likely
   answerable. Filed as `pydexpi-datalog-1-3qo.9.11` (repair-before-giving-up
   half of the same bead).

3. **Live progress is much thinner than other agent harnesses.** Only
   `(round, max_rounds, tool_name)` is surfaced -- no tool arguments, no
   model reasoning -- because the provider never requests reasoning tokens,
   discards any it gets anyway, and `RoundProgress`/`append_progress` have no
   field for it even if captured. Filed as `pydexpi-datalog-1-3qo.9.12`.

4. **Correct template answers were not provably correct to the user.** Asked
   "show me the logic formula you used", the model had nothing to show: the
   executed Souffle program never left `run_souffle_program`, and the
   answered payload carried no route artifact. Fixed as
   `pydexpi-datalog-1-qcof`: `route_artifact.logic_program` now carries the
   template's executed rules verbatim, the answered payload exposes
   `route_artifact` for template-backed turns, and this REPL grew a `:o`
   (`:logic`) command showing the last template-backed turn's program (a
   real ctrl-o keybinding needs raw-tty handling this line-based prototype
   deliberately avoids).

## Status

Kept (not deleted) -- still useful for re-driving the harness by hand while
`3qo.9.11`/`3qo.9.12` are worked. Delete once those land and this stops being
the fastest way to sanity-check the flow, or fold the E06-session-bootstrap
pattern into a real dev fixture if it turns out to be broadly useful.
