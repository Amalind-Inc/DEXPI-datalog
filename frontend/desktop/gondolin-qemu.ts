import { access, constants } from "node:fs/promises";
import { isAbsolute } from "node:path";

import { VM, type VMOptions } from "@earendil-works/gondolin";

import {
  MAX_ISOLATED_COMMAND_DIAGNOSTIC_LENGTH,
  type ApprovedCommandProfile,
  type IsolatedCommandBackendIdentity,
  type IsolatedCommandContentIdentity,
  type IsolatedCommandExecutor,
  type IsolatedCommandResult,
} from "./isolated-command.ts";

export const GONDOLIN_QEMU_PROFILE: ApprovedCommandProfile = Object.freeze({
  id: "native-child-echo",
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
      let outcome: IsolatedCommandResult["outcome"] = "unavailable";
      let diagnostic = "Gondolin QEMU/HVF is unavailable.";
      let exitCode: number | undefined;
      let vm: GondolinVm | undefined;

      if (request.commandProfile.id !== GONDOLIN_QEMU_PROFILE.id) {
        outcome = "rejected";
        diagnostic = "The requested command profile is not approved.";
      } else if (request.commandProfile.version !== GONDOLIN_QEMU_PROFILE.version) {
        outcome = "rejected";
        diagnostic = "The requested command profile version is not approved.";
      } else if (request.signal.aborted) {
        outcome = "cancelled";
        diagnostic = "Isolated command was cancelled.";
      } else if (process.platform !== "darwin" || process.arch !== "arm64") {
        diagnostic = "Gondolin QEMU/HVF requires an arm64 macOS host.";
      } else if (!isAbsolute(options.qemuPath)) {
        diagnostic = "Gondolin QEMU/HVF requires an absolute QEMU path.";
      } else {
        try {
          await access(options.qemuPath, constants.X_OK);
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
            vfs: null,
            env: [],
          });

          if (request.signal.aborted) {
            outcome = "cancelled";
            diagnostic = "Isolated command was cancelled.";
          } else {
            const execution = await vm.exec(NATIVE_CHILD_COMMAND, {
              signal: request.signal,
              pty: false,
              stdout: "buffer",
              stderr: "buffer",
            });
            exitCode = execution.exitCode;
            if (request.signal.aborted) {
              outcome = "cancelled";
              diagnostic = "Isolated command was cancelled.";
              exitCode = undefined;
            } else if (execution.exitCode !== 0) {
              outcome = "failed";
              diagnostic = `Native guest command failed with exit code ${execution.exitCode}.`;
            } else if (execution.stdout.trim() !== NATIVE_CHILD_MARKER) {
              outcome = "failed";
              diagnostic = "Native guest child output was not observed.";
            } else {
              outcome = "admitted";
              diagnostic = "Native guest child completed.";
            }
          }
        } catch {
          if (request.signal.aborted) {
            outcome = "cancelled";
            diagnostic = "Isolated command was cancelled.";
            exitCode = undefined;
          } else if (vm) {
            outcome = "failed";
            diagnostic = "Native guest command failed.";
          } else {
            outcome = "unavailable";
            diagnostic = "Gondolin QEMU/HVF could not start.";
          }
        } finally {
          if (vm) {
            try {
              await vm.close();
            } catch {
              if (outcome === "admitted") {
                outcome = "failed";
                diagnostic = "Native guest completed but could not close.";
                exitCode = undefined;
              }
            }
          }
        }
      }

      const completedAt = now();
      const provenance = {
        runId: request.runId,
        backend: GONDOLIN_QEMU_BACKEND,
        image: GONDOLIN_QEMU_IMAGE,
        policy: GONDOLIN_QEMU_POLICY,
        commandProfile: request.commandProfile,
        startedAt: startedAt.toISOString(),
        completedAt: completedAt.toISOString(),
        durationMs: Math.max(0, completedAt.getTime() - startedAt.getTime()),
        outcome,
      };
      const boundedDiagnostic = diagnostic.slice(0, MAX_ISOLATED_COMMAND_DIAGNOSTIC_LENGTH);

      if (outcome === "admitted") {
        return { outcome, diagnostic: boundedDiagnostic, provenance, exitCode: exitCode ?? 0 };
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
