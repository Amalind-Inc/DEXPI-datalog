# PortLog interaction taste (GUI-first stub)

Process engineers use the **desktop GUI** review harness, not a product TUI and not a web UI product face. Capture behaviors here — not file paths or component ports. Terminal aesthetics are **non-goals**.

## Wanted (engineer-facing)

1. **Authority is visible** — ordinary tool/context output is never styled like PortLog evidence or deterministic rule outcomes.
2. **Evidence is expandable** — short labels such as `[E1]` / `[D2]` open to stable source/revision references without fuzzy rebinding.
3. **Deterministic vs prose** — Soufflé / rule results are unmistakably distinct from model interpretation; incomplete coverage reads as indeterminate, not pass.
4. **Cancel is honest** — cancelled work is not shown as success; uncertain side effects stay visible.
5. **Reopen is faithful** — reopening a review restores the same provenance-bound history; moves/copies of a workspace do not silently inherit old authority.

## Rejected

- Competing with coding-agent terminal polish (Oh My Pi / Claude Code InteractiveMode).
- Vendoring TUI engines into this repo to chase feel.
- Auto-attaching authority to uncited claims.

## Taste mining note

Branch `quarantine/portlog-tui-oh-my-pi-wip` may be read for additional **behavior** bullets only. Do not port code from it without a new accepted ADR.
