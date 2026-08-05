# Gondolin VM trigger findings

Bead: `pydexpi-datalog-1-8yli.3`

Date: 2026-08-05

## Summary

The repository has two VM-start paths:

1. The standalone Gondolin spike starts the VM when the CLI invokes the isolated-command executor.
2. The PortLog Pi review flow starts the VM when Pi calls the `portlog_isolated_command` tool.

The second path is strongly instructed by the review prompt, but the host does not yet enforce that every review turn actually made the expected isolated-command call.

## Standalone spike trigger

Running the following command is the trigger:

```bash
npm run prototype:gondolin -- --scenario candidate
```

The call chain is:

```text
CLI main()
  -> createRequest(...)
  -> createGondolinQemuExecutor(...)
  -> executor.runIsolatedCommand(request)
  -> VM.create(...)
  -> vm.exec(plan.command)
```

Relevant implementation:

- `frontend/desktop/gondolin-spike.ts:63-81` constructs the request and invokes the executor.
- `frontend/desktop/gondolin-qemu.ts:142-163` maps the requested profile to a fixed command plan.
- `frontend/desktop/gondolin-qemu.ts:195-224` validates QEMU, stages the immutable input, and creates the disposable QEMU/HVF VM.
- `frontend/desktop/gondolin-qemu.ts:233-238` executes the fixed command inside the guest.

Constructing the executor alone does not start a VM. VM creation occurs only after profile, cancellation, platform, QEMU-path, and input-staging checks succeed.

## Pi review trigger

The production review path is gated as follows:

- `local-inspection-worker.ts:96-102` enables the Gondolin executor only for `posture === "review"` and an executable QEMU path.
- `capability-routing.ts:37-47` exposes isolated execution only for a prepared review in review posture.
- `pi-turn-adapter.ts:131-168` registers the `portlog_isolated_command` tool when that callback is available.
- `pi-turn-adapter.ts:141-157` invokes the host callback when Pi calls the tool.
- `local-inspection-worker.ts:103-120` builds the isolated-command request and calls the Gondolin executor.
- The executor then reaches `VM.create(...)` and `vm.exec(...)` as described above.

Therefore the current Pi-trigger sequence is:

```text
Prepared review request with review posture
  -> isolated-command tool becomes available
  -> Pi selects/calls portlog_isolated_command
  -> host callback invokes runIsolatedCommand
  -> Gondolin VM is created
  -> fixed approved guest command executes
```

If the posture is chat or inspect, if the review is not prepared, or if QEMU is unavailable, the isolated-command tool is not registered and no VM starts.

## Model discretion versus host enforcement

The current implementation is not pure model discretion, because the host applies hard gates and the review prompt gives an explicit sequence:

1. Call `portlog_evidence`.
2. Call `portlog_rule_check`.
3. Call `portlog_isolated_command` with `profileId` `review-bundle-candidate`.

That instruction is in `frontend/desktop/local-review-inspection.ts:370-377`.

However, the prompt is not a host-enforced state machine. The model can technically omit the isolated-command call or request another approved profile. The tool validates that `profileId` is a non-empty string, and the executor rejects unknown profiles, but the current worker does not force the profile to be exactly `review-bundle-candidate`.

The current boundary is:

```text
Host-enforced:
  review/prepared/QEMU availability gates
  approved profile validation
  fixed command plans
  guest isolation policy
  cancellation and resource limits
  no host fallback

Model-selected:
  whether to call the isolated-command tool
  when to call it
  which approved profile to request
```

## Follow-up implication

If every E06 review must execute the candidate command, the host-owned review coordinator should record an expected isolated-command obligation and mark the turn incomplete or failed unless the matching tool result is observed. The invariant should also require the exact expected profile, rather than relying only on the model prompt.

The current implementation is suitable for the prototype and demonstrates the execution seam, but it should not yet be described as a mandatory VM execution guarantee for every review turn.
