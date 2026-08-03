export const MAX_ISOLATED_COMMAND_DIAGNOSTIC_LENGTH = 240;

export type IsolatedCommandOutcome =
  | "admitted"
  | "rejected"
  | "unavailable"
  | "failed"
  | "timed_out"
  | "cancelled";

export interface ImmutableInputFile {
  readonly relativePath: string;
  readonly bytes: Readonly<Uint8Array>;
  readonly digest: string;
}

export interface ImmutableInputBundle {
  readonly bundleId: string;
  readonly digest: string;
  readonly files: readonly ImmutableInputFile[];
}

export interface ApprovedCommandProfile {
  readonly id: string;
  readonly version: string;
}

export interface IsolatedCommandLimits {
  readonly maxDurationMs: number;
  readonly maxMemoryBytes: number;
  readonly maxCpuSeconds: number;
  readonly maxScratchBytes: number;
  readonly maxOutputCount: number;
  readonly maxOutputBytes: number;
  readonly maxInputFiles?: number;
  readonly maxInputBytes?: number;
}

export interface IsolatedCommandRequest {
  readonly runId: string;
  readonly inputBundle: ImmutableInputBundle;
  readonly commandProfile: ApprovedCommandProfile;
  readonly limits: IsolatedCommandLimits;
  readonly signal: AbortSignal;
}

export interface IsolatedCommandBackendIdentity {
  readonly id: string;
  readonly version: string;
}

export interface IsolatedCommandContentIdentity {
  readonly id: string;
  readonly digest: string;
}

export interface IsolatedCommandArtifactIdentity extends IsolatedCommandContentIdentity {
  readonly byteLength: number;
}
export interface IsolatedCommandCandidate {
  readonly schemaVersion: 1;
  readonly status: "ok";
  readonly message: string;
}

export interface IsolatedCommandProvenance {
  readonly runId: string;
  readonly backend: IsolatedCommandBackendIdentity;
  readonly image: IsolatedCommandContentIdentity;
  readonly policy: IsolatedCommandContentIdentity;
  readonly commandProfile: ApprovedCommandProfile;
  readonly startedAt: string;
  readonly completedAt: string;
  readonly durationMs: number;
  readonly outcome: IsolatedCommandOutcome;
  readonly artifact?: IsolatedCommandArtifactIdentity;
}

interface IsolatedCommandResultBase {
  readonly diagnostic: string;
  readonly provenance: IsolatedCommandProvenance;
  readonly exitCode?: number;
}

export type IsolatedCommandResult =
  | (IsolatedCommandResultBase & {
      readonly outcome: "admitted";
      readonly exitCode: number;
      readonly candidate?: IsolatedCommandCandidate;
    })
  | (IsolatedCommandResultBase & {
      readonly outcome: Exclude<IsolatedCommandOutcome, "admitted">;
    });

export interface IsolatedCommandExecutor {
  runIsolatedCommand(request: IsolatedCommandRequest): Promise<IsolatedCommandResult>;
}

export type RunIsolatedCommand = IsolatedCommandExecutor["runIsolatedCommand"];

export interface InMemoryIsolatedCommandExecutorOptions {
  readonly outcome?: IsolatedCommandOutcome;
  readonly diagnostic?: string;
  readonly exitCode?: number;
  readonly backend?: IsolatedCommandBackendIdentity;
  readonly image?: IsolatedCommandContentIdentity;
  readonly policy?: IsolatedCommandContentIdentity;
  readonly artifact?: IsolatedCommandArtifactIdentity;
  readonly candidate?: IsolatedCommandCandidate;
  readonly now?: () => Date;
}

const DEFAULT_BACKEND: IsolatedCommandBackendIdentity = {
  id: "in-memory-conformance",
  version: "1",
};
const DEFAULT_IMAGE: IsolatedCommandContentIdentity = {
  id: "conformance-image",
  digest: "sha256:conformance-image",
};
const DEFAULT_POLICY: IsolatedCommandContentIdentity = {
  id: "conformance-policy",
  digest: "sha256:conformance-policy",
};
const DEFAULT_DIAGNOSTICS: Record<IsolatedCommandOutcome, string> = {
  admitted: "Isolated command completed.",
  rejected: "Isolated command was rejected.",
  unavailable: "Isolated command execution is unavailable.",
  failed: "Isolated command failed.",
  timed_out: "Isolated command timed out.",
  cancelled: "Isolated command was cancelled.",
};

/**
 * Returns a conformance-only executor for testing callers of the interface.
 * This implementation models result and cancellation semantics in memory; it
 * does not provide isolation and must not be used as a runtime fallback.
 */
export function createInMemoryIsolatedCommandExecutor(
  options: InMemoryIsolatedCommandExecutorOptions = {},
): IsolatedCommandExecutor {
  const now = options.now ?? (() => new Date());
  const backend = options.backend ?? DEFAULT_BACKEND;
  const image = options.image ?? DEFAULT_IMAGE;
  const policy = options.policy ?? DEFAULT_POLICY;

  return {
    async runIsolatedCommand(request) {
      const startedAt = now();
      const outcome = request.signal.aborted ? "cancelled" : (options.outcome ?? "admitted");
      const completedAt = now();
      const provenance: IsolatedCommandProvenance = {
        runId: request.runId,
        backend,
        image,
        policy,
        commandProfile: request.commandProfile,
        startedAt: startedAt.toISOString(),
        completedAt: completedAt.toISOString(),
        durationMs: Math.max(0, completedAt.getTime() - startedAt.getTime()),
        outcome,
        ...(outcome === "admitted" && options.artifact ? { artifact: options.artifact } : {}),
      };
      const diagnostic = (
        outcome === "cancelled"
          ? DEFAULT_DIAGNOSTICS.cancelled
          : (options.diagnostic ?? DEFAULT_DIAGNOSTICS[outcome])
      ).slice(0, MAX_ISOLATED_COMMAND_DIAGNOSTIC_LENGTH);

      if (outcome === "admitted") {
        return {
          outcome,
          diagnostic,
          provenance,
          exitCode: options.exitCode ?? 0,
          ...(options.candidate ? { candidate: options.candidate } : {}),
        };
      }

      return {
        outcome,
        diagnostic,
        provenance,
        ...(options.exitCode === undefined ? {} : { exitCode: options.exitCode }),
      };
    },
  };
}
