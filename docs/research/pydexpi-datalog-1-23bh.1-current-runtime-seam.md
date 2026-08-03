# pydexpi-datalog-1-23bh.1 — Electron Runtime and Candidate Isolated-Turn Seam

## Decision

**Electron is the only PortLog product surface.** The React/Next-derived
renderer is an internal Electron renderer module, Electron main is the
composition root, and the Python process on loopback is an internal Electron
sidecar/capability adapter. PortLog is not targeting a standalone browser
application, a hosted product, or a public backend product.

The narrowest current candidate seam for a future isolated,
Pi-compatible runtime is **RunLocalReviewInspectionOptions.createTurn** in
[local-review-inspection.ts](../../frontend/desktop/local-review-inspection.ts#L43-L79).
Put a guest adapter behind that internal seam. Keep the surrounding PortLog
responsibility split intact: Electron main owns composition, credential
resolution, local project-manifest creation, and worker supervision; the
worker constructs the bounded adapter-facing callbacks; the loopback
sidecar/flow implements the domain operations and persists their result
artifacts; and runLocalReviewInspection mediates those callbacks to the
adapter and owns normalized LocalInspectionEvent/LocalInspectionRecord state,
posture, terminal classification, cancellation/error mapping, and
inspection-turn upserts to the local project manifest.

This is deliberately a **candidate/internal seam**, not a claim of a mature
production-variation interface. Pi is the only production adapter today. A
guest adapter that runs behind createTurn would make production variation
real; until then, the injection point is useful evidence, not proof of a
finished abstraction.

This report changes no runtime behavior and authorizes no deletion. Legacy
browser and hosted paths may remain in the repository until a separately
authorized cleanup explicitly targets them.

## Scope rule: product surface is not implementation technology

The following distinction controls this report:

- Electron launching a renderer over a local URL does not make that renderer a
  standalone browser product.
- An ASGI module, FastAPI route, or loopback HTTP request does not make the
  local Python process a public backend product.
- Renderer localStorage for a selected provider and Electron-used
  session/thread state does not make it browser BYOK secret storage.
- Active-turn recovery is not Electron runtime state: the desktop branch
  returns before writeActiveTurn. It belongs to the excluded legacy
  non-desktop path. [Desktop return and legacy write](../../frontend/components/chat/pid-runtime-provider.tsx#L124-L137)

The source contains legacy web and hosted implementations, and the renderer
still has a non-desktop branch. Those facts describe code currently present;
they are not compatibility invariants for the Electron-only target.

## Observed Electron runtime map

| Stage | Current Electron-only behavior | Owner and retained role |
| --- | --- | --- |
| Internal renderer | Packaged Electron starts the bundled UI server with the loopback sidecar URL and opens the assistant route in a BrowserWindow. The renderer detects the preload bridge and takes the desktop inspection path. [Packaged UI and sidecar URL](../../frontend/desktop/electron-main.cjs#L64-L77); [desktop renderer branch](../../frontend/components/chat/pid-runtime-provider.tsx#L104-L133) | Retain as the internal renderer module. The route and React/Next-derived implementation are delivery details inside Electron, not a separately supported browser surface. |
| Electron main | Main starts the sidecar on 127.0.0.1:8000 with the local deployment profile, creates the local project manifest, resolves desktop credentials, spawns one Node worker per turn, relays event frames over IPC, and sends SIGTERM to the supervised worker for cancellation. [Sidecar startup](../../frontend/desktop/electron-main.cjs#L226-L255); [manifest creation](../../frontend/desktop/electron-main.cjs#L280-L289); [runtime resolution and worker launch](../../frontend/desktop/electron-main.cjs#L333-L440); [cancellation and IPC registration](../../frontend/desktop/electron-main.cjs#L449-L530) | Retain as the composition root, credential resolver, manifest-creation owner, and worker supervisor. |
| Per-turn Node worker | The worker turns SIGTERM/SIGINT into an AbortController, writes a temporary model configuration, constructs bounded evidence and governed-check callbacks backed by the loopback sidecar, passes them to the PortLog wrapper, emits normalized frames, and deletes its temporary directory in finally. [Worker lifecycle and sidecar callbacks](../../frontend/desktop/local-inspection-worker.ts#L21-L145) | Retain as Electron-internal per-turn transport and the constructor of adapter-facing capability callbacks. It is not the replacement seam because it currently carries credential and sidecar-transport details. |
| Loopback Python sidecar | Electron invokes the ASGI application with the local profile. The worker calls its topology and governed-check routes; those routes delegate to the local flow, which implements prepared-topology lookup and deterministic checking and persists governed-check result artifacts. [ASGI composition](../../pydexpi_datalog/web/asgi.py#L25-L49); [topology and governed-check routes](../../pydexpi_datalog/web/review_api.py#L396-L401) and [review_api.py](../../pydexpi_datalog/web/review_api.py#L584-L598); [result-artifact persistence](../../pydexpi_datalog/web/chainlit_review_flow.py#L714-L810) | Retain as an internal local capability adapter and domain-operation implementation. HTTP is its process-local transport, not a public product contract. |
| PortLog turn wrapper | runLocalReviewInspection mediates the worker-constructed callbacks to the runtime adapter, constructs and updates LocalInspectionRecord, normalizes and sequences LocalInspectionEvent values, applies posture rules, maps cancellation/errors to terminal state, disposes the runtime, and requests initial/final inspection-turn upserts to the local project manifest. [Record and wrapper lifecycle](../../frontend/desktop/local-review-inspection.ts#L92-L204) | Retain for those wrapper-owned responsibilities and as the host of the selected candidate seam; domain-operation implementation and other persistence remain outside it. |
| Current Pi adapter | The default factory closes over Pi construction, subscribes to Pi events, and maps only selected Pi event shapes into the PortLog event union. Pi itself receives only the current bounded evidence and deterministic-check tools. [Default Pi factory and normalization](../../frontend/desktop/local-review-inspection.ts#L207-L261); [Pi tool constraints and lifecycle](../../frontend/desktop/pi-turn-adapter.ts#L53-L158) | Retain as the current adapter beneath the seam. A guest adapter may replace this role, not the PortLog wrapper around it. |

The renderer's normal backend base URL also defaults to the same loopback
address when Electron supplies no packaged override. That is more evidence of
an internal process arrangement, not a claim that 127.0.0.1 is a public
deployment endpoint. [review-backend.ts](../../frontend/lib/review-backend.ts#L1244-L1246)

## Retained Electron modules versus excluded product roles

| Retain inside the Electron product | Why it remains | Excluded role |
| --- | --- | --- |
| Electron main, preload IPC, the internal renderer, and the per-turn worker | They compose, run, and stop the one supported product. Electron main owns credential resolution, project-manifest creation, and worker supervision; the worker constructs the bounded sidecar-backed callbacks before invoking the wrapper. [Manifest creation](../../frontend/desktop/electron-main.cjs#L280-L289); [runtime resolution and worker launch](../../frontend/desktop/electron-main.cjs#L333-L400); [worker callback construction](../../frontend/desktop/local-inspection-worker.ts#L80-L142) | A standalone browser application or a browser-accessible desktop runtime. |
| The local sidecar slices actually invoked by Electron: ASGI local composition, topology lookup, governed checks, and their flow implementation | The worker asks for prepared topology and posts a scoped check. The flow reads prepared artifacts/facts, executes the deterministic check, derives evidence, and writes its result artifact. [Worker requests](../../frontend/desktop/local-inspection-worker.ts#L80-L127); [topology implementation](../../pydexpi_datalog/web/chainlit_review_flow.py#L294-L342); [governed-check implementation](../../pydexpi_datalog/web/chainlit_review_flow.py#L714-L810) | A hosted/public backend product. The directory name web and the HTTP transport do not determine product scope. |
| The local project manifest and the wrapper's LocalInspectionRecord | Electron main creates the project manifest during import. The manifest module performs atomic writes; runLocalReviewInspection requests active and terminal inspection-turn upserts when a project directory is present. [Main-process manifest creation](../../frontend/desktop/electron-main.cjs#L280-L289); [manifest write and upsert](../../frontend/desktop/local-project-manifest.cjs#L8-L14) and [local-project-manifest.cjs](../../frontend/desktop/local-project-manifest.cjs#L111-L120); [wrapper upsert points](../../frontend/desktop/local-review-inspection.ts#L132-L203) | Hosted S3/libSQL/ProfileBundle parity, account-scoped persistence, or public turn-lifecycle persistence contracts. |
| Renderer non-secret local state | The Electron renderer reads a selected OAuth provider name and uses the shared session ID plus local thread-history adapter. The desktop branch returns before writeActiveTurn, so active-turn recovery belongs only to the excluded non-desktop path. [Session and history adapter](../../frontend/components/chat/pid-runtime-provider.tsx#L62-L63) and [pid-runtime-provider.tsx](../../frontend/components/chat/pid-runtime-provider.tsx#L299-L304); [provider selection](../../frontend/components/chat/pid-runtime-provider.tsx#L320-L352); [desktop return before active-turn write](../../frontend/components/chat/pid-runtime-provider.tsx#L124-L137); [thread-history persistence](../../frontend/components/chat/pid-runtime-provider.tsx#L622-L626) | Browser BYOK credentials and legacy browser active-turn recovery. The Electron state listed here contains no provider secret and is not the pydexpi.byok.v1 store described by ADR-0014. |
| Pi as the existing default adapter | Pi supplies model streaming and sequential tool orchestration only. Electron main supplies the resolved credential, the worker supplies sidecar-backed callbacks, the wrapper owns normalized record/event and terminal mapping, and the sidecar/flow owns domain execution and result artifacts. [Pi adapter contract](../../frontend/desktop/pi-turn-adapter.ts#L53-L158) | Pi-owned PortLog credentials, projects, result artifacts, durable transcript authority, generic host tools, or a Pi-specific contract imposed on a guest. |

Do not prune pydexpi_datalog/web/asgi.py, review_api.py, or
chainlit_review_flow.py merely because their names contain web or because
Electron speaks loopback HTTP to them. Retain the local implementations where
the Electron execution path invokes them. Conversely, retaining an
implementation does not restore its former browser/hosted product role.

## Selected seam: createTurn

### The current internal interface

The structural interface at createTurn is small enough to replace the turn
mechanics while leaving PortLog-owned behavior on the host side:

~~~text
createTurn({
  emit(nonterminal LocalInspectionEvent),
  getEvidence?: ({ artifactId, claim }) -> Promise<unknown>,
  getRuleCheck?: ({ checkId, scopeEntityId, signal }) -> Promise<unknown>
}) -> Promise<{
  prompt(text) -> Promise<void>,
  abort() -> Promise<void>,
  dispose() -> Promise<void>
}>
~~~

The precise contract is in [CreateTurnOptions and
TurnRuntime](../../frontend/desktop/local-review-inspection.ts#L43-L62):

- **emit** accepts only assistant text deltas and tool request/result events.
  The wrapper, not the adapter, emits turn_started and terminal events.
- **getEvidence** and **getRuleCheck** are bounded callbacks constructed by the
  worker and backed by sidecar/flow implementations. runLocalReviewInspection
  mediates them into the adapter-facing interface; the adapter requests an
  operation but does not receive implicit project, filesystem, rule-engine, or
  domain authority.
- **prompt** runs one PortLog prompt; **abort** cooperates with the host stop
  path; **dispose** releases transient runtime state even after an error.
- The adapter returns no LocalInspectionRecord, terminal status, raw guest
  transcript, persistence handle, or credential store.

The default factory is createPiRuntime, so Pi-specific configuration and event
translation sit below this interface. [Default factory selection](../../frontend/desktop/local-review-inspection.ts#L135-L154);
[Pi normalization](../../frontend/desktop/local-review-inspection.ts#L207-L261)

### Wrapper-owned invariants the adapter cannot own

Within the responsibility split above, runLocalReviewInspection owns these
specific invariants:

1. **Posture and terminal answer classification.** It chooses Inspect,
   Verify, or Chat posture and supplies the corresponding prompt. The sidecar
   implements the deterministic operation; after that result returns, the
   wrapper prevents model prose from becoming the engineering outcome and
   restates a completed deterministic result. [Posture prompts and result enforcement](../../frontend/desktop/local-review-inspection.ts#L156-L188) and [verify/inspect prompts](../../frontend/desktop/local-review-inspection.ts#L298-L311)

2. **Normalized events and records.** It appends a PortLog event union with a
   sequence and timestamp, collects final text/evidence IDs/deterministic
   checks, and owns the LocalInspectionRecord status. Raw Pi or guest events
   are not a PortLog event contract. [Event and record definitions](../../frontend/desktop/local-review-inspection.ts#L8-L41); [event normalization](../../frontend/desktop/local-review-inspection.ts#L110-L130)

3. **Inspection-turn manifest upserts.** It requests the initial record upsert
   when a project directory is present and the terminal record upsert in
   finally. Electron main owns manifest creation, while the manifest module
   performs the actual atomic write. [Main-process manifest creation](../../frontend/desktop/electron-main.cjs#L280-L289); [wrapper upsert points](../../frontend/desktop/local-review-inspection.ts#L132-L203); [manifest upsert implementation](../../frontend/desktop/local-project-manifest.cjs#L111-L120)

4. **Cancellation and errors.** Electron sends SIGTERM to the active worker;
   the worker aborts its controller; the wrapper calls runtime.abort. An
   aborted signal or AbortError becomes cancelled plus turn_cancelled; every
   other error becomes failed plus turn_failed; dispose and the final
   inspection-turn upsert still run. [Electron cancellation](../../frontend/desktop/electron-main.cjs#L449-L458); [worker signal handling](../../frontend/desktop/local-inspection-worker.ts#L21-L23); [wrapper terminal handling](../../frontend/desktop/local-review-inspection.ts#L143-L204)

### Why this is the narrowest current candidate seam

The createTurn module has useful **depth**: callers use one internal interface
to vary the entire turn loop while the wrapper hides record construction,
event normalization, posture enforcement, inspection-turn upsert timing, and
terminal classification. That gives **leverage** to every Electron caller and
**locality** to maintainers: guest-runtime work stays in an adapter instead
of spreading into the renderer, IPC, worker, manifest, and sidecar modules.

It is narrower and more appropriate than the nearby alternatives:

| Candidate | Why it is not the selected seam |
| --- | --- |
| createGovernedPiReviewTurn | It is physically smaller, but it is Pi's adapter implementation: it exposes a Pi Agent/session/subscription shape and the caller must translate Pi events. A guest would either imitate Pi or force Pi concepts into the PortLog wrapper. [Pi return shape](../../frontend/desktop/pi-turn-adapter.ts#L123-L158); [Pi event mapping](../../frontend/desktop/local-review-inspection.ts#L225-L261) |
| The worker/stdio process | It is transport around the turn, but currently receives a resolved runtime key and a sidecar endpoint. Replacing it first would combine runtime selection, secret delivery, capability transport, and isolation decisions with the loop comparison. [Worker launch inputs](../../frontend/desktop/electron-main.cjs#L367-L400) |
| Electron main | It is correctly the composition root, not a runtime seam. Moving the guest choice here would widen the change into provider resolution, IPC, sidecar lifecycle, and application shutdown. [Composition responsibilities](../../frontend/desktop/electron-main.cjs#L226-L255) and [electron-main.cjs](../../frontend/desktop/electron-main.cjs#L493-L543) |
| Loopback sidecar routes | They are PortLog capability implementations. Replacing them would change prepared-topology and deterministic-check authority rather than only the agent-loop mechanics. [Worker route calls](../../frontend/desktop/local-inspection-worker.ts#L80-L127); [route delegation](../../pydexpi_datalog/web/review_api.py#L396-L401) and [review_api.py](../../pydexpi_datalog/web/review_api.py#L584-L598) |

One current production adapter means this seam is not yet a demonstrated
production-variation interface. That caveat is material: do not inflate the
interface, rename it as a public runtime port, or claim adapter parity before
the guest adapter exists and is exercised through it.

## Recommendation for the future isolated Pi-compatible runtime

Introduce a guest adapter behind createTurn and leave the Electron wrapper in
place. The adapter may implement guest lifecycle, model streaming, and
guest-to-host capability requests. It must turn guest output into the three
nonterminal PortLog events and honor prompt, abort, and dispose.

Keep each existing owner in place:

- Electron main owns composition, model/provider credential resolution,
  project-manifest creation, and worker supervision.
- The per-turn worker constructs the bounded evidence and governed-check
  callbacks and backs them with loopback sidecar requests.
- The sidecar/flow implements prepared-topology lookup and deterministic
  checking and persists its result artifacts.
- runLocalReviewInspection mediates the callbacks to the adapter and owns
  normalized event/record state, posture, terminal classification,
  cancellation/error mapping, and initial/final inspection-turn upsert
  requests.
- local-project-manifest.cjs performs the project-manifest writes requested by
  Electron main and runLocalReviewInspection.

This avoids relocating composition, domain operations, result artifacts,
records, credentials, or cancellation responsibilities into the isolated
guest. It also lets a future Pi-compatible guest reuse Pi-compatible
mechanics without making Pi state, events, or persistence the product
contract.

## Electron-only compatibility invariants

The following constrain a guest adapter adopted behind createTurn:

1. Electron main remains the owner of composition, credential resolution,
   project-manifest creation, and worker supervision; the renderer, IPC,
   worker, and loopback sidecar remain internal parts of the product.
2. runLocalReviewInspection remains the owner of LocalInspectionEvent,
   LocalInspectionRecord, event sequence/timestamps, final text/evidence/check
   collection, posture, terminal classification, cancellation/error mapping,
   and initial/final inspection-turn upsert requests. The manifest module
   performs the writes.
3. The worker constructs the supplied callbacks, and the sidecar/flow
   implements their domain operations and persists operation result artifacts.
   A guest receives no ambient access to PortLog projects, prepared artifacts,
   rule execution, host credentials, or a new authoritative persistence
   location.
4. Cancellation keeps its current chain: Electron main signals the supervised
   worker, the worker aborts its controller, and runLocalReviewInspection calls
   runtime.abort and maps abort/error outcomes into the record. A late guest
   success cannot replace a cancelled record, and cleanup still invokes
   dispose.
5. The sidecar/flow remains authoritative for deterministic execution;
   runLocalReviewInspection remains authoritative for Inspect/Verify posture
   and restatement of the returned deterministic result.

The following are **not** compatibility invariants for this target:

- standalone browser behavior or public Next route behavior;
- browser BYOK credentials or browser-secret transport;
- Better Auth/JWT, hosted accounts/principals, and hosted provider-key stores;
- hosted S3/libSQL/ProfileBundle parity; or
- public TurnLifecycleStore and HTTP product contracts, including hosted
  cancellation/recovery semantics.

Those roles may still be implemented in the repository. Their presence is not
an instruction to preserve their product behavior for the isolated Electron
runtime, and this documentation bead does not authorize their removal.

## ADR status and legacy cleanup

For the Electron-only target, [ADR-0014](../adr/0014-byok-keys-live-in-the-browser.md#L1-L12)
conflicts with and is superseded as a product-scope requirement: its
browser-BYOK secret-store premise is not part of the supported product.
Likewise, [ADR-0016](../adr/0016-local-and-hosted-deployment-profiles.md#L1-L20)
conflicts with and is superseded as a product-scope requirement: local/hosted
parity, hosted accounts, and hosted storage are not compatibility targets.

This records a target-scope conflict; it does not edit either ADR, invalidate
their historical reasoning, or delete their code paths. Electron renderer
localStorage for selected-provider and shared session/thread state remains
distinct from the browser secret store that ADR-0014 describes. Active-turn
recovery remains part of the excluded non-desktop path.

## Downstream bead guidance

| Bead | Scope after this decision |
| --- | --- |
| pydexpi-datalog-1-23bh.7 | Decide Electron runtime architecture only: how Electron main, the per-turn worker, the loopback sidecar, and an isolated guest compose while preserving the responsibility split documented above. Do not reopen standalone-browser, hosted-parity, public-HTTP, or account/key-store architecture. |
| pydexpi-datalog-1-23bh.8 | Adopt the selected guest adapter behind createTurn, prove the Electron local record/event/cancellation behavior, and treat legacy dual-path cleanup as a separate, explicitly authorized work item. Do not couple that adoption to deleting browser/hosted paths. |

## Source index

All primary evidence below is repository source. The final row is retained
only to identify excluded legacy scope.

| Source | Role in this report |
| --- | --- |
| [electron-main.cjs](../../frontend/desktop/electron-main.cjs#L64-L77), [electron-main.cjs](../../frontend/desktop/electron-main.cjs#L226-L289), and [electron-main.cjs](../../frontend/desktop/electron-main.cjs#L333-L530) | Electron renderer launch, local-sidecar composition, project-manifest creation, provider/credential resolution, per-turn worker supervision, IPC, and cancellation signaling. |
| [pid-runtime-provider.tsx](../../frontend/components/chat/pid-runtime-provider.tsx#L62-L63), [pid-runtime-provider.tsx](../../frontend/components/chat/pid-runtime-provider.tsx#L104-L137), [pid-runtime-provider.tsx](../../frontend/components/chat/pid-runtime-provider.tsx#L299-L352), and [pid-runtime-provider.tsx](../../frontend/components/chat/pid-runtime-provider.tsx#L622-L626) | Internal renderer desktop route, its return before legacy active-turn persistence, provider selection, session identity, IPC interaction, and Electron-used thread history. |
| [local-inspection-worker.ts](../../frontend/desktop/local-inspection-worker.ts#L21-L145) | Per-turn signal handling, temporary configuration, construction of bounded sidecar-backed callbacks, wrapper invocation, frame output, and cleanup. |
| [local-review-inspection.ts](../../frontend/desktop/local-review-inspection.ts#L8-L79), [local-review-inspection.ts](../../frontend/desktop/local-review-inspection.ts#L92-L204), and [local-review-inspection.ts](../../frontend/desktop/local-review-inspection.ts#L207-L311) | Selected createTurn interface, callback mediation, PortLog record/event normalization, posture, inspection-turn upsert timing, errors, cancellation mapping, and default Pi adapter placement. |
| [pi-turn-adapter.ts](../../frontend/desktop/pi-turn-adapter.ts#L53-L158) | Current Pi adapter's tool allowlist, provider streaming, abort behavior, and Pi-specific return shape. |
| [local-project-manifest.cjs](../../frontend/desktop/local-project-manifest.cjs#L8-L42) and [local-project-manifest.cjs](../../frontend/desktop/local-project-manifest.cjs#L111-L120) | Atomic local project-manifest creation and inspection-turn upsert writes invoked by Electron main and runLocalReviewInspection, respectively. |
| [asgi.py](../../pydexpi_datalog/web/asgi.py#L25-L49), [review_api.py](../../pydexpi_datalog/web/review_api.py#L396-L401), [review_api.py](../../pydexpi_datalog/web/review_api.py#L584-L598), and [chainlit_review_flow.py](../../pydexpi_datalog/web/chainlit_review_flow.py#L294-L342) | Local-sidecar composition and the topology capability invoked by Electron. |
| [chainlit_review_flow.py](../../pydexpi_datalog/web/chainlit_review_flow.py#L714-L810) | Sidecar/flow deterministic-check execution, evidence derivation, and result-artifact persistence behind the loopback capability route. |
| [ADR-0014](../adr/0014-byok-keys-live-in-the-browser.md#L1-L12) and [ADR-0016](../adr/0016-local-and-hosted-deployment-profiles.md#L1-L20) | Legacy browser/hosted decisions identified above as conflicting with and superseded for the Electron-only target; neither ADR is edited here. |
