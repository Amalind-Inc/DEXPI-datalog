# Commodity vs core

Apply this filter **before** any UI or harness work. If the work is commodity, bind or thin-wrap; do not reimplement. If it is core, deep modules and tests are appropriate.

## Core (deep, PortLog-owned)

- Evidence and authority envelopes (`ordinary` vs `portlog` vs `deterministic`)
- Rule evaluation outcomes, coverage, and indeterminacy
- DEXPI → canonical facts → Soufflé path
- Gondolin / isolated-command confinement and cancel semantics
- Review reopen provenance and host-owned session policy
- Thin policy wrappers around a mature Pi agent loop (ADR 0017)

## Commodity (bind / thin-wrap — do not rebuild)

- Generic chat transcript and scrollback
- Markdown / rich-text rendering
- Prompt editors and sticky input chrome
- Model pickers and provider login chrome
- Full TUI engines and InteractiveMode clones
- Coding-agent session UX copied from Oh My Pi, Claude Code, or similar

## Synthesis rule (replaces GitHub-memory-slop)

**Allowed**

- Short **behavior** notes in `docs/agents/portlog-interaction-taste.md` (what the engineer should see or do, and why).
- Dependencies on maintained packages or git pins with a thin PortLog adapter.
- Taste mining from `quarantine/portlog-tui-oh-my-pi-wip` as **read-only** behavior extraction.

**Forbidden**

- Copying upstream component trees into `frontend/desktop/vendor/` without an accepted ADR that names the dependency and adapter boundary.
- Agent tasks that “remember” a GitHub repo and dump a degraded remix into this tree.
- Expanding the frozen terminal TUI (see `docs/agents/terminal-ui-freeze.md`).

## Decision question

Ask: *Is this unique to grounded P&ID review with PortLog authority, or is it generic agent UX?*

- Generic → buy/bind/thin-wrap; ship on the desktop GUI or the existing `portlog:review` smoke CLI.
- Unique → overengineer in PortLog-owned modules; cover with behavior tests.
