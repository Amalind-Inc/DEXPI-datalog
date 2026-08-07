# PortLog interaction taste (workbench)

Process engineers use the **desktop P&ID workbench**, not a product TUI and not
a web UI product face. Capture behaviors here — not file paths or component
ports. Terminal aesthetics are **non-goals**.

Product sentence: create, edit, and optimize P&IDs; neurosymbolic engine is
co-pilot and verifier. QA/review is a mode, not the destination.
See `CONTEXT.md` § Product.

## Shell grammar (steal carefully / fork Synara)

**Approved shell:** fork Synara (MIT) — see `docs/research/synara-fork-for-portlog-workbench.md`.
Keep projects/threads, files, agent transcript, panes, terminal. Replace the craft
surface with P&ID + PortLog authority/apply. Do not rebuild that chrome in
`frontend/desktop/`.

Synara / Codex / Cursor energy: projects and threads sidebar, document tree,
agent transcript, resizable panes, accessible VM/process lane.
**Steal shell grammar via the fork. Own domain chrome** (drawing, evidence,
propose/apply, rule outcomes). If you remove the P&ID and authority UI and it
still looks like a generic coding command center, the workbench is wrong.

## Wanted (engineer-facing)

1. **Workbench, not chat-only** — multi-doc project, readable uploads, drawing
   as a first-class pane, agent that can propose grounded edits.
2. **Authority is visible** — ordinary tool/context output is never styled like
   PortLog evidence or deterministic rule outcomes.
3. **Evidence is expandable** — short labels such as `[E1]` / `[D2]` open to
   stable source/revision references without fuzzy rebinding.
4. **Deterministic vs prose** — Soufflé / rule results are unmistakably distinct
   from model interpretation; incomplete coverage reads as indeterminate, not
   pass.
5. **Propose → validate → apply** — edits are explicit; no silent DEXPI
   mutation; engineer accepts; host owns apply and provenance.
6. **VM is accessible** — isolation/guest work is inspectable, not a black box.
7. **Cancel is honest** — cancelled work is not shown as success; uncertain
   side effects stay visible.
8. **Reopen is faithful** — workspace reopen restores provenance-bound history;
   moves/copies do not silently inherit old authority.

## Rejected

- Shipping a review chatbot as if it were the product.
- Competing with coding-agent terminal polish (Oh My Pi InteractiveMode).
- Vendoring TUI engines into this repo to chase feel.
- Auto-attaching authority to uncited claims.
- Auto-applying model suggestions to the plant design.

## Taste mining note

Branch `quarantine/portlog-tui-oh-my-pi-wip` may be read for additional
**behavior** bullets only. Do not port code from it without a new accepted ADR.
