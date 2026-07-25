# Local and Hosted Deployment Profiles

DEXPI-datalog ships two deployment profiles from one codebase. The `local`
profile keeps every artifact on the operator's own machine with no accounts
and no network services; the `hosted` profile persists per-user projects,
chats, and review sessions behind sign-in. The profile is selected once at
the composition root (`pydexpi_datalog/web/asgi.py`) and is invisible below
it: no workflow, verification, or QA module may branch on deployment mode.

Three seams carry the difference. **Principal** resolves a `user_id` and a
`workspace` scoping key — a constant `"local"` in the local profile, the
authenticated subject in hosted — so business logic always has an owner and
never asks which profile it is running under. **ArtifactStore** narrows the
`artifact_root: Path` already threaded through `ChainlitReviewFlow`,
`TurnLifecycleStore`, `AuthoredRulePackStore`, and `render_execution_trace`
into an interface; local writes the filesystem tree under `root/<workspace>/`,
hosted writes an object store under the same prefix and serves reads as
presigned URLs so artifact bytes never proxy through the application.
**Catalog** is new: projects, chats, review sessions, and authored pack
ownership, on SQLite locally and libSQL hosted.

The catalog exists in both profiles because the problem it solves is
findability, not durability. Session identity today is a random UUID in
`window.localStorage` (`frontend/lib/session-id.ts`); clearing browser
storage orphans that session's artifacts on disk with nothing left that can
name them. A local operator loses files exactly the way a hosted user would,
so an index is a product feature rather than hosting infrastructure.

Rejected alternatives: (1) hosted-only, which abandons the standalone
CLI/TUI/GUI story the README commits to and reduces the OSS repository to a
client for a service; (2) local-only, which leaves the orphaned-artifact
problem unsolved and forces reviewers to hold session UUIDs in their heads;
(3) SQLite local with PostgreSQL hosted, which doubles the migration set and
invites the dialect drift that quietly turns one profile into the only tested
one — SQLite and libSQL share a dialect, so both profiles run one schema; and
(4) a client-direct backend-as-a-service with row-level security as the
authorization mechanism, which cannot express author-confirmed rule trust,
since trust scoped to one promoted version and its author is not a row
predicate. All access goes through this repository's own backend; if a hosted
database offers RLS it is enabled with no policies, as a deny-all backstop.

Feature skew is the expected failure mode: hosted grows capability, the local
path rots into a demo, and the standalone product becomes theatre. The
integration suite therefore runs against both profiles in CI from the first
slice, using the existing `PYDEXPI_QA_PROVIDER=scripted` hermeticity switch.

The profile has no default. `PYDEXPI_DEPLOYMENT_PROFILE` must name `local` or
`hosted`, and an unset or unrecognised value stops the server from starting.
Defaulting is dangerous in one specific direction: a hosted deployment that
forgot the setting would fall back to a single shared workspace with no
sign-in, and would look like it was working. The app factory below the entry
point still defaults to `local`, because a script or a test importing it
should not need an environment; only a served deployment must be explicit.
That default is also what lets CI re-run the entire existing suite under the
other profile by setting one variable rather than by every test opting in.

Until the hosted seams are built (verified-token principal, libSQL catalog,
object-store artifacts) the hosted profile names the local implementations,
so the two CI legs are near-identical and the hosted leg guards little today.
The harness is still what lands first: replacing one line in the hosted
bundle is what puts a hosted implementation under the whole suite, and no
hosted slice can land without both legs staying green.

`AuthoredRulePackStore(artifact_root / "authored_rule_packs")` is a single
global directory shared by every session. It already violates the authored
rule pack and author-confirmed rule trust definitions, which scope authored
packs to one user and forbid cross-user trust, and it is wrong under two
local workspaces as much as under two hosted users. Workspace-scoping it
belongs to this decision, not to a follow-up.

pyDEXPI is AGPL-3.0 and this repository imports it for XML-to-graph
extraction, so a hosted instance is expected to offer its corresponding
source to the users of that service. The project is not commercial, so this
costs nothing today; it is recorded because it constrains any future
deployment that is not source-available, and because the planned replacement
of pyDEXPI with an own extraction engine is what would lift it.

Governing related ADRs: 0014 (BYOK keys live in the browser — scoped to the
local profile, where env configuration and browser storage remain the only
credential boundary; the hosted profile adds an encrypted server-side key
store rather than superseding it), 0006 (page-navigated app shell), 0001 (web
review shell). CONTEXT.md's temporary session artifact and session-scoped
logic reuse both become profile-dependent and need rewording so that
"temporary" means unsaved rather than local.
