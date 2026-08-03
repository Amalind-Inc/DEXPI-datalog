# Unmodified VMPI Apple Silicon prototype

Bead: `pydexpi-datalog-1-23bh.5`

## Answer

Unmodified `@the-agency/vmpi` 0.4.1 can set up, boot, and run Pi and native child processes on the target Apple Silicon workstation when raised from its default 512 MiB to 2 GiB. It also enforces the configured deny-all network policy in the probes and stops a running guest command promptly on cancellation.

It does **not** implement the representative PortLog isolation contract. VMPI always exposes the host current directory read-write as `/workspace`, exposes a snapshot of the host-selected Pi configuration as `/root/.pi`, and copies sessions back to the host when sessions are enabled. A guest command read a host-only sentinel and created result files directly in the host workspace. Configured secrets are written into the guest and sourced into the Pi process, so a reusable provider credential would be guest-readable. There is no bounded PortLog capability, artifact-export, event, or terminal-result protocol in unmodified VMPI.

This is evidence for the architecture comparison, not the final Hybrid-versus-Full-guest choice.

## Frozen environment

- Host: Apple Silicon (`arm64`), macOS 26.5.2 (25F84).
- Runtime: Node 26.5.0, npm 11.10.1.
- Prototype package: `@the-agency/vmpi@0.4.1` with `@earendil-works/gondolin@0.10.0`.
- Guest agent installed by VMPI setup: Pi 0.83.0.
- QEMU: 11.0.3, installed through Homebrew for this prototype.
- Review input: a disposable copy of the checked-in E06 representative bundle. Its four original file hashes were checked before and after the run and remained unchanged.
- Model boundary: a deterministic, OpenAI-compatible host stub exposed through VMPI's documented `network.localServices`; no real provider credential was used.

VMPI documents macOS/aarch64 as untested. These results therefore establish behavior only on this workstation and frozen package set.

## What ran

`vmpi setup --debug` completed and produced a reusable checkpoint. The first unchanged run at VMPI's default 512 MiB reached guest resume but failed while extracting Pi with `No space left on device`. Repeating the package with documented `VMPI_MEMORY=2048` succeeded.

The deterministic Pi run used only Pi's Bash tool. In the guest it:

1. confirmed its working directory was `/workspace`;
2. enumerated the mounted workspace;
3. read a fresh host-only sentinel;
4. spawned a native Python child process;
5. attempted external and loopback network access;
6. wrote a small JSON result and probe evidence files.

Pi completed with exit status 0 and the deterministic model received the initial request and tool-result continuation.

## Scenario result matrix

| Representative requirement | Result | Evidence |
| --- | --- | --- |
| Boot on packaged-target Apple Silicon | Pass with qualification | Setup, checkpoint resume, Pi launch, and native child execution succeeded at 2 GiB. Default 512 MiB failed. This was a development install, not an Electron package/signing/notarization test. |
| Receive only uploaded input | Fail | The guest saw the whole host current directory through fixed `/workspace`, including `.vmpirc.json` and a fresh host-only sentinel. |
| Read-only review input | Fail | `/workspace` is a `RealFSProvider` mounted read-write. Original inputs happened to remain unchanged, but the guest had mutation authority and created new host files directly. |
| Ephemeral scratch | Blocked/missing | Unmodified VMPI provides no PortLog-shaped `/review/scratch` lifecycle. Guest writes to `/workspace` survive immediately on the host. |
| Bounded sole result artifact | Fail | The guest can create arbitrary files in the host workspace; there is no allowlisted export or size/count boundary. Session state is also merged back when enabled. |
| No PortLog project or host filesystem access | Fail | The sentinel was readable and copied byte-for-byte from the host workspace. VMPI intentionally mounts the current directory. |
| No ambient configuration | Fail | VMPI snapshots the selected host Pi config and mounts it at `/root/.pi`. The prototype used a clean, non-secret temporary config, but the capability is present. |
| No reusable raw credential in guest | Fail for Full guest | VMPI writes configured secrets to `/tmp/.vmpi-secrets` and sources them into the guest Pi process. No real secret was used in the prototype. |
| No sidecar access | Partial | Guest attempts to `127.0.0.1:8000` failed. No real PortLog sidecar was exposed, so this does not prove denial of every host-service configuration. |
| No unrestricted network | Pass for observed policy behavior | With explicit `deny-all`, the external request failed while the single declared local model service worked. This is guest/application-level evidence, not a packet-capture audit. |
| Native process execution | Pass | Pi's Bash tool spawned a Python subprocess and captured `native-child-ok`. |
| Structured observability | Partial/missing PortLog protocol | Pi JSON mode emitted machine-readable events, but VMPI also owns a human-oriented PTY/lifecycle stream. It supplies no bounded PortLog event schema, correlation contract, or normalized terminal-result adapter. |
| Cancellation | Pass for process stop; adapter blocked | Ctrl-C during a stable `sleep 300` path returned exit 130 promptly, no late-success marker appeared, and no VMPI/Gondolin process remained. Mapping that into PortLog's normalized terminal record still requires an adapter. |
| Cold retry / artifact retention | Partial | Checkpoint reuse supports a cold guest restart. Host workspace writes and optional session copy-back survive outside a bounded result contract, which is the wrong retention model for this scenario. |
| Governed PortLog pump check | Blocked/missing | Unmodified VMPI has no host-authorized PortLog capability bridge, so the same governed operation could not be invoked without adding the very adapter the later comparison must evaluate. |

## Source-confirmed boundaries

The executable package agrees with the runtime observations:

- VMPI reserves `/workspace` and `/root/.pi`; user mounts cannot replace them.
- `/workspace` maps to `new RealFSProvider(process.cwd())`.
- the configured Pi directory is copied to a temporary snapshot before guest launch;
- configured secret values are written to `/tmp/.vmpi-secrets`, then sourced before `pi` starts;
- Pi runs under an attached PTY after `cd /workspace`;
- session data is collected back into the host workspace/session location after execution;
- absent allowed domains, network policy resolves to deny-all; declared local services use a host TCP tunnel.

These are product semantics, not merely defects in the throwaway harness.

## Implications for the next comparison

Unmodified VMPI is useful evidence that the Gondolin/QEMU execution substrate works on this Apple Silicon machine and can confine network access. It is not a drop-in PortLog worker boundary.

- A **Hybrid** path can keep Pi and PortLog authorization on the host, but risky execution needs a thinner guest interface than VMPI's fixed host-workspace mount.
- A **Full guest** path additionally needs host-mediated model access that never reveals a reusable provider credential, plus host-authorized PortLog capability calls and bounded artifact/event bridges. Unmodified VMPI supplies none of those contracts.

The next bead should compare the adapter depth and regression radius of those two paths, using Gondolin directly or an upstreamable VMPI extension where the fixed VMPI semantics block the scenario.

## Host and temporary effects

Homebrew QEMU 11.0.3 remains installed on the workstation and can be removed with `brew uninstall qemu` if it is no longer needed. The prototype used only disposable state under `/private/tmp`; it did not expose real PortLog credentials, the real project directory, or a real sidecar to the guest.
