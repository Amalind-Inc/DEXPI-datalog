# Terminal UI freeze

Interactive PortLog TUI work is **frozen**. Process engineers will use the **desktop GUI** (macOS PortLog desktop harness). The terminal is a **dev/smoke harness**, not a product face. Do not treat web UI epics as the product face.

## Supported terminal entry

- **Only:** `npm run portlog:review` (`frontend/desktop/portlog-review.ts`)
- Use it to exercise harness, evidence, rule checks, isolation, and cancellation quickly.
- Do **not** expand InteractiveMode, Oh My Pi engine facades, or commodity chat chrome in the terminal.

## Quarantine branch (taste mining only)

- Branch: `quarantine/portlog-tui-oh-my-pi-wip`
- Contains the frozen InteractiveMode / `oh-my-pi-tui` vendor chase for **read-only** behavior mining.
- **Not** a merge candidate. Do not treat quarantine code as something to port back without a new accepted ADR that names a package/git dependency and a thin adapter.

## Forbidden until this freeze is lifted in Beads

- Expanding `frontend/desktop/vendor/oh-my-pi-tui`
- New `portlog-tui*` features or Bun/Node TUI engine shims
- Agent tasks whose acceptance criteria are “feel like Oh My Pi / Claude Code in the terminal”
- “Read a GitHub TUI repo and vendor/copy it into this tree”
- Commodity chat chrome (transcript scrollback, markdown renderer, prompt editor, model picker polish) as terminal product work

## Where to spend effort instead

- Core: evidence/authority envelopes, Soufflé outcomes, Gondolin isolation, provenance, host-owned Pi harness (see `docs/adr/0017-full-pi-portlog-agent-harness.md` and `docs/agents/commodity-vs-core.md`)
- Product face: macOS desktop review harness (`pydexpi-datalog-1-34eu` and related desktop work) — not web UI epics
- Taste: short GUI behavior notes in `docs/agents/portlog-interaction-taste.md` — never component-tree dumps

Lift this freeze only by closing or explicitly updating the Beads freeze decision and accepting a new ADR.
