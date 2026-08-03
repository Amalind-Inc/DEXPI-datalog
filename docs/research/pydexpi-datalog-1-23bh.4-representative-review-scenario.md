# pydexpi-datalog-1-23bh.4 — Representative End-to-End Review Scenario

## Settled purpose, scope, and threat model

This is one representative acceptance scenario for comparing two isolated-turn
topologies over the *same* untrusted, multifile engineering-review upload. It
is deliberately not a benchmark suite, a guest-adapter implementation, a VMPI
run, or a topology recommendation.

Electron remains the only product surface. The scenario preserves the existing
ownership split: Electron main composes the turn, resolves credentials, creates
the project manifest, and supervises workers; the worker constructs bounded
callbacks; the sidecar/flow owns PortLog domain operations and artifacts; and
<code>runLocalReviewInspection</code> owns normalized records/events, posture,
terminal classification, cancellation/error mapping, and manifest-upsert
requests. The candidate internal variation point is
<code>createTurn</code>, not Electron main, the worker transport, or a sidecar
route. [Current seam report](pydexpi-datalog-1-23bh.1-current-runtime-seam.md#decision)
and [the desktop wrapper](../../frontend/desktop/local-review-inspection.ts#L43-L204)
establish those boundaries.

The VM is justified here by an untrusted command-line toolchain that can inspect
the upload and create native child processes. Pure deterministic Datalog or the
existing bounded PortLog check is not, by itself, the reason to put work in a
guest. Pi core and Pi AI remain unchanged behind the narrow seam; this scenario
does not introduce Pi AgentSession, OMP session state, or Pi/OMP persistence.
The inventory likewise distinguishes Pi's host-oriented tool loop from a VM's
filesystem, process, and network isolation responsibilities.
[Capability inventory](pydexpi-datalog-1-23bh.2-upstream-capability-inventory.md#concise-answer)

The security claim under test is narrow and falsifiable:

> A command-line toolchain that may execute native processes and read the
> untrusted upload cannot read or modify PortLog host state, credentials,
> configuration, sidecar capabilities, external network, or non-approved
> output paths; PortLog receives at most one bounded command result through the
> defined candidate/admission path.

Neither topology may be called viable because it merely starts a guest. It
passes only when the captured evidence below proves the claim. A missing
adapter or control protocol is a blocking result, not a reason to silently run
the work on the host.

## Fixed review subject and existing PortLog operation

Use this immutable input tree without adding, removing, rewriting, or
substituting files:

<code>testdata/benchmark/trap_bundle/e06-trap-drawing</code>

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| <code>drawing.xml</code> | 6,288 | <code>2a6b4762cd1c85c9fcf329f885ca368769a84ebd5dbf5966c6a0781bb4038351</code> |
| <code>graph.json</code> | 11,669 | <code>4e79b44d7f65488ab1aff838e2d6a696486c20b5995716de73c8fe5c5ff651da</code> |
| <code>graph_facts.json</code> | 15,568 | <code>8800d50b1c1827467a09de189f0a313816107b3051dcc0c2dc08dff1fb92db83</code> |
| <code>README.md</code> | 770 | <code>83bb096dab0263804629b24754463488d7b479cf27b32e049213e508fc9a9a60</code> |

The fixture guide declares it a self-contained read-only sandbox input and
identifies its graph witness conventions.
[E06 trap-bundle guide](../../testdata/benchmark/trap_bundle/e06-trap-drawing/README.md)
Its checked-in facts identify a real <code>CentrifugalPump</code>,
<code>proteusId: CentrifugalPump-1</code>, with tag <code>P-4713</code>.
[E06 graph facts](../../testdata/benchmark/trap_bundle/e06-trap-drawing/graph_facts.json#L319-L328)

The one selected existing governed PortLog operation is:

~~~text
getRuleCheck({
  checkId: "pump_discharge_check_valve",
  scopeEntityId: <the prepared-topology source_graph_node_id for P-4713>
})
~~~

It is the operation required by the existing Verify prompt, rather than an
invented rule API. [Verify prompt and check identifier](../../frontend/desktop/local-review-inspection.ts#L298-L307)
The worker's bounded callback sends only its check ID and scoped entity to the
host sidecar. [Worker callback](../../frontend/desktop/local-inspection-worker.ts#L86-L122)
The host flow executes the allowlisted deterministic check and writes the
PortLog-owned governed-check result artifact.
[Flow implementation](../../pydexpi_datalog/web/chainlit_review_flow.py#L714-L810)
[Check ownership and scope validation](../../pydexpi_datalog/verification/governed_check.py#L42-L171)

### Fixture-preparation prerequisite

The source facts establish <code>P-4713</code>, but they do not check in the
sidecar's prepared-topology identity for this particular trap bundle. Before
either topology runs, bead <code>.5</code> must perform one narrow,
host-authorized preparation lookup:

1. Prepare <code>drawing.xml</code> through the existing local PortLog flow.
2. Read the existing bounded topology response.
3. Select the sole node whose label is <code>CentrifugalPump</code> and whose
   tag is <code>P-4713</code>.
4. Record that node's <code>source_graph_node_id</code> and freeze it as
   <code>scopeEntityId</code> for both topology runs and their retries.

This is a **fixture-preparation prerequisite**, not a new API, a rewritten
fixture, or an assumed UUID mapping. It follows the existing governed-check
test's topology-to-scope lookup pattern.
[Existing topology scope lookup](../../tests/web/test_governed_check_api.py#L45-L66)
The scenario must capture the actual deterministic outcome from the prepared
upload; it must not import a claimed outcome from a different E06 fixture.

## Trust boundary

| Location / channel | May contain or do | Must not contain or do | Required evidence |
| --- | --- | --- | --- |
| **Host** | Electron main, wrapper, worker supervision, project manifest, resolved provider credential, the host-authorized PortLog callbacks, sidecar/flow, governed-check artifact, bounded supervisor telemetry, and a fresh <code>.portlog-host-sentinel</code> canary file in the host launch/project workspace before each run. | Must not mount its project, manifest, credential stores, sidecar state, configuration, or the canary into the guest. It must not treat PTY text as a PortLog result. The actual canary path and contents stay host-only. | Host launch configuration, manifest-upsert record, sidecar request/response metadata, redacted credential-confinement test, canary-unchanged verification, and supervisor lifecycle log. |
| **Guest read-only input** at <code>/review/input</code> | Exactly the four fixed E06 files above, exposed as a read-only view. The toolchain may enumerate, hash, and read them. | No writable overlay, no parent directory traversal into a host mount, no project directory, no hidden fixture files, no automatically injected config, and no <code>/workspace</code> mount. | Guest mount description plus host SHA-256 before/after comparison for all four files. |
| **Guest ephemeral scratch** at <code>/review/scratch</code> | Guest-local writable scratch only. The toolchain may create temporary files and, on normal command completion, leave its one candidate <code>result.json</code>. | It is not a host-mounted output directory; it contains no credentials and is destroyed after every normal, rejected, failed, or cancelled run. | Scratch path, lifecycle timestamps, post-destruction absence, and a bounded entry/byte count before destruction. |
| **Sole application export channel** | The sole **guest candidate file** is <code>/review/scratch/result.json</code>, which only a normally completed command may leave. After that normal exit, the host adapter retrieves only that candidate, validates it, and applies the admission rule below. Host-owned lifecycle/terminal and admission/rejection records are not guest exports. A future adapter may use a guest-file pickup or equivalent bounded protocol. | No arbitrary stdout/stderr payload, shared writable host directory, socket callback, extra guest export file, sidecar request, clipboard, or network request is an application export channel. Raw VM/PTY observations are supervisor telemetry only and are never forwarded as a PortLog tool result. | A normal single-candidate pickup with its host admission record, or one bounded host-generated rejection record. If the prototype cannot supply this channel, classify it as blocked-by-missing-adapter/protocol. |

An accepted scenario exposes only <code>/review/input</code> and
<code>/review/scratch</code> as host-provided review paths; <code>/workspace</code>
must not be mounted.

The guest environment is an allowlist, not a filtered copy of the host
environment. It may contain only the minimum executable search path, locale,
working-directory values, and a nonsecret run ID. It contains no
<code>PORTLOG_*</code>, provider-specific credential, Pi configuration, user
home/config path, sidecar endpoint, or host project path. Values are never
logged as evidence.

## Exact user request and deterministic workload

Use this exact user request in both topologies:

> Review the uploaded E06 drawing. Run PortLog's
> <code>pump_discharge_check_valve</code> for pump <code>P-4713</code>, then
> run the supplied untrusted native review command against every uploaded file.
> Report PortLog's deterministic outcome and evidence separately from the
> command result. Do not modify the upload or PortLog data.

The test driver must make the turn deterministic without changing Pi core or
Pi AI. It supplies a controlled, host-authorized response stream that produces
these two tool requests in order and then one fixed completion sentence. It is
not an AgentSession, OMP session, alternate persistence model, or a different
agent runtime:

1. Request the governed check with the frozen <code>scopeEntityId</code>.
2. Request the untrusted native command stage with the fixed input manifest
   and policy probes below.
3. After both host-owned results return, produce exactly:
   <code>PortLog deterministic result and bounded command artifact recorded.</code>

The deterministic response stream gives both topologies the same control flow;
the comparison is where Pi and the command execute, not whether a model happened
to choose a tool. A live provider is not required for this architecture proof.
If a live provider is used later, Electron main still owns the raw provider
credential and all logs must redact it.

The normal-completion workload phases are:

1. **Host preparation.** Verify the four source hashes, perform the
   fixture-preparation prerequisite, create a fresh review session and turn ID,
   and before each run create a fresh nonsecret
   <code>.portlog-host-sentinel</code> canary file in the host launch/project
   workspace. Its actual host path and value are neither passed to the guest nor
   logged.
2. **PortLog deterministic operation.** Issue the selected governed-check
   request through the host-authorized callback. Preserve its deterministic
   result and host result-artifact identity.
3. **Risky native command.** Start the fixed untrusted command in the guest
   with only the read-only input view and ephemeral scratch.
4. **Artifact admission.** Only after a normal command exit, retrieve and
   validate the one bounded candidate <code>result.json</code> and produce the
   host admission record, or a host rejection record. Failed and cancelled
   executions produce no candidate and retain only their existing bounded
   host-owned lifecycle/terminal evidence.
5. **Turn completion.** Feed the admitted command result to the Pi turn,
   normalize the events in the wrapper, perform the terminal manifest-upsert
   request, and destroy scratch/guest resources.
6. **Cold retry.** Start a new worker/guest/process with a new run ID and
   scratch directory over the same fixed input and frozen scope. Do not resume
   RAM, a process, a guest checkpoint, Pi state, an AgentSession, or OMP state.

The retry may record a normal host-side governed-check cache provenance if the
existing flow reports one, but it must not restore guest memory or process
state. A fresh guest lifecycle is required for every retry.

### Cross-topology invariants

The following are test fixtures, not per-topology choices. A result is invalid
if either topology changes one of them to make itself pass:

| Invariant | Fixed value for Hybrid and Full guest |
| --- | --- |
| Upload and prepared scope | The four fixed source files and hashes, plus the one frozen prepared-topology source ID for <code>P-4713</code>. |
| User/model workload | The exact user request and controlled two-tool-call response stream above. |
| Risky command | One <code>e06-native-review-v1</code> executable/argv digest and the five deterministic command behaviors, including a real native child. |
| PortLog operation | One host-owned <code>pump_discharge_check_valve</code> request over the frozen scope ID; the guest never substitutes a rule engine. |
| Result contract | The same normal-only guest-candidate schema, canonical digest rules, host admission/rejection object, and execution-outcome rules. |
| Negative probes | The same six probe IDs, targets, ordering, and host corroboration. |
| Cancellation | The same <code>native-child-hold</code> marker, 250 ms trigger delay, 5,000 ms termination bound, and no-late-success rule. |
| Captured evidence | The structured record, governed-check artifact identity, raw supervisor ledger, artifact/rejection decision, host policy evidence, cleanup proof, and cold-retry record. |

## Fixed untrusted native-command behavior

The command stage is a harness-defined untrusted toolchain, identified in the
artifact as <code>e06-native-review-v1</code>. This bead does not create that
toolchain; bead <code>.5</code> supplies it only when the selected prototype can
run the following behavior unchanged in both topologies.

The guest toolchain's only host-provided scenario paths are the read-only input
view and ephemeral scratch; <code>/workspace</code> is not mounted. Its fixed
binary may receive a nonsecret run ID as launch metadata, but it receives no
host data through argv, environment, stdin, mounted files, or descriptors: no
host path or canary value, credential, sidecar endpoint, model configuration,
scope ID, or generic capability callback. The
<code>P-4713</code> search string is fixed test behavior, not a host-supplied
input. Its deterministic behavior is:

1. Enumerate exactly the four input paths, read each one, and calculate the
   SHA-256 and byte count.
2. Inspect <code>drawing.xml</code> and <code>graph_facts.json</code> for the
   literal <code>P-4713</code>; record only the match fact and path, never a
   full file excerpt.
3. Spawn at least one real native child process from the command-line
   toolchain. The parent must collect the child's exit/termination fields.
   A library call with no child process is insufficient.
4. Execute the six negative probes in the table below, without retrying a
   prohibited operation through another channel.
5. On normal completion, leave only the completed contract candidate at
   <code>/review/scratch/result.json</code> and exit. The toolchain may write
   temporary scratch files, but it may not leave a second export file. A failed
   or cancelled command leaves no <code>result.json</code> and may not export
   one later.

The command must have one stable cancellation phase named
<code>native-child-hold</code>: after the native child has started and completed
its input reads, but before it writes <code>result.json</code>, it emits the
bounded phase marker to the supervisor and waits. The cancellation case uses
that same command and phase in both topologies.

## Bounded command-result candidate and admission contract

Only a normally completed guest command may leave
<code>/review/scratch/result.json</code>. That file is a UTF-8 JSON **candidate**
until host validation completes; its status is exactly <code>completed</code>.
There are no additional properties at any level except the explicitly listed
<code>findings</code> entries.

~~~json
{
  "schema_version": 1,
  "kind": "untrusted_command_result",
  "run_id": "<uuid>",
  "status": "completed",
  "input": {
    "bundle_id": "e06-trap-drawing",
    "manifest_sha256": "<64 lowercase hex>",
    "files": [
      { "path": "<one fixed relative path>", "bytes": 0, "sha256": "<64 lowercase hex>" }
    ]
  },
  "toolchain": {
    "id": "e06-native-review-v1",
    "executable_sha256": "<64 lowercase hex>",
    "argv_sha256": "<64 lowercase hex>"
  },
  "process": {
    "started_monotonic_ms": 0,
    "ended_monotonic_ms": 0,
    "exit_code": 0,
    "termination": "exited",
    "signal": null,
    "native_children": [
      {
        "ordinal": 1,
        "executable_sha256": "<64 lowercase hex>",
        "exit_code": 0,
        "termination": "exited"
      }
    ],
    "stdout": { "bytes": 0, "sha256": "<64 lowercase hex>", "truncated": false },
    "stderr": { "bytes": 0, "sha256": "<64 lowercase hex>", "truncated": false }
  },
  "findings": [
    {
      "id": "<ascii identifier>",
      "kind": "input_file_seen | entity_marker_seen | native_child_seen",
      "subject_path": "<one fixed input path or null>",
      "message": "<bounded nonsecret text>"
    }
  ],
  "negative_probes": [
    {
      "id": "host_sentinel | host_env_credentials_config | loopback_sidecar | external_network | input_mutation | output_escape",
      "result": "denied | unexpectedly_allowed | not_attempted",
      "code": "<bounded nonsecret reason>"
    }
  ],
  "scratch": { "entry_count": 0, "bytes_written": 0 },
  "payload_sha256": "<64 lowercase hex>"
}
~~~

For every SHA-256 calculation over JSON in this scenario, **canonical JSON**
means a UTF-8 serialization of an RFC 8259 JSON value with object keys sorted
recursively in lexicographic order, no insignificant whitespace, and array
order preserved. For a digest field calculated from the object that contains
it, omit that digest field before serialization; specifically,
<code>payload_sha256</code> is omitted when calculating
<code>payload_sha256</code>. File, executable, and captured-stream digests are
of their exact observed bytes rather than a JSON reserialization.

The JSON digest sources are fixed: <code>manifest_sha256</code> is the
canonical JSON encoding of the four-item <code>input.files</code> array;
<code>argv_sha256</code> is the canonical JSON encoding of the normalized
argument vector; and <code>payload_sha256</code> is the canonical JSON encoding
of the whole candidate with that field omitted. The file, executable, native
child executable, stdout, stderr, and raw-supervisor-ledger SHA-256 values each
digest their respective bounded raw byte streams.

The host-side command adapter, not the guest, produces exactly one
<code>untrusted_command_artifact_admission</code> object for each normally
exited command considered for pickup, and none for failed or cancelled
execution. It has this exact shape and is at most 2,048 UTF-8 bytes:

~~~json
{
  "schema_version": 1,
  "kind": "untrusted_command_artifact_admission",
  "run_id": "<uuid>",
  "decision": "admitted | rejected",
  "candidate_path": "/review/scratch/result.json",
  "candidate_bytes": "<integer 0..65536 | over_limit | unavailable>",
  "admitted_payload_sha256": "<64 lowercase hex | null>",
  "reason_code": "<ASCII 1..96 chars | null>",
  "reason_message": "<nonsecret UTF-8 1..512 bytes | null>"
}
~~~

All fields above are required. For an admitted decision,
<code>candidate_bytes</code> is the exact candidate byte count,
<code>admitted_payload_sha256</code> is the validated candidate digest, and
both reason fields are null. For a rejected decision,
<code>admitted_payload_sha256</code> is null and both reason fields are
non-null. <code>candidate_bytes</code> is <code>over_limit</code> when the
adapter reads at most 65,537 bytes and establishes that the candidate exceeds
65,536 bytes, or <code>unavailable</code> when it cannot safely read a regular
candidate. The record contains no guest-supplied candidate bytes, canary
contents, or raw logs.

Validation is strict:

| Field / condition | Exact limit or rule |
| --- | --- |
| Guest candidate | At most 65,536 UTF-8 bytes. It is eligible only after a normal parent exit with <code>status: completed</code>, <code>process.termination: exited</code>, and <code>process.exit_code: 0</code>. Reject malformed JSON, duplicate JSON keys, a non-object root, an unknown property, or a symlink/nonregular result path. |
| Input provenance | <code>input.files</code> has exactly the four paths in lexical order, each with the fixed byte count and SHA-256 above. <code>manifest_sha256</code> uses the canonical JSON rule above. |
| Tool provenance | The tool executable and normalized argument vector are separately SHA-256 hashed; <code>argv_sha256</code> uses the canonical JSON rule above. This identifies the exact native command under test without recording raw arguments. |
| Process fields | Time fields are nonnegative integers with end at or after start. The completed candidate requires parent <code>exit_code</code> 0 and <code>termination</code> <code>exited</code>. <code>native_children</code> has one through four entries, each with <code>termination</code> <code>exited</code> and no raw argv or environment. |
| Logs | The candidate includes only byte count, digest, and truncation flag for stdout/stderr; it includes no raw stdout/stderr text. Each observed stream is capped at 4,096 bytes by the supervisor. |
| Findings | At most 12 entries. Each ID is ASCII, 1–64 characters; each message is at most 512 UTF-8 bytes; each subject path is one of the four fixed paths or null. |
| Negative probes | Exactly six entries, in the order shown in the schema. A completed normal run requires all six to be <code>denied</code>. |
| Scratch accounting | <code>entry_count</code> is at most 32 and <code>bytes_written</code> is at most 1,048,576. It is measurement only; scratch is destroyed after pickup, rejection, failure, or cancellation. |
| Payload digest | <code>payload_sha256</code> uses the canonical JSON rule above and omits only <code>payload_sha256</code> itself. |
| Host admission/rejection | The host-side command adapter generates exactly the required 2,048-byte-bounded admission object above. An admitted object has a non-null validated digest and null reason fields; a rejected object has null admitted digest and non-null bounded reason fields. |

The host rejects a missing, over-limit, malformed, duplicate-key, extra-output,
wrong-hash, unexpectedly-allowed, output-escape, or nonregular candidate. It
discards all guest-supplied candidate bytes and persists only the bounded
host-generated rejection object; it never forwards those bytes or raw logs.

| Execution outcome | Guest candidate | Host-owned result and terminal behavior |
| --- | --- | --- |
| Normal | One valid <code>result.json</code> with <code>status: completed</code> after normal command exit. | The adapter writes an <code>admitted</code> object as lifecycle evidence. The validated guest candidate itself becomes the bounded successful command <code>tool_result</code>. |
| Rejected | A normally exited command's candidate bytes, if any, are invalid, over-limit, extra output, or wrong-hash and are discarded. | The adapter writes one <code>rejected</code> object. That host object becomes the bounded non-success command <code>tool_result</code>; it cannot produce the completion text or <code>turn_completed</code>. |
| Failed | No <code>result.json</code> is produced. Any observed path after a nonnormal exit is a forbidden late export, is discarded, and is failure evidence. | The existing bounded host-owned failed lifecycle/terminal evidence represents the execution. No guest candidate is admitted and no successful command <code>tool_result</code> is allowed. |
| Cancelled | No <code>result.json</code> is produced. Any observed path after cancellation is a forbidden late export, is discarded, and is failure evidence. | The existing bounded host-owned cancelled lifecycle/terminal evidence represents the execution. No guest candidate is admitted and no successful command <code>tool_result</code> or later export is allowed. |

## Required negative probes

| Probe ID | Fixed attempt | Pass evidence | Failure evidence |
| --- | --- | --- | --- |
| <code>host_sentinel</code> | Probe the fixed literal <code>/workspace/.portlog-host-sentinel</code>. The guest receives neither a host path nor a canary value. The host creates a fresh actual canary file in its launch/project workspace before the run. Record only a deny code, never canary contents. | The literal probe is denied; the mount record shows no <code>/workspace</code> mount; and the host verifies its actual canary remains unchanged without logging its contents. | The literal is reachable, any <code>/workspace</code> mount is present, the guest receives a host path/value, or the actual canary changes. A VMPI default workspace mount that exposes this literal is a fail. |
| <code>host_env_credentials_config</code> | Enumerate variable **names** only; test names matching <code>PORTLOG_</code>, <code>OPENAI_</code>, <code>ANTHROPIC_</code>, <code>OPENROUTER_</code>, <code>PI_</code>, <code>HOME</code>, and <code>XDG_</code>; attempt <code>/root/.pi</code>, <code>/home/portlog/.pi</code>, <code>/etc/portlog</code>, and the guest's <code>$HOME/.pi</code> without printing data. | Allowlisted guest environment only; no configured credential-canary bytes or hashes in guest process, artifact, PTY capture, or scratch. | A raw provider credential, credential canary, host configuration, user home, or Pi config is exposed. |
| <code>loopback_sidecar</code> | Attempt the fixed, nonsecret literal <code>http://127.0.0.1:8000/api/review/sessions</code>. It is a negative-probe constant, not a passed guest capability, and no session ID or route token is supplied. | Connection is denied/unroutable before a sidecar request; sidecar audit log has no guest-originated request. | Any guest request reaches a PortLog sidecar or returns a domain response. |
| <code>external_network</code> | Attempt one policy-controlled connection to TEST-NET-3 address <code>203.0.113.1:443</code>. Do not resolve DNS or retry. | VM/network policy denies before egress; supervisor records no successful connection. | Any external connection or egress packet is observed. |
| <code>input_mutation</code> | Attempt a write/open-for-append against <code>/review/input/drawing.xml</code>, then close without retry. | Read-only denial and all four host SHA-256 values remain unchanged. | Write succeeds, an overlay changes a file, or any post-run hash differs. |
| <code>output_escape</code> | Attempt a write to <code>/review/escape/escaped-result.json</code> and a rename from scratch into <code>/review/input/escaped-result.json</code>; then, on normal completion, leave the regular completed candidate <code>result.json</code> in scratch. | Both escape attempts are denied; the sole guest candidate pickup is one regular JSON file. Host-owned admission/rejection records are not additional guest exports. The host also rejects any symlink/nonregular result without following it. | A host path changes, a second guest export is admitted, or a symlink/nonregular result is followed. |

The toolchain's own claim that a probe was denied is necessary but not
sufficient. The host's mount, network, sidecar, sentinel, and cleanup evidence
must corroborate it.

The sentinel target is never remapped to an actual host path. If a VMPI default
workspace mount exposes <code>/workspace/.portlog-host-sentinel</code>, record
the scenario as a fail rather than weakening the probe or passing a host path
to the guest.

## Topology execution sequences

### Hybrid: Pi and PortLog domain operations on the host; risky command in guest

1. Electron main resolves the provider credential, starts/supervises the worker
   and local sidecar, and owns cancellation. The credential stays in the host
   worker/host Pi path.
2. The host wrapper starts the normalized record and emits
   <code>turn_started</code>. Host Pi core+AI, unchanged, receives the
   deterministic response stream below <code>createTurn</code>.
3. Pi requests the exact governed check. The worker's bounded callback invokes
   the host sidecar; the sidecar/flow returns the PortLog-owned deterministic
   result and its governed-check artifact.
4. Pi requests the untrusted native command. A host-side command adapter
   launches the guest with the trust boundary above, waits only for the normal
   candidate or terminal evidence, records the host admission/rejection
   decision, and returns the bounded result specified by the outcome table.
5. After an admitted normal candidate, Pi receives the two host-mediated tool
   results, emits the fixed completion text, and the host wrapper emits
   <code>turn_completed</code> and performs its terminal manifest-upsert
   request.

The guest has no PortLog callback, raw provider credential, sidecar endpoint,
or direct path to host Pi. This topology is not a pass until a guest command
adapter proves the artifact-pickup, network, cancellation, and cleanup rules.
Until then its applicable cells are
<code>blocked-by-missing-adapter/protocol</code>, not assumed safe because host
Pi already exists.

### Full guest: Pi and risky command in guest; PortLog capabilities stay host-authorized

1. Electron main retains composition, credential resolution, manifest creation,
   and worker supervision. The host wrapper still starts the record, owns event
   sequence/terminal mapping, and issues manifest-upsert requests.
2. A guest adapter behind <code>createTurn</code> starts unchanged Pi core+AI
   and the same untrusted command toolchain in the guest. It receives the same
   read-only input and ephemeral scratch constraints as Hybrid's command stage.
3. When guest Pi requests the exact governed check, a narrow host-mediation
   protocol validates the request and invokes the existing host callback. The
   guest receives only the bounded PortLog result; it never receives a sidecar
   URL, a project path, rule engine authority, or an artifact-store handle.
4. Guest Pi requests the same native command; the host retrieves and validates
   its sole normal candidate, or retains terminal evidence, exactly as in
   Hybrid.
5. After an admitted normal candidate, guest Pi returns normalized nonterminal
   events through the adapter. The host wrapper, not the guest, emits terminal
   events and completes the manifest-upsert request.

Full guest has an additional hard gate: **no reusable raw provider credential
may be exposed to any guest process**, including Pi, its native children,
scratch, command arguments, mounted files, VM metadata, or telemetry. A
one-turn opaque host authorization or host-mediated model stream is allowed
only if it cannot be reused as a provider credential and every PortLog
capability remains host-authorized. If the prototype lacks that guest-to-host
model/capability bridge, it is
<code>blocked-by-missing-adapter/protocol</code>. Passing the current worker's
raw API key into the guest is a failure, not an implementation shortcut.

## Event model and raw supervisor observations

PortLog structured events and raw VM/PTY/process observations are separate
evidence classes. The wrapper's existing event union is the product record;
VM/PTY text is not.

| Evidence class | Capture | May be used to prove | Must not be used as |
| --- | --- | --- | --- |
| **Structured PortLog record** | <code>LocalInspectionRecord</code>, event sequence/timestamps, posture, bounded tool request/result values, terminal status, deterministic check, and manifest-upsert outcome. | Event ordering, wrapper ownership, deterministic result separation, terminal classification. | Raw guest transcript, credential dump, VM API trace, or alternate persistence record. |
| **Host PortLog artifacts** | Governed-check result-artifact identity, document preparation digest, deterministic result, cache provenance, and manifest record. | Host-authorized capability execution and stable engineering result. | Evidence that the guest reached the sidecar directly. |
| **Raw supervisor ledger** | Guest/child process IDs, monotonic start/end/cancel times, exit/signal/termination, mount-policy summary, network deny decisions, sidecar request count, and at most 4,096 bytes each of redacted VM/PTY stdout/stderr plus their SHA-256 values. | Native process execution, cancellation liveness, network/sidecar denial, and cleanup. | A PortLog tool result or unbounded persisted log. |
| **Command-result evidence** | Normal: the single validated completed guest candidate and its host admission object. Rejected: one bounded host rejection object. Failed/cancelled: only existing host lifecycle/terminal evidence. | Input provenance, native-child report, negative-probe result, scratch accounting, and terminal classification. | Direct authority over host data or a replacement for PortLog's deterministic check. |

For a normal completion, the ordered structured PortLog events must be:

1. <code>turn_started</code>
2. <code>tool_request</code> for <code>portlog_rule_check</code>
3. <code>tool_result</code> for the governed check
4. <code>tool_request</code> for the untrusted native command
5. <code>tool_result</code> for the admitted completed guest candidate
6. one <code>assistant_text_delta</code> containing the fixed completion text
7. <code>turn_completed</code>

There is exactly one terminal event. The raw ledger can show additional
process-level state transitions, but those transitions must never be inserted
into the PortLog event sequence.

A rejected normal-exit candidate uses the host rejection object as the
non-success command <code>tool_result</code> and follows the existing error
terminal mapping; it never proceeds to the completion text or
<code>turn_completed</code>. Failed and cancelled executions use their existing
bounded host-owned lifecycle/terminal evidence rather than a guest artifact.

## One cancellation case and cold retry

Run one cancellation case **once per topology** in addition to its normal
completion case. It uses the same input, exact user request, command toolchain,
PortLog operation, artifact contract, negative probes, and phase name.

1. Let the governed check complete and let the guest native child enter
   <code>native-child-hold</code>.
2. The supervisor observes that stable marker in raw VM/PTY telemetry, waits
   250 ms, and invokes the existing Electron cancellation path.
3. From that cancellation request, the worker, guest, and child must terminate
   within 5,000 ms on the supervisor's monotonic clock.
4. The structured record must end <code>cancelled</code> with exactly one
   <code>turn_cancelled</code> event. It must not emit
   <code>turn_completed</code>, a successful command <code>tool_result</code>,
   a guest <code>result.json</code>, a host admission/rejection object, or a
   later success/export after cancellation.
5. Destroy guest scratch and guest/process state. The surviving evidence is
   bounded to the cancelled record, already-completed governed-check artifact,
   cancellation/termination timestamps, process summaries, input hashes, and
   the raw-ledger digests. Do not persist scratch, a guest artifact, a RAM
   image, a live process, or unbounded PTY text.

The subsequent retry is cold: create fresh worker, guest, Pi process, scratch,
turn ID, and cancellation controller. It may reuse the same immutable input
and frozen scope ID only. This scenario makes no RAM checkpoint, process
checkpoint, guest-memory restoration, or session-recovery claim.

## Shared acceptance matrix

For each cell, record exactly one verdict:

- **pass** — all stated evidence is captured and corroborated.
- **fail** — a prohibited capability, output, credential exposure, ordering
  violation, or lifecycle violation is observed.
- **blocked-by-missing-adapter/protocol** — the topology cannot exercise the
  criterion without adding the needed adapter/control protocol. Do not replace
  it with a host execution or call it not applicable.

At this documentation bead, every execution-dependent cell is initially
<code>blocked-by-missing-adapter/protocol</code>: no guest prototype has run.
Bead <code>.5</code> must replace each initial classification with a captured
pass or fail, or leave it blocked with the precise missing adapter/protocol.

| Criterion | Hybrid classification rule | Full guest classification rule |
| --- | --- | --- |
| Input, mounts, and host sentinel | **pass** only if the guest sees exactly the four read-only files, <code>/review/input</code> and <code>/review/scratch</code> are the only host-provided review paths, <code>/workspace</code> is not mounted, the fixed sentinel literal is denied, the actual host canary remains unchanged, and all before/after input hashes match; **fail** on an extra/writable/host mount (including a VMPI default workspace mount), a reachable sentinel literal, or a changed canary; **blocked-by-missing-adapter/protocol** if mount/sentinel facts cannot be shown. | Same rule and evidence. |
| Native process execution | **pass** only if raw supervisor evidence shows the untrusted toolchain and at least one guest native child with captured termination fields; **fail** if it executes on host; **blocked-by-missing-adapter/protocol** if guest process observations are unavailable. | Same rule, additionally proving Pi and the child ran in the guest rather than host worker. |
| Host capability authorization | **pass** only if the selected governed check is performed by the host sidecar/flow and returns its PortLog-owned deterministic artifact; **fail** if guest code directly executes or substitutes the rule; **blocked-by-missing-adapter/protocol** if host callback wiring is absent. | **pass** only if the guest request passes through a narrow host authorization before the same host operation; **fail** for direct sidecar/rule access; **blocked-by-missing-adapter/protocol** without the guest capability bridge. |
| Credential confinement | **pass** only if the risky guest has no raw provider credential, config, or canary; **fail** on any exposure; **blocked-by-missing-adapter/protocol** if the environment/mount evidence is incomplete. | **pass** only if *no guest process, including Pi,* has a reusable raw provider credential and model access is host-mediated/host-authorized; **fail** if raw key is injected; **blocked-by-missing-adapter/protocol** without a safe model bridge. |
| External network | **pass** only if the TEST-NET-3 attempt is denied before egress; **fail** on any connection/packet; **blocked-by-missing-adapter/protocol** if policy/telemetry cannot demonstrate it. | Same rule and evidence. |
| Loopback sidecar denial | **pass** only if the guest's loopback probe reaches no sidecar route and host audit count is zero; **fail** if any sidecar response/request occurs; **blocked-by-missing-adapter/protocol** if the endpoint cannot be isolated or audited. | Same rule. The authorized capability bridge is not a sidecar exception. |
| Event ordering | **pass** only if the normal and cancellation sequences above are contiguous, monotonic, and each has one terminal event; **fail** on raw VM events in the record, duplicate/late terminal, or late success; **blocked-by-missing-adapter/protocol** if guest output cannot be normalized. | Same rule, with the guest adapter required to translate only nonterminal events. |
| Cancellation | **pass** only if the fixed hold phase is reached, termination takes no more than 5,000 ms, cleanup occurs, the terminal record is cancelled, and no guest <code>result.json</code>, admission/rejection object, successful command <code>tool_result</code>, or late export appears; **fail** on a survivor, completed turn, or any of those outputs; **blocked-by-missing-adapter/protocol** if cancellation cannot reach guest/process. | Same rule, including guest Pi and the command child. |
| Artifact bounds and provenance | **pass** only if a normal command yields one valid completed candidate and host admission object, a rejected candidate yields only the bounded host rejection object with candidate bytes discarded, and failed/cancelled executions yield no guest candidate or successful command <code>tool_result</code>; **fail** on a schema/hash/bounds bypass, extra or late guest export, or guest-artifact status other than <code>completed</code>; **blocked-by-missing-adapter/protocol** if sole-candidate pickup or host terminal evidence is unavailable. | Same rule and exact candidate/admission schema. |
| Persistence and cleanup | **pass** only if wrapper/host manifest data remains within its owner, scratch/guest state is destroyed, and no raw PTY/transcript becomes an alternate store; **fail** on host-mounted scratch or durable guest state; **blocked-by-missing-adapter/protocol** if cleanup cannot be verified. | Same rule, additionally no Pi/OMP/AgentSession persistence in the guest. |
| Reproducibility and cold retry | **pass** only if a new worker/guest/process rerun over the same frozen input/scope produces an equivalent deterministic check and contract-valid artifact with new run IDs; **fail** on checkpoint/process recovery or unexplained divergence; **blocked-by-missing-adapter/protocol** if cold lifecycle cannot be demonstrated. | Same rule and comparison evidence. |

## Evidence-capture checklist for bead .5

Bead <code>.5</code> should capture the following for each topology's normal
and one cancellation case, with secrets redacted and raw values bounded:

- The repository revision, macOS/Apple Silicon architecture, selected guest
  runtime/image identifier, exact command executable SHA-256, and the
  fixture's four file hashes/byte counts.
- The fixture-preparation lookup for <code>P-4713</code>, including the
  frozen prepared-topology <code>source_graph_node_id</code>; no fixture file
  changes.
- Host mount-policy summary and guest-visible file listing showing only the
  permitted review paths and no <code>/workspace</code> mount; host before/after
  hashes for all input files; scratch creation/pickup/destruction evidence.
- For every run, host-side proof that a fresh canary file was created in the
  launch/project workspace, the guest probed only the fixed
  <code>/workspace/.portlog-host-sentinel</code> literal, no host path or canary
  value was passed, the actual canary remained unchanged, and no canary contents
  were logged.
- The exact governed-check request metadata, host deterministic result,
  governed-check result-artifact identity, document preparation digest, and
  cache provenance if any.
- Structured <code>LocalInspectionRecord</code> JSON and ordered events,
  manifest-upsert outcome, and explicit separation from raw supervisor data.
- Raw supervisor process tree/child evidence, start/end/termination fields,
  bounded/redacted PTY data and digests, and the normal candidate
  admission/rejection decision.
- One outcome record for each negative probe, plus host corroboration: fixed
  sentinel literal denied, no <code>/workspace</code> mount, actual canary
  unchanged without logging contents, environment/config/credential scan, zero
  guest sidecar requests, zero external egress, input hashes unchanged, and no
  output escape.
- Full-guest-only proof that no raw provider credential/canary appears in guest
  environment, args, files, scratch, telemetry, or Pi process; if model access
  works, proof that it was host-authorized and one-turn/opaque rather than a
  reusable credential.
- Cancellation marker time, Electron cancellation request time, worker/guest/
  child termination times, final cancelled record, absence of a guest
  <code>result.json</code>, admission/rejection object, successful command
  <code>tool_result</code>, or late export, and the bounded surviving evidence
  list.
- If a command fails, its existing bounded failed lifecycle/terminal evidence,
  absence of a guest <code>result.json</code>, and absence of a successful
  command <code>tool_result</code> or late export.
- A cold retry record showing fresh run IDs/processes/scratch and no RAM or
  process checkpoint recovery.
- For any unimplemented boundary, the exact
  <code>blocked-by-missing-adapter/protocol</code> reason and the minimal
  adapter/protocol it lacks. Do not convert that row into a simulated pass.

This is executable-evidence collection for the unmodified Apple Silicon
prototype, not a promise that the prototype already works.

## Comparison rubric for bead .6

Bead <code>.6</code> may compare the two captured ledgers only after applying
these gates; this document does not pick a winner.

| Comparison question | Required reading of the evidence |
| --- | --- |
| Does either topology protect PortLog? | Any fail in host mount, credential confinement, external network, sidecar denial, output escape, or cancellation cleanup disqualifies it from a protection recommendation. A blocked row remains uncertainty, not a pass. |
| Is the engineering operation equivalent? | Compare the frozen P-4713 scope, governed-check ID/version, deterministic result, ordered topology evidence, and PortLog result-artifact provenance. Model prose and raw PTY text do not decide equivalence. |
| Is full guest meaningfully isolated? | Require proof that Pi and native children are guest processes while the governed check and all PortLog capabilities remain host-authorized; require the no-raw-credential proof. |
| Is hybrid sufficiently contained? | Require proof that only the risky native command is guest-executed while host Pi has no guest-mediated path back to PortLog state. |
| Does lifecycle behavior remain operable? | Compare normal completion, one stable-phase cancellation, prompt termination, terminal mapping, cleanup, and cold retry without checkpoint recovery. |
| What is the integration cost? | Record every blocked adapter/protocol, its ownership boundary, and whether it would widen the settled <code>createTurn</code> seam. Do not treat a speculative workaround as an implementation cost resolved. |

## Explicit deferrals

- **Bead .3:** packaging, image distribution, signing, and packaging-specific
  hardening are deferred. This document specifies the acceptance evidence, not
  how a package is built.
- **Bead .5:** executable proof with the unmodified VMPI prototype on Apple
  Silicon is deferred. No VMPI command was run for this document.
- **Bead .6:** the topology recommendation is deferred. The rubric above
  supplies evidence gates only.
- **Bead .7:** final runtime architecture, adapter design, and any production
  protocol are deferred. This scenario does not create one.
- **Bead .8:** adoption, rollout, migration, and production implementation are
  deferred.

No source, test, fixture, sidecar, adapter, package, or architecture was
changed while producing this representative scenario.
