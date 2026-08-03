import { createHash } from "node:crypto";
import { access, constants } from "node:fs/promises";
import { isAbsolute } from "node:path";

import { MemoryProvider, ReadonlyProvider, VM, type VMOptions } from "@earendil-works/gondolin";

import {
  MAX_ISOLATED_COMMAND_DIAGNOSTIC_LENGTH,
  type ApprovedCommandProfile,
  type ImmutableInputBundle,
  type IsolatedCommandArtifactIdentity,
  type IsolatedCommandBackendIdentity,
  type IsolatedCommandCandidate,
  type IsolatedCommandContentIdentity,
  type IsolatedCommandExecutor,
  type IsolatedCommandProvenance,
  type IsolatedCommandResult,
} from "./isolated-command.ts";

export const GONDOLIN_QEMU_PROFILE: ApprovedCommandProfile = Object.freeze({
  id: "native-child-echo",
  version: "1",
});

export const GONDOLIN_REVIEW_CANDIDATE_PROFILE: ApprovedCommandProfile = Object.freeze({
  id: "review-bundle-candidate",
  version: "1",
});

export const GONDOLIN_CONFINEMENT_PROFILE: ApprovedCommandProfile = Object.freeze({
  id: "confinement-probes",
  version: "1",
});

export const GONDOLIN_CANCELLATION_PROFILE: ApprovedCommandProfile = Object.freeze({
  id: "native-child-hold",
  version: "1",
});

export const GONDOLIN_QEMU_BACKEND: IsolatedCommandBackendIdentity = Object.freeze({
  id: "gondolin-qemu-hvf",
  version: "0.10.0",
});

const GONDOLIN_QEMU_IMAGE: IsolatedCommandContentIdentity = Object.freeze({
  id: "alpine-base",
  digest: "builtin:alpine-base",
});
const GONDOLIN_QEMU_POLICY: IsolatedCommandContentIdentity = Object.freeze({
  id: "qemu-hvf-deny-all",
  digest: "builtin:qemu-hvf-deny-all",
});
const NATIVE_CHILD_MARKER = "portlog-native-child";
const NATIVE_CHILD_COMMAND = ["/bin/sh", "-c", `/bin/echo ${NATIVE_CHILD_MARKER}`];
const CONFINEMENT_MARKER = "confinement-probes-passed";
const CONFINEMENT_COMMAND = [
  "/bin/sh",
  "-c",
  [
    "set -eu",
    "test -x /bin/busybox",
    "/bin/busybox wget --help >/dev/null 2>&1",
    'probe() { if /bin/busybox wget -T 1 -q -O /dev/null "$1" 2>/dev/null; then exit 20; fi; }',
    'probe "http://127.0.0.1:8000/api/review/sessions"',
    'probe "http://10.0.2.2:8000/portlog-undeclared-host-service"',
    'probe "http://203.0.113.1:443"',
    "test ! -e /workspace/.portlog-host-sentinel",
    "test ! -e /root/.pi",
    "test ! -e /home/portlog/.pi",
    "test ! -e /etc/portlog",
    "if /bin/busybox env | /bin/busybox grep -Eq '^(PORTLOG_|OPENAI_|ANTHROPIC_|OPENROUTER_|PI_)'; then exit 21; fi",
    `printf '%s' '${CONFINEMENT_MARKER}'`,
  ].join("\n"),
];
const CANCELLATION_COMMAND = ["/bin/sh", "-c", "/bin/sleep 300"];
const VALID_CANDIDATE_JSON =
  '{"schemaVersion":1,"status":"ok","message":"review bundle inspected"}';
const REVIEW_CANDIDATE_COMMAND = [
  "/bin/sh",
  "-c",
  [
    "set -eu",
    "test -f /review/input/review.json",
    "cat /review/input/review.json >/dev/null",
    "if printf 'mutation' > /review/input/review.json 2>/dev/null; then exit 42; fi",
    `printf '%s' '${VALID_CANDIDATE_JSON}' > /review/scratch/result.json`,
  ].join("\n"),
];
const DEFAULT_MAX_INPUT_FILES = 16;
const DEFAULT_MAX_INPUT_BYTES = 4 * 1024 * 1024;

export interface GondolinVm {
  exec(
    command: string | string[],
    options?: {
      signal?: AbortSignal;
      pty?: boolean;
      stdout?: "buffer";
      stderr?: "buffer";
    },
  ): PromiseLike<{ exitCode: number; stdout: string }>;
  close(): Promise<void>;
}

type CreateGondolinVm = (options: VMOptions) => Promise<GondolinVm>;
type CommandPlan = {
  command: string[];
  candidate: boolean;
  marker?: string;
  hold?: boolean;
};
type TimeoutHandle = NodeJS.Timeout;
type CandidateAdmission =
  | {
      accepted: true;
      candidate: IsolatedCommandCandidate;
      artifact: IsolatedCommandArtifactIdentity;
    }
  | { accepted: false; diagnostic: string };

export interface GondolinQemuExecutorOptions {
  readonly qemuPath: string;
  readonly imagePath?: string;
  readonly now?: () => Date;
  readonly createVm?: CreateGondolinVm;
}

/**
 * Creates the development-only QEMU/HVF implementation behind the stable
 * isolated-command interface. The caller must provide an absolute QEMU path;
 * this adapter never discovers or invokes a host executable through PATH.
 */
export function createGondolinQemuExecutor(
  options: GondolinQemuExecutorOptions,
): IsolatedCommandExecutor {
  const now = options.now ?? (() => new Date());
  const createVm = options.createVm ?? ((vmOptions: VMOptions) => VM.create(vmOptions));

  return {
    async runIsolatedCommand(request): Promise<IsolatedCommandResult> {
      const startedAt = now();
      const plan: CommandPlan | undefined =
        request.commandProfile.id === GONDOLIN_QEMU_PROFILE.id &&
        request.commandProfile.version === GONDOLIN_QEMU_PROFILE.version
          ? {
              command: NATIVE_CHILD_COMMAND,
              candidate: false,
              marker: NATIVE_CHILD_MARKER,
            }
          : request.commandProfile.id === GONDOLIN_REVIEW_CANDIDATE_PROFILE.id &&
              request.commandProfile.version === GONDOLIN_REVIEW_CANDIDATE_PROFILE.version
            ? { command: REVIEW_CANDIDATE_COMMAND, candidate: true }
            : request.commandProfile.id === GONDOLIN_CONFINEMENT_PROFILE.id &&
                request.commandProfile.version === GONDOLIN_CONFINEMENT_PROFILE.version
              ? {
                  command: CONFINEMENT_COMMAND,
                  candidate: false,
                  marker: CONFINEMENT_MARKER,
                }
              : request.commandProfile.id === GONDOLIN_CANCELLATION_PROFILE.id &&
                  request.commandProfile.version === GONDOLIN_CANCELLATION_PROFILE.version
                ? { command: CANCELLATION_COMMAND, candidate: false, hold: true }
                : undefined;
      let outcome: IsolatedCommandResult["outcome"] = "unavailable";
      let diagnostic = "Gondolin QEMU/HVF is unavailable.";
      let exitCode: number | undefined;
      let candidate: IsolatedCommandCandidate | undefined;
      let artifact: IsolatedCommandArtifactIdentity | undefined;
      let vm: GondolinVm | undefined;
      let readOnlyInput: ReadonlyProvider | undefined;
      let timedOut = false;
      let timeoutId: TimeoutHandle | undefined;
      let onAbort: (() => void) | undefined;

      if (!plan) {
        outcome = "rejected";
        diagnostic = "The requested command profile is not approved.";
      } else if (request.signal.aborted) {
        outcome = "cancelled";
        diagnostic = "Isolated command was cancelled.";
      } else if (process.platform !== "darwin" || process.arch !== "arm64") {
        diagnostic = "Gondolin QEMU/HVF requires an arm64 macOS host.";
      } else if (!isAbsolute(options.qemuPath)) {
        diagnostic = "Gondolin QEMU/HVF requires an absolute QEMU path.";
      } else {
        const executionController = new AbortController();
        onAbort = () => executionController.abort();
        request.signal.addEventListener("abort", onAbort, { once: true });
        const maxDurationMs = Math.max(0, request.limits.maxDurationMs);
        timeoutId = setTimeout(() => {
          timedOut = true;
          executionController.abort();
        }, maxDurationMs);
        try {
          await access(options.qemuPath, constants.X_OK);
          const input = await buildReadonlyInputProvider(
            request.inputBundle,
            request.limits.maxInputFiles ?? DEFAULT_MAX_INPUT_FILES,
            request.limits.maxInputBytes ?? DEFAULT_MAX_INPUT_BYTES,
          );
          readOnlyInput = new ReadonlyProvider(input);
          const scratch = new MemoryProvider();
          vm = await createVm({
            sandbox: {
              vmm: "qemu",
              qemuPath: options.qemuPath,
              accel: "hvf",
              machineType: "virt",
              memory: "2G",
              cpus: 1,
              imagePath: options.imagePath ?? "alpine-base",
              netEnabled: false,
              console: "none",
              autoRestart: false,
            },
            rootfs: { mode: "memory" },
            vfs: {
              mounts: {
                "/review/input": readOnlyInput,
                "/review/scratch": scratch,
              },
            },
            env: [],
          });

          if (request.signal.aborted) {
            outcome = "cancelled";
            diagnostic = "Isolated command was cancelled.";
          } else if (timedOut) {
            outcome = "timed_out";
            diagnostic = "Isolated command timed out.";
          } else {
            const execution = await vm.exec(plan.command, {
              signal: executionController.signal,
              pty: false,
              stdout: "buffer",
              stderr: "buffer",
            });
            exitCode = execution.exitCode;
            if (request.signal.aborted) {
              outcome = "cancelled";
              diagnostic = "Isolated command was cancelled.";
              exitCode = undefined;
            } else if (timedOut) {
              outcome = "timed_out";
              diagnostic = "Isolated command timed out.";
              exitCode = undefined;
            } else if (execution.exitCode !== 0) {
              outcome = "failed";
              diagnostic = plan.candidate
                ? `Review candidate command failed with exit code ${execution.exitCode}.`
                : `Native guest command failed with exit code ${execution.exitCode}.`;
            } else if (plan.marker && execution.stdout.trim() !== plan.marker) {
              outcome = "failed";
              diagnostic = "Approved guest command did not return its expected marker.";
            } else if (plan.candidate) {
              const admission = await admitScratchCandidate(scratch, request.limits.maxOutputBytes);
              if (request.signal.aborted) {
                outcome = "cancelled";
                diagnostic = "Isolated command was cancelled.";
                exitCode = undefined;
              } else if (timedOut) {
                outcome = "timed_out";
                diagnostic = "Isolated command timed out.";
                exitCode = undefined;
              } else if (admission.accepted) {
                outcome = "admitted";
                diagnostic = "Review candidate admitted.";
                candidate = admission.candidate;
                artifact = admission.artifact;
              } else {
                outcome = "rejected";
                diagnostic = admission.diagnostic;
                exitCode = undefined;
              }
            } else {
              outcome = "admitted";
              diagnostic = plan.hold
                ? "Native guest hold completed."
                : "Native guest child completed.";
            }
          }
        } catch {
          if (request.signal.aborted) {
            outcome = "cancelled";
            diagnostic = "Isolated command was cancelled.";
            exitCode = undefined;
          } else if (timedOut) {
            outcome = "timed_out";
            diagnostic = "Isolated command timed out.";
            exitCode = undefined;
          } else if (vm) {
            outcome = "failed";
            diagnostic = "Native guest command failed.";
          } else {
            outcome = "unavailable";
            diagnostic = "Gondolin QEMU/HVF could not start.";
          }
        } finally {
          clearTimeout(timeoutId);
          if (onAbort) request.signal.removeEventListener("abort", onAbort);
          if (vm) {
            try {
              await vm.close();
            } catch {
              if (outcome === "admitted") {
                outcome = "failed";
                diagnostic = "Native guest completed but could not close.";
                exitCode = undefined;
                candidate = undefined;
                artifact = undefined;
              }
            }
          }
          if (readOnlyInput) {
            try {
              await readOnlyInput.close();
            } catch {
              if (outcome === "admitted") {
                outcome = "failed";
                diagnostic = "Review input could not be released.";
                exitCode = undefined;
                candidate = undefined;
                artifact = undefined;
              }
            }
          }
        }
      }

      const completedAt = now();
      const provenance: IsolatedCommandProvenance = {
        runId: request.runId,
        backend: GONDOLIN_QEMU_BACKEND,
        image: GONDOLIN_QEMU_IMAGE,
        policy: GONDOLIN_QEMU_POLICY,
        commandProfile: request.commandProfile,
        startedAt: startedAt.toISOString(),
        completedAt: completedAt.toISOString(),
        durationMs: Math.max(0, completedAt.getTime() - startedAt.getTime()),
        outcome,
        ...(artifact ? { artifact } : {}),
      };
      const boundedDiagnostic = diagnostic.slice(0, MAX_ISOLATED_COMMAND_DIAGNOSTIC_LENGTH);

      if (outcome === "admitted") {
        return {
          outcome,
          diagnostic: boundedDiagnostic,
          provenance,
          exitCode: exitCode ?? 0,
          ...(candidate ? { candidate } : {}),
        };
      }
      return {
        outcome,
        diagnostic: boundedDiagnostic,
        provenance,
        ...(exitCode === undefined ? {} : { exitCode }),
      };
    },
  };
}

async function buildReadonlyInputProvider(
  bundle: ImmutableInputBundle,
  maxFiles: number,
  maxBytes: number,
): Promise<MemoryProvider> {
  if (bundle.files.length > maxFiles) throw new Error("Too many input files");
  let totalBytes = 0;
  const paths = new Set<string>();
  const createdDirectories = new Set<string>();
  const provider = new MemoryProvider();

  for (const file of bundle.files) {
    const segments = file.relativePath.split("/");
    if (
      !file.relativePath ||
      file.relativePath.startsWith("/") ||
      file.relativePath.includes("\\") ||
      segments.some((segment) => !segment || segment === "." || segment === "..")
    ) {
      throw new Error("Invalid input path");
    }
    const guestPath = `/${file.relativePath}`;
    if (paths.has(guestPath)) throw new Error("Duplicate input path");
    paths.add(guestPath);
    totalBytes += file.bytes.byteLength;
    if (totalBytes > maxBytes) throw new Error("Input bundle is too large");

    let directory = "";
    for (const segment of segments.slice(0, -1)) {
      directory += `/${segment}`;
      if (!createdDirectories.has(directory)) {
        await provider.mkdir(directory);
        createdDirectories.add(directory);
      }
    }
    if (!provider.writeFile) throw new Error("Memory provider cannot write files");
    await provider.writeFile(guestPath, Buffer.from(file.bytes));
  }
  provider.setReadOnly();
  return provider;
}

async function admitScratchCandidate(
  scratch: MemoryProvider,
  maxBytes: number,
): Promise<CandidateAdmission> {
  if (!scratch.readdir || !scratch.stat || !scratch.readFile) {
    return { accepted: false, diagnostic: "Scratch output cannot be inspected." };
  }
  const files: string[] = [];
  const directories = ["/"];
  while (directories.length) {
    const directory = directories.pop()!;
    for (const entry of await scratch.readdir(directory)) {
      const name = typeof entry === "string" ? entry : entry.name;
      const path = directory === "/" ? `/${name}` : `${directory}/${name}`;
      const stats = await scratch.stat(path);
      if (stats.isDirectory()) directories.push(path);
      else files.push(path);
    }
  }
  if (files.length !== 1 || files[0] !== "/result.json") {
    return { accepted: false, diagnostic: "Expected exactly one result.json candidate." };
  }

  const raw = await scratch.readFile("/result.json");
  const bytes = Buffer.isBuffer(raw) ? raw : Buffer.from(raw);
  if (bytes.byteLength > maxBytes) {
    return { accepted: false, diagnostic: "The result candidate exceeds the byte bound." };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(bytes.toString("utf8"));
  } catch {
    return { accepted: false, diagnostic: "The result candidate is malformed JSON." };
  }
  if (
    !parsed ||
    typeof parsed !== "object" ||
    Array.isArray(parsed) ||
    Object.keys(parsed).sort().join(",") !== "message,schemaVersion,status" ||
    (parsed as Record<string, unknown>).schemaVersion !== 1 ||
    (parsed as Record<string, unknown>).status !== "ok" ||
    typeof (parsed as Record<string, unknown>).message !== "string"
  ) {
    return { accepted: false, diagnostic: "The result candidate does not match its schema." };
  }

  return {
    accepted: true,
    candidate: parsed as IsolatedCommandCandidate,
    artifact: {
      id: "result.json",
      digest: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
      byteLength: bytes.byteLength,
    },
  };
}
