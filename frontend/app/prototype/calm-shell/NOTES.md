# Calm shell prototype — verdict (bead 2ki.3)

## Question

What should the new "calm review shell" look like? Three structurally
different directions were built at `/prototype/calm-shell` (UI-variations
branch of `skill://prototype`):

- **A — Rail + timeline**: persistent labeled sidebar; stepped review as an
  always-visible vertical timeline (all steps shown, connected by a line).
- **B — Hero-first, minimal chrome**: icon-only rail, Sessions as a flyout;
  empty state fills the viewport like a landing page; review as full-width
  stacked cards.
- **C — Split workspace**: sidebar is a single tabbed panel; review is a
  paged stepper (one step visible at a time behind a dot rail).

## Verdict

**B**, approved 2026-07-03, with one addition made during review: a
split-pane P&ID panel on the right in review mode (inspired by a doc-QA
reference UI where a citation panel highlights the quoted passage — same
idea, P&ID instead of a document). Clicking a step card highlights the
symbols/lines its evidence references, using the real
`SchematicSceneView` component against fake scene data
(`fake-pid-scene.ts`), not a static mockup.

Only variant B survives in the prototype route; A and C and the comparison
switcher were deleted after the decision. The route (`page.tsx`,
`variant-b.tsx`, `fake-data.ts`, `fake-pid-scene.ts`) stays as a live
reference for the real implementation slice (2ki.10), not folded into
production yet — rewrite under production constraints (tests, real data,
error handling) when building that slice.

## Design tokens to carry into 2ki.10

**Palette** (white ground, one accent):

| Token | Value | Use |
|---|---|---|
| `--calm-paper` | `#fbfaf8` | page background |
| `--calm-ink` | `#1c1815` | primary text |
| `--calm-ink-muted` | `#6b6259` | secondary text |
| `--calm-accent` | `#b9542e` | CTAs, active/selected state, consent-card accent |
| `--calm-accent-soft` | `#f4e3d8` | accent-tinted fills (active nav item, selected chip) |
| `--calm-line` | `#e8e3dc` | borders/dividers |

**Type**: `Fraunces` (next/font/google, variable) for display moments
(hero headline, turn/panel titles) via `font-[family-name:var(--calm-display-font)]`;
system sans (existing Tailwind default) for body text and UI chrome.

**Radius**: `rounded-2xl` (1rem) for cards and panels, `rounded-lg`
(0.5rem) for buttons, `rounded-full` for pills and icon buttons.

**Elevation** (soft, layered shadows — no hard drop shadows):
- Resting card: `shadow-[0_1px_2px_rgba(28,24,21,0.04)]`
- Raised panel/hero input: add
  `0_16px_36px_-20px_rgba(28,24,21,0.2)` (panel) or
  `0_20px_40px_-20px_rgba(28,24,21,0.25)` (hero input)
- Accent/consent emphasis: swap the raised-panel shadow's color for the
  accent, e.g. `0_16px_36px_-16px_rgba(185,84,46,0.35)`

**Interaction states** reused from the existing schematic renderer CSS
(`app/globals.css` — `.schematic-scene-svg .selected` / `.highlighted`):
selected = blue drop-shadow, highlighted = amber drop-shadow. The calm
shell's own "active" state (step card) uses the accent color instead
(`ring-1 ring-[var(--calm-accent)]`), kept distinct from the schematic's
existing selection colors so the two don't compete visually inside the
same panel.

**Layout shape carried forward**: icon-only left rail (Assistant / Rule
Packs / Sessions, Sessions as a flyout, not a permanent column); hero
empty state is full-viewport; once a session is active, main content
splits into a scrollable step feed (left) and a persistent P&ID panel
(right, fixed ~440px) with a small header bar (filename + download
affordance) — this panel shape is the one to formalize in 2ki.10, backed
by real `schematicScene` data instead of `fake-pid-scene.ts`.
