# Issue tracker: Beads (`br`)

Issues, PRDs, and wayfinder maps for this repo live in **Beads** (`br`, beads_rust) — a
local SQLite + JSONL tracker committed under `.beads/`. Despite the GitHub remote
(`Amalind-Inc/DEXPI-datalog`), there is **no GitHub-Issues workflow**; all work is tracked
in beads. Use the `br` CLI for every operation. **Use `br`, not `bd`.** Issue ids are
prefixed `pydexpi-datalog-1-`.

**External PRs are not a triage surface** — beads is internal, so `/triage` has no PR queue
here.

## Conventions

- **Create**: `br create "<title>" -t <type> -p <P0-P4> -d "<body>"`; `--parent <id>` for a
  child, `--labels a,b` for labels. `br q "<title>"` quick-captures and prints only the id.
- **Read**: `br show <id>` (description + dependencies + comments); `br comments list <id>`.
- **List / find**: `br list --status open`, `br ready` (unblocked), `br blocked`,
  `br search <text>`.
- **Update**: `br update <id> --description ... | --status ... | --priority ... | -a <who>`.
- **Comment**: `br comments add <id> "<text>"` — text is **positional**, not `-m`.
- **Close / reopen**: `br close <id>` / `br reopen <id>`.
- **Dependencies**: `br dep add <issue> <depends-on>` (issue depends on depends-on; the
  depends-on **blocks** issue). Inspect with `br dep tree <id>` / `br dep list <id>`.
- **Labels**: `br label add <id> <label>`.
- **Sync**: `br sync --flush-only` exports the DB to `.beads/issues.jsonl`; **commit that
  file**. `br` never runs git itself.

## When a skill says "publish to the issue tracker"

Create a bead with `br create` (as a child of the relevant epic/parent where applicable).

## When a skill says "fetch the relevant ticket"

`br show <id>` — the user normally passes the id directly.

## Session protocol

After creating/updating beads: `br sync --flush-only`, then `git add .beads/issues.jsonl`
and commit with a message referencing the bead id. See the "Beads Workflow Integration"
section of `AGENTS.md`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single bead; its tickets are **child beads**.

- **Map**: one bead labelled `wayfinder:map` holding the Destination / Notes /
  Decisions-so-far / Not-yet-specified / Out-of-scope body:
  `br create "<title>" -t feature --labels wayfinder:map -d "<body>"`.
- **Child ticket**: `br create ... --parent <map-id> --labels wayfinder:<type>`, where
  `<type>` is `research` | `prototype` | `grilling` | `task`. Parent-child is grouping only
  (non-blocking), so children stay on the frontier while the map is open.
- **Blocking**: native dependencies — `br dep add <ticket> <blocker>`. A ticket is
  unblocked when every blocker is closed.
- **Frontier**: `br ready` lists open, unblocked beads (take the map's children among them);
  `br blocked` shows what is waiting and on what.
- **Claim**: `br update <id> -a <dev>` before any work — an open, unassigned child is
  unclaimed.
- **Resolve**: `br comments add <id> "<answer>"`, then `br close <id>`, then append a
  one-line context pointer to the map's Decisions-so-far (edit the map body), then
  `br sync --flush-only` + commit.
