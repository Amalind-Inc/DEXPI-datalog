# Synara fork for the PortLog P&ID workbench

**Status:** product direction (owner-accepted)  
**Date:** 2026-08-07  
**Related:** `CONTEXT.md` § Product (`pydexpi-datalog-1-n7go`); freeze `pydexpi-datalog-1-7dgd`; harness ADR 0017; epic `pydexpi-datalog-1-34eu`

## Decision

**Fork [Synara](https://github.com/Emanuele-web04/synara) (MIT) as the desktop workbench shell for PortLog.**

Do not rebuild Synara/Codex/Cursor chrome in this repo. Do not vendor Synara by pasting files into `frontend/desktop/vendor/`. Fork the upstream project, edit the seams below, and keep PortLog’s neurosymbolic core (DEXPI, facts, evidence, Soufflé, propose→validate→apply, Gondolin) as PortLog-owned code.

Synara began as a clone of [T3 Code](https://github.com/pingdotgg/t3code) and is now a distinct product. It is mature enough for a controlled fork: local-first desktop command center, projects/threads, terminals, browser/preview panes, files, provider sessions, and packaging. PortLog’s product is a **P&ID workbench** (create / edit / optimize), not a coding-agent clone — Synara supplies shell grammar; PortLog supplies domain chrome and authority.

## What we are forking

**Whole Synara monorepo** as a separate PortLog-branded fork (recommended layout: sibling repo or git submodule under something like `workbench/` — exact path chosen in the first spike). Not a partial file cherry-pick.

Observed upstream shape (subject to change; verify on pin):

| Area | Role for PortLog |
|---|---|
| `apps/desktop` | Electron shell, packaging, native bridge — **keep, rebrand** |
| `apps/web` | Renderer UI (sidebar, chat, panes, composer) — **keep shell; replace center domain surfaces** |
| `apps/server` | Local workspace/server orchestration — **keep; add PortLog host seams** |
| `packages/contracts` | Shared protocol types — **extend carefully; do not silently break** |

Upstream run path today: `bun install` / `bun run dev`. License: **MIT** (retain copyright notices; see LICENSE on pin).

**Pin policy:** record exact upstream commit SHA + date in this doc’s “Pin” section when the fork is created. Prefer periodic intentional merges from upstream over continuous drift; never “agent remembers GitHub and dumps diffs.”

## Pin

- Upstream: `https://github.com/Emanuele-web04/synara`
- Local fork working copy: `/Users/vikramoddiraju/LogicProgramming/portlog-synara` (sibling of PortLog; **not** vendored into this repo)
- GitHub fork home: *blocked this session — `gh` auth token invalid; create `Harborfield-suite/portlog-synara` (or equivalent) and `git remote add origin …` when authenticated*
- Upstream remote on local clone: `upstream` → `Emanuele-web04/synara`
- Upstream commit pinned: `2e25a16a0e97764c4ffcaacd32fcdaac710415da` (2026-08-07, “Fix composer send arrow alignment (#566)”)
- Spike branch on local clone: `portlog/spike-host-bridge` @ `559e997`
- Date pinned: 2026-08-07

## What we keep from Synara (commodity — edit lightly)

- Windowing, layout, resizable / dockable panes  
- Projects + threads / session navigation  
- Chat transcript + composer chrome  
- Files / workspace tree pane (adapt to DEXPI + prepared artifacts)  
- Terminal / process pane (route risky work toward Gondolin later)  
- Desktop packaging and local-first storage posture  
- Provider/session plumbing **only as a host for PortLog’s agent**, not as the product identity  

## What we replace or gut (PortLog-owned)

| Synara / coding default | PortLog workbench |
|---|---|
| Code editor / diff as the main craft surface | **P&ID / topology canvas** (separate canvas fork or embed — see below) |
| Generic coding-agent providers as the product | **Host-owned PortLog Pi harness** (ADR 0017): evidence, rules, apply, policy |
| GitHub PR / worktree-as-product | Optional later; not the ship gate |
| Model prose as authority | **Authority-visible events** (`ordinary` / `portlog` / `deterministic`) |
| Silent file edits | **Propose → validate → explicit apply** |

If someone strips the drawing, evidence, and apply UI and the app still reads as “just Synara for code,” the fork failed.

## What we do **not** put in the Synara fork

- Soufflé / Datalog engines  
- pyDEXPI extraction and canonical fact layer  
- Authority envelope semantics and review provenance store  
- Gondolin isolation policy (call from shell; implement in PortLog core)  
- Reinventing chat markdown, prompt editors, or Electron from scratch  

Those stay in the PortLog repo (or existing sidecar) and are exposed to the shell through a **narrow host API / event protocol**.

## Canvas (related, not this fork)

Synara does not give you a DEXPI P&ID editor. Center-pane options remain separate (spike later):

- [chemical-graph-editor](https://github.com/ssnchenfeng-ai/chemical-graph-editor) (MIT) — semantic P&ID + agent export  
- [PandID](https://github.com/ashpursglove/PandID) — React Flow P&ID draw polish  

**Rule:** pick one canvas baseline in a follow-on spike; embed it in Synara’s main craft pane. Do not rewrite CAD in the shell fork.

## Architecture target

```text
[Synara fork]  desktop shell: projects, files, agent UI, terminal/VM panes
      │
      ├─ craft pane ← [P&ID canvas baseline — separate decision]
      │
      └─ agent/tools ← [PortLog host: Pi + evidence + rules + apply + Gondolin]
                ↑
         pyDEXPI facts / Soufflé (PortLog core)
```

Renderer is a client. PortLog (Electron main / host worker / sidecar) remains authority for documents, evidence, deterministic outcomes, credentials, and apply.

## Agent rules (how not to waste tokens)

1. **Edit the fork** at named seams. Do not reimplement Synara UX in `frontend/desktop/`.  
2. **No GitHub-memory vendor dumps** into PortLog `vendor/` (see `docs/agents/commodity-vs-core.md`).  
3. Every shell PR answers: *does this help create / edit / optimize a P&ID under grounded checks?*  
4. Prefer thin adapters: Synara session/event → PortLog record; PortLog tool result → Synara transcript chrome with authority badges.  
5. Upstream pulls are intentional, reviewed merges — not drive-by sync.  

## First spike (acceptance)

1. Create Harborfield/PortLog fork; pin SHA in this doc.  
2. Run stock Synara desktop locally (`bun` path).  
3. Map seams (written notes in spike closeout):  
   - where the main craft/editor pane mounts  
   - where agent/provider sessions start  
   - where files tree roots  
   - where terminal/process panes attach  
4. Prove one **no-op PortLog host bridge**: one PortLog event type rendered in Synara transcript chrome (e.g. distinguish a fake `portlog` evidence line from ordinary chat).  
5. Stop. Do not redesign the whole app in the spike.

## Spike closeout (2026-08-07, bead `pydexpi-datalog-1-ngrs`)

**Done**

- Shallow-cloned Synara to sibling `portlog-synara`; remotes: `upstream` only (GitHub org fork pending owner `gh auth login`).
- `bun install` succeeded; `bun run dev:web` reached Vite ready on `http://localhost:5733/` (stock shell path proven; full Electron desktop not required for this seam).
- No-op PortLog evidence bridge landed on branch `portlog/spike-host-bridge`:
  - `apps/web/src/portlog/portlogHostBridge.ts` (+ tests)
  - `PortLogEvidenceChip` / `PortLogTranscriptSegments`
  - Wired into assistant `ChatMarkdown` so `[portlog:evidence|E1|…]` lines render with `data-portlog-authority="portlog"`, distinct from ordinary prose
  - Focused vitest: 28 passed (`portlogHostBridge` + `ChatMarkdown`)

**Seam map (pin `2e25a16`)**

| Concern | Where |
|---|---|
| Craft / editor center | `apps/web/src/components/EditorWorkspaceView.tsx` — file/diff center + `WorkspaceFilesSidebar` / `WorkspaceFilePreview`; replace later with P&ID canvas |
| Files tree | Right-dock kind `explorer` / `file` via `apps/web/src/rightDockStore.logic.ts` (`RIGHT_DOCK_PANE_KINDS`); editor explorer in `components/chat/workspaceExplorer` |
| Terminal | Right-dock kind `terminal`; state `apps/web/src/terminalStateStore.ts` |
| Browser / side chat / git | Right-dock kinds `browser`, `sidechat`, `git`, `pullRequest`, `diff` |
| Agent / provider sessions | `apps/server/src/agentGateway/` (+ `harnessPolicy.ts`); providers include **`pi`** in `PROVIDERS_WITH_THREAD_SCOPED_SYNARA_MCP`; Codex path also `codexAppServerManager.ts` |
| Transcript chrome (PortLog spike) | `apps/web/src/components/ChatMarkdown.tsx` ← `portlog/PortLogTranscriptSegments.tsx` |
| Desktop packaging | `apps/desktop` (Electron); monorepo scripts `dev:desktop` / `electron:dev` |

**Resolved from open questions**

- Layout: **sibling repo** (`portlog-synara`), not submodule/vendor dump into PortLog.
- Electron host strategy: deferred — Synara desktop remains candidate shell; PortLog core stays sidecar/host API.

**Still open**

- Push GitHub fork under Harborfield when `gh` works  
- Branding rename `@synara/*` → PortLog  
- Canvas baseline (chemical-graph-editor vs PandID)  
- Wire real PortLog host events (not marker strings) into the bridge  

## Non-goals for the spike

- Full DEXPI edit/apply  
- Multi-provider coding-agent parity  
- Merging Synara into the existing Electron app without a pin  
- Web-as-product-face  

## Open questions (post-spike)

- Whether PortLog’s existing Electron main is replaced by Synara desktop or embeds PortLog as a sidecar host  
- Branding/package rename cadence (`@synara/*` → PortLog identifiers)  
- Canvas baseline choice  
- GitHub remote for `portlog-synara` after `gh auth login`

## References

- Upstream: https://github.com/Emanuele-web04/synara  
- Docs: https://www.trysynara.com/docs  
- T3 Code (ancestry): https://github.com/pingdotgg/t3code  
- PortLog product: `CONTEXT.md` § Product  
- Taste: `docs/agents/portlog-interaction-taste.md`  
- Commodity filter: `docs/agents/commodity-vs-core.md`
