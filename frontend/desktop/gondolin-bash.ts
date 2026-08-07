import { createHash } from "node:crypto";
import { constants, type Stats } from "node:fs";
import { access, lstat, open, opendir, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";

import { MemoryProvider, VM, type VMOptions, type VirtualProvider } from "@earendil-works/gondolin";

import type {
  BashDiffArtifact,
  BashDiffEntry,
  BashExecutionMetadata,
  BashExecutionResult,
  BashOutputUpdate,
  NormalizedBashRequest,
  RunGovernedBash,
} from "./bash-capability.ts";
import {
  assertNoWorkspaceSymlinkComponents,
  loadPortLogWorkspacePathPolicy,
  normalizeWorkspaceRelativePath,
  PORTLOG_WORKSPACE_PATH_POLICY_DIGEST,
  type PortLogWorkspacePathPolicy,
} from "./workspace-path-policy.ts";

const MAX_SNAPSHOT_FILES = 512;
const MAX_SNAPSHOT_DIRECTORIES = 256;
const MAX_SNAPSHOT_FILE_BYTES = 8 * 1024 * 1024;
const MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024;
const MAX_SNAPSHOT_DURATION_MS = 5_000;
const MAX_CAPTURE_BYTES = 8 * 1024;
const MAX_LIVE_BYTES = 64 * 1024;
const MAX_LIVE_UPDATE_BYTES = 4 * 1024;
const MAX_DIFF_SCAN_ENTRIES = 1_024;
const MAX_DIFF_ENTRIES = 128;
const MAX_DIFF_CONTENT_FILE_BYTES = 8 * 1024;
const MAX_DIFF_CONTENT_BYTES = 32 * 1024;
const CLEANUP_TIMEOUT_MS = 5_000;
const GONDOLIN_BACKEND = Object.freeze({ id: "gondolin-qemu-hvf", version: "0.10.0" });
const GONDOLIN_IMAGE = Object.freeze({ id: "alpine-base", version: "gondolin-0.10.0" });
const NORMAL_BASH_PROFILE_MANIFEST = Object.freeze({
  id: "normal-bash-request",
  version: "1",
  shell: "/bin/sh",
  argv: ["-c"],
  network: "disabled",
  workspace: "bounded-ephemeral-copy",
});
const GONDOLIN_BASH_COMMAND_PROFILE = Object.freeze({
  id: NORMAL_BASH_PROFILE_MANIFEST.id,
  version: NORMAL_BASH_PROFILE_MANIFEST.version,
  digest: `sha256:${createHash("sha256")
    .update(JSON.stringify(NORMAL_BASH_PROFILE_MANIFEST))
    .digest("hex")}`,
});
const EMPTY_DIGEST = `sha256:${createHash("sha256").update("").digest("hex")}`;
const GUEST_ENV = Object.freeze({
  HOME: "/tmp",
  LANG: "C.UTF-8",
  LC_ALL: "C.UTF-8",
  PATH: "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
  TMPDIR: "/tmp",
});

export interface GondolinBashOutputChunk {
  readonly stream: "stdout" | "stderr";
  readonly data: Buffer;
  readonly text: string;
}

export interface GondolinBashProcess extends PromiseLike<{
  exitCode: number;
  stdout: string;
  stderr: string;
}> {
  output(): AsyncIterable<GondolinBashOutputChunk>;
}

export interface GondolinBashVm {
  exec(
    command: string[],
    options?: {
      signal?: AbortSignal;
      cwd?: string;
      stdin?: boolean;
      pty?: boolean;
      env?: Record<string, string>;
      stdout?: "buffer" | "pipe";
      stderr?: "buffer" | "pipe";
    },
  ): GondolinBashProcess;
  close(): Promise<void>;
}

type SnapshotDirectory = {
  readonly path: string;
  readonly mode: number;
};

type SnapshotFile = {
  readonly path: string;
  readonly bytes: Buffer;
  readonly digest: string;
  readonly mode: number;
};

type SnapshotEntry =
  | ({ readonly entryType: "directory" } & SnapshotDirectory)
  | ({ readonly entryType: "file" } & SnapshotFile);

type WorkspaceSnapshot = {
  readonly root: string;
  readonly cwd: string;
  readonly digest: string;
  readonly policy: PortLogWorkspacePathPolicy;
  readonly fileCount: number;
  readonly directoryCount: number;
  readonly byteLength: number;
  readonly entries: readonly SnapshotEntry[];
  readonly baseline: ReadonlyMap<string, SnapshotEntry>;
  readonly provider: VirtualProvider;
  readonly exclusions: BashExecutionMetadata["exclusions"];
};

type TerminalCause = "external" | "deadline";

type CreateGondolinBashVm = (options: VMOptions) => Promise<GondolinBashVm>;

export interface GondolinBashRunnerOptions {
  readonly workspaceRoot: string;
  readonly qemuPath: string;
  readonly scheduleTimeout?: (callback: () => void, delayMs: number) => unknown;
  readonly cancelTimeout?: (handle: unknown) => void;
  readonly imagePath?: string;
  readonly imageIdentity?: { readonly id: string; readonly version: string };
  readonly policyDigest: string;
  readonly createVm?: CreateGondolinBashVm;
  readonly now?: () => Date;
}

export function createGondolinBashRunner(options: GondolinBashRunnerOptions): RunGovernedBash {
  const now = options.now ?? (() => new Date());
  const scheduleTimeout =
    options.scheduleTimeout ??
    ((callback: () => void, delayMs: number) => setTimeout(callback, delayMs));
  const cancelTimeout =
    options.cancelTimeout ?? ((handle: unknown) => clearTimeout(handle as NodeJS.Timeout));
  const createVm: CreateGondolinBashVm =
    options.createVm ?? (async (vmOptions) => VM.create(vmOptions));

  return async (request, signal, onUpdate) => {
    const startedAt = now();
    const commandDigest = digestText(request.command);
    const executionController = new AbortController();
    let terminalCause: TerminalCause | undefined;
    const abortFor = (cause: TerminalCause) => {
      if (terminalCause !== undefined) return;
      terminalCause = cause;
      executionController.abort();
    };
    const onExternalAbort = () => abortFor("external");
    if (signal.aborted) onExternalAbort();
    else signal.addEventListener("abort", onExternalAbort, { once: true });
    const timeoutHandle = scheduleTimeout(() => abortFor("deadline"), request.timeoutMs);

    let outcome: BashExecutionResult["outcome"] = "unavailable";
    let diagnostic = "Gondolin Bash is unavailable.";
    let exitCode: number | undefined;
    let snapshot: WorkspaceSnapshot | undefined;
    let scratch: VirtualProvider | undefined;
    let vm: GondolinBashVm | undefined;
    let diffArtifact: BashDiffArtifact | undefined;
    let output = emptyOutputCapture();
    let cleanup: BashExecutionMetadata["cleanup"] = "completed";

    try {
      if (terminalCause !== undefined) throw new TerminalAbortError(terminalCause);
      if (options.imagePath && !options.imageIdentity)
        throw new StartupError("A configured Gondolin image requires an explicit identity.");
      if (!options.createVm) {
        if (process.platform !== "darwin" || process.arch !== "arm64")
          throw new StartupError("Gondolin QEMU/HVF requires an arm64 macOS host.");
        if (!isAbsolute(options.qemuPath))
          throw new StartupError("Gondolin QEMU/HVF requires an absolute QEMU path.");
        try {
          await access(options.qemuPath, constants.X_OK);
        } catch {
          throw new StartupError("Gondolin QEMU/HVF executable is unavailable.");
        }
      }

      snapshot = await buildWorkspaceSnapshot(
        options.workspaceRoot,
        request,
        executionController.signal,
        startedAt.getTime() + Math.min(request.timeoutMs, MAX_SNAPSHOT_DURATION_MS),
      );
      scratch = new MemoryProvider();
      if (terminalCause !== undefined) throw new TerminalAbortError(terminalCause);

      vm = await createVm({
        sandbox: {
          vmm: "qemu",
          qemuPath: options.qemuPath,
          accel: "hvf",
          machineType: "virt",
          memory: "2G",
          cpus: 1,
          imagePath: options.imagePath ?? GONDOLIN_IMAGE.id,
          netEnabled: false,
          console: "none",
          autoRestart: false,
        },
        rootfs: { mode: "memory" },
        vfs: {
          mounts: {
            "/workspace": snapshot.provider,
            "/scratch": scratch,
          },
        },
        env: [],
      });
      if (terminalCause !== undefined) throw new TerminalAbortError(terminalCause);

      const processHandle = vm.exec(["/bin/sh", "-c", request.command], {
        signal: executionController.signal,
        cwd: snapshot.cwd,
        stdin: false,
        pty: false,
        env: { ...GUEST_ENV },
        stdout: "pipe",
        stderr: "pipe",
      });
      output = await drainBoundedOutput(processHandle, executionController.signal, onUpdate);
      const execution = await processHandle;
      if (terminalCause !== undefined) throw new TerminalAbortError(terminalCause);

      exitCode = execution.exitCode;
      diffArtifact = await buildDiffArtifact(snapshot, executionController.signal);
      if (terminalCause !== undefined) throw new TerminalAbortError(terminalCause);
      if (execution.exitCode !== 0) {
        outcome = "failed";
        diagnostic = `Gondolin Bash command failed with exit code ${execution.exitCode}.`;
      } else {
        outcome = "admitted";
        diagnostic = "Gondolin Bash command completed.";
      }
    } catch (error) {
      if (terminalCause !== undefined || error instanceof TerminalAbortError) {
        const cause =
          terminalCause ?? (error instanceof TerminalAbortError ? error.cause : "external");
        terminalCause = cause;
        outcome = cause === "external" ? "cancelled" : "timed_out";
        diagnostic =
          cause === "external" ? "Gondolin Bash was cancelled." : "Gondolin Bash timed out.";
        exitCode = undefined;
        diffArtifact = undefined;
      } else if (error instanceof PolicyError) {
        outcome = "rejected";
        diagnostic = error.message;
      } else if (error instanceof StartupError) {
        outcome = "unavailable";
        diagnostic = error.message;
      } else if (error instanceof SnapshotError) {
        outcome = "unavailable";
        diagnostic = error.message;
      } else if (vm) {
        outcome = "failed";
        diagnostic = "Gondolin Bash failed before a complete result was available.";
      } else {
        outcome = "unavailable";
        diagnostic = "The bounded Gondolin workspace snapshot or guest could not be prepared.";
      }
      if (outcome !== "failed" || exitCode === undefined) exitCode = undefined;
    } finally {
      cancelTimeout(timeoutHandle);
      const cleanupErrors: string[] = [];
      if (vm) {
        try {
          await withCleanupTimeout(vm.close());
        } catch {
          cleanupErrors.push("guest");
        }
      }
      if (cleanupErrors.length > 0) {
        cleanup = "failed";
        if (outcome === "admitted") {
          outcome = "failed";
          diagnostic = "Gondolin Bash completed but isolated resources could not be released.";
          exitCode = undefined;
          diffArtifact = undefined;
        } else {
          diagnostic = `${diagnostic} Isolated resource cleanup also failed.`;
        }
      }
    }

    const completedAt = now();
    const metadata = createMetadata({
      options,
      request,
      startedAt,
      completedAt,
      commandDigest,
      snapshot,
      output,
      cleanup,
      terminalCause,
      diffArtifact,
    });
    return {
      outcome,
      stdout: output.stdout,
      stderr: output.stderr,
      diagnostic: diagnostic.slice(0, 240),
      ...(exitCode === undefined ? {} : { exitCode }),
      metadata,
      ...(diffArtifact === undefined ? {} : { diffArtifact }),
    };
  };
}

async function buildWorkspaceSnapshot(
  workspaceRoot: string,
  request: NormalizedBashRequest,
  signal: AbortSignal,
  deadline: number,
): Promise<WorkspaceSnapshot> {
  assertSnapshotActive(signal, deadline);
  const root = await realpath(workspaceRoot);
  const policy = await loadPortLogWorkspacePathPolicy(root);
  const exclusions: BashExecutionMetadata["exclusions"] = {
    protected: 0,
    ignored: 0,
    defaultIgnored: 0,
    symlinks: 0,
  };
  const lexicalRoot = resolve(workspaceRoot);
  const lexicalCwd = resolve(request.cwd);
  const requestedCwd = isWithin(lexicalRoot, lexicalCwd)
    ? relative(lexicalRoot, lexicalCwd)
    : request.cwd;
  const cwdIdentity = await assertNoWorkspaceSymlinkComponents(root, requestedCwd);
  const entries: SnapshotEntry[] = [];
  const includedDirectories = new Set<string>([""]);
  let files = 0;
  let directories = 0;
  let totalBytes = 0;

  const visitDirectory = async (
    hostDirectory: string,
    relativeDirectory: string,
    expectedStatus?: Stats,
  ): Promise<void> => {
    const names = await readStableDirectoryNames(
      root,
      hostDirectory,
      expectedStatus,
      signal,
      deadline,
    );

    for (const name of names) {
      assertSnapshotActive(signal, deadline);
      if (name.includes("/") || name.includes("\\") || name.includes("\0"))
        throw new SnapshotError("Workspace entry name is malformed.");
      const relativePath = relativeDirectory ? `${relativeDirectory}/${name}` : name;
      const normalized = normalizeWorkspaceRelativePath(relativePath);
      const hostPath = resolve(root, ...normalized.split("/"));
      const before = await lstat(hostPath);
      if (before.isSymbolicLink()) {
        exclusions.symlinks += 1;
        continue;
      }
      const kind = before.isDirectory() ? "directory" : "file";
      const decision = policy.evaluate(normalized, kind);
      if (!decision.include) {
        if (decision.reason === "protected") exclusions.protected += 1;
        else if (decision.reason === "default_ignored") exclusions.defaultIgnored += 1;
        else exclusions.ignored += 1;
        continue;
      }
      if (before.isDirectory()) {
        directories += 1;
        if (directories > MAX_SNAPSHOT_DIRECTORIES)
          throw new SnapshotError("Workspace snapshot contains too many directories.");
        const directoryEntry: SnapshotEntry = {
          entryType: "directory",
          path: normalized,
          mode: before.mode & 0o777,
        };
        entries.push(directoryEntry);
        includedDirectories.add(normalized);
        await visitDirectory(hostPath, normalized, before);
      } else if (before.isFile()) {
        files += 1;
        if (files > MAX_SNAPSHOT_FILES)
          throw new SnapshotError("Workspace snapshot contains too many files.");
        if (before.size > MAX_SNAPSHOT_FILE_BYTES)
          throw new SnapshotError("Workspace snapshot file exceeds the per-file limit.");
        const file = await readStableFile(root, hostPath, before, signal, deadline);
        totalBytes += file.bytes.byteLength;
        if (totalBytes > MAX_SNAPSHOT_BYTES)
          throw new SnapshotError("Workspace snapshot exceeds the aggregate byte limit.");
        entries.push({ entryType: "file", path: normalized, ...file });
      } else {
        throw new SnapshotError("Workspace snapshot contains an unsupported entry type.");
      }
    }
  };

  await visitDirectory(root, "");
  const cwdRelative = cwdIdentity.relativePath;
  if (cwdRelative && !includedDirectories.has(cwdRelative))
    throw new PolicyError("Bash cwd is excluded from the admitted workspace snapshot.");
  entries.sort((left, right) => left.path.localeCompare(right.path));
  const provider = new MemoryProvider();
  for (const entry of entries) {
    const guestPath = `/${entry.path}`;
    if (entry.entryType === "directory") await provider.mkdir(guestPath, { mode: entry.mode });
    else {
      if (!provider.writeFile) throw new SnapshotError("Memory workspace cannot accept files.");
      await provider.writeFile(guestPath, entry.bytes, { mode: entry.mode });
    }
  }
  const baseline = new Map(entries.map((entry) => [entry.path, entry]));
  return {
    root,
    fileCount: files,
    directoryCount: directories,
    byteLength: totalBytes,
    cwd: cwdRelative ? `/workspace/${cwdRelative}` : "/workspace",
    digest: digestSnapshot(entries),
    policy,
    entries,
    baseline,
    provider,
    exclusions,
  };
}

async function readStableDirectoryNames(
  root: string,
  path: string,
  expectedStatus: Stats | undefined,
  signal: AbortSignal,
  deadline: number,
): Promise<string[]> {
  assertSnapshotActive(signal, deadline);
  await assertNoWorkspaceSymlinkComponents(root, relative(root, path));
  const lexicalStatus = await lstat(path);
  if (
    lexicalStatus.isSymbolicLink() ||
    !lexicalStatus.isDirectory() ||
    (expectedStatus !== undefined &&
      (lexicalStatus.dev !== expectedStatus.dev || lexicalStatus.ino !== expectedStatus.ino))
  )
    throw new SnapshotError("Workspace directory identity changed before it was read.");
  const handle = await open(
    path,
    constants.O_RDONLY | (constants.O_DIRECTORY ?? 0) | (constants.O_NOFOLLOW ?? 0),
  );
  try {
    const openedStatus = await handle.stat();
    await assertNoWorkspaceSymlinkComponents(root, relative(root, path));
    const lexicalAfterOpen = await lstat(path);
    if (
      !openedStatus.isDirectory() ||
      openedStatus.dev !== lexicalStatus.dev ||
      openedStatus.ino !== lexicalStatus.ino ||
      lexicalAfterOpen.isSymbolicLink() ||
      lexicalAfterOpen.dev !== openedStatus.dev ||
      lexicalAfterOpen.ino !== openedStatus.ino
    )
      throw new SnapshotError("Workspace directory identity changed before it was read.");

    const directory = await opendir(path);
    const names: string[] = [];
    try {
      for await (const item of directory) names.push(item.name);
    } finally {
      try {
        await directory.close();
      } catch {
        // Async directory iteration may already have closed the handle.
      }
    }

    assertSnapshotActive(signal, deadline);
    await assertNoWorkspaceSymlinkComponents(root, relative(root, path));
    const after = await handle.stat();
    const lexicalAfterRead = await lstat(path);
    if (
      after.dev !== openedStatus.dev ||
      after.ino !== openedStatus.ino ||
      after.mtimeMs !== openedStatus.mtimeMs ||
      lexicalAfterRead.isSymbolicLink() ||
      lexicalAfterRead.dev !== openedStatus.dev ||
      lexicalAfterRead.ino !== openedStatus.ino
    )
      throw new SnapshotError("Workspace directory changed while it was read.");
    return names.sort((left, right) => left.localeCompare(right));
  } finally {
    await handle.close();
  }
}

async function readStableFile(
  root: string,
  path: string,
  lexicalStatus: Stats,
  signal: AbortSignal,
  deadline: number,
): Promise<{ bytes: Buffer; digest: string; mode: number }> {
  await assertNoWorkspaceSymlinkComponents(root, relative(root, path));
  const handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const before = await handle.stat();
    await assertNoWorkspaceSymlinkComponents(root, relative(root, path));
    const lexicalAfterOpen = await lstat(path);
    if (
      !before.isFile() ||
      before.nlink !== 1 ||
      before.dev !== lexicalStatus.dev ||
      before.ino !== lexicalStatus.ino ||
      before.size !== lexicalStatus.size ||
      lexicalAfterOpen.isSymbolicLink() ||
      lexicalAfterOpen.dev !== before.dev ||
      lexicalAfterOpen.ino !== before.ino
    )
      throw new SnapshotError("Workspace file identity changed before it was read.");
    assertSnapshotActive(signal, deadline);
    const bytes = await handle.readFile();
    await assertNoWorkspaceSymlinkComponents(root, relative(root, path));
    const lexicalAfterRead = await lstat(path);
    const after = await handle.stat();
    if (
      bytes.byteLength !== before.size ||
      after.dev !== before.dev ||
      after.ino !== before.ino ||
      after.size !== before.size ||
      after.mtimeMs !== before.mtimeMs ||
      after.nlink !== 1 ||
      lexicalAfterRead.isSymbolicLink() ||
      lexicalAfterRead.dev !== before.dev ||
      lexicalAfterRead.ino !== before.ino
    )
      throw new SnapshotError("Workspace file changed while it was read.");
    return {
      bytes,
      digest: digestBytes(bytes),
      mode: before.mode & 0o777,
    };
  } finally {
    await handle.close();
  }
}

function digestSnapshot(entries: readonly SnapshotEntry[]): string {
  const hash = createHash("sha256");
  for (const entry of entries) {
    hash.update(entry.entryType === "file" ? "F\0" : "D\0");
    hash.update(entry.path);
    hash.update("\0");
    hash.update(String(entry.mode));
    hash.update("\0");
    if (entry.entryType === "file") {
      hash.update(entry.digest);
      hash.update("\0");
      hash.update(String(entry.bytes.byteLength));
    }
    hash.update("\n");
  }
  return `sha256:${hash.digest("hex")}`;
}

async function drainBoundedOutput(
  processHandle: GondolinBashProcess,
  signal: AbortSignal,
  onUpdate?: (update: BashOutputUpdate) => void,
): Promise<OutputCapture> {
  const stdoutChunks: Buffer[] = [];
  const stderrChunks: Buffer[] = [];
  const decoders = {
    stdout: new TextDecoder("utf-8", { fatal: false }),
    stderr: new TextDecoder("utf-8", { fatal: false }),
  };
  let stdoutBytes = 0;
  let stderrBytes = 0;
  let stdoutCapturedBytes = 0;
  let stderrCapturedBytes = 0;
  let liveBytes = 0;
  let sequence = 0;
  let liveTruncated = false;

  for await (const chunk of processHandle.output()) {
    if (signal.aborted) throw new TerminalAbortError("external");
    const bytes = Buffer.isBuffer(chunk.data) ? chunk.data : Buffer.from(chunk.data);
    if (chunk.stream === "stdout") {
      stdoutBytes += bytes.byteLength;
      const captured = bytes.subarray(0, Math.max(0, MAX_CAPTURE_BYTES - stdoutCapturedBytes));
      if (captured.byteLength > 0) {
        stdoutChunks.push(captured);
        stdoutCapturedBytes += captured.byteLength;
      }
    } else {
      stderrBytes += bytes.byteLength;
      const captured = bytes.subarray(0, Math.max(0, MAX_CAPTURE_BYTES - stderrCapturedBytes));
      if (captured.byteLength > 0) {
        stderrChunks.push(captured);
        stderrCapturedBytes += captured.byteLength;
      }
    }

    if (bytes.byteLength > MAX_LIVE_BYTES - liveBytes) liveTruncated = true;
    let offset = 0;
    while (offset < bytes.byteLength && liveBytes < MAX_LIVE_BYTES) {
      const available = Math.min(
        MAX_LIVE_UPDATE_BYTES,
        bytes.byteLength - offset,
        MAX_LIVE_BYTES - liveBytes,
      );
      const piece = bytes.subarray(offset, offset + available);
      offset += available;
      liveBytes += available;
      const text = decoders[chunk.stream].decode(piece, { stream: true });
      if (text && onUpdate) {
        sequence += 1;
        onUpdate({
          stdout: chunk.stream === "stdout" ? text : "",
          stderr: chunk.stream === "stderr" ? text : "",
          sequence,
          stdoutBytes,
          stderrBytes,
          truncated: liveTruncated,
        });
      }
    }
    if (offset < bytes.byteLength) liveTruncated = true;
  }

  for (const stream of ["stdout", "stderr"] as const) {
    const text = decoders[stream].decode();
    if (text && onUpdate && liveBytes < MAX_LIVE_BYTES) {
      sequence += 1;
      onUpdate({
        stdout: stream === "stdout" ? text : "",
        stderr: stream === "stderr" ? text : "",
        sequence,
        stdoutBytes,
        stderrBytes,
        truncated: liveTruncated,
      });
    }
  }

  return {
    stdout: Buffer.concat(stdoutChunks).toString("utf8"),
    stderr: Buffer.concat(stderrChunks).toString("utf8"),
    stdoutBytes,
    stderrBytes,
    stdoutCapturedBytes,
    stderrCapturedBytes,
    stdoutDroppedBytes: Math.max(0, stdoutBytes - stdoutCapturedBytes),
    stderrDroppedBytes: Math.max(0, stderrBytes - stderrCapturedBytes),
    stdoutTruncated: stdoutBytes > stdoutCapturedBytes,
    stderrTruncated: stderrBytes > stderrCapturedBytes,
  };
}

type ProviderReadResult = {
  readonly entries: Map<string, SnapshotEntry>;
  readonly suppressedPrefixes: Set<string>;
  readonly scanComplete: boolean;
};

async function buildDiffArtifact(
  snapshot: WorkspaceSnapshot,
  signal: AbortSignal,
): Promise<BashDiffArtifact> {
  const current = await readProviderEntries(snapshot.provider, snapshot.policy, signal);
  const paths = [...new Set([...snapshot.baseline.keys(), ...current.entries.keys()])].sort(
    (left, right) => left.localeCompare(right),
  );
  const entries: BashDiffEntry[] = [];
  let contentBytes = 0;
  let truncated = !current.scanComplete || current.suppressedPrefixes.size > 0;

  for (const path of paths) {
    if (signal.aborted) throw new TerminalAbortError("external");
    const baseline = snapshot.baseline.get(path);
    const result = current.entries.get(path);
    if (
      baseline &&
      !result &&
      (!current.scanComplete ||
        [...current.suppressedPrefixes].some(
          (prefix) => path === prefix || path.startsWith(`${prefix}/`),
        ))
    ) {
      truncated = true;
      continue;
    }
    if (baseline && result && sameSnapshotEntry(baseline, result)) continue;
    if (entries.length >= MAX_DIFF_ENTRIES) {
      truncated = true;
      continue;
    }
    const status = baseline ? (result ? "modified" : "deleted") : "added";
    const entryType = result?.entryType ?? baseline?.entryType;
    if (!entryType) continue;
    const entry: BashDiffEntry = {
      path,
      status,
      entryType,
      ...(baseline?.entryType === "file"
        ? {
            baselineDigest: baseline.digest,
            baselineBytes: baseline.bytes.byteLength,
            baselineMode: baseline.mode,
          }
        : baseline
          ? { baselineMode: baseline.mode }
          : {}),
      ...(result?.entryType === "file"
        ? {
            resultDigest: result.digest,
            resultBytes: result.bytes.byteLength,
            resultMode: result.mode,
          }
        : result
          ? { resultMode: result.mode }
          : {}),
    };
    if (
      result?.entryType === "file" &&
      result.bytes.byteLength <= MAX_DIFF_CONTENT_FILE_BYTES &&
      contentBytes + result.bytes.byteLength <= MAX_DIFF_CONTENT_BYTES
    ) {
      entry.content = { encoding: "base64", data: result.bytes.toString("base64") };
      contentBytes += result.bytes.byteLength;
    } else if (result?.entryType === "file" && result.bytes.byteLength > 0) truncated = true;
    entries.push(entry);
  }

  const body = {
    schemaVersion: 1 as const,
    authority: "ordinary" as const,
    applicable: false as const,
    truncated,
    entries,
  };
  return { ...body, digest: digestText(JSON.stringify(body)) };
}

async function readProviderEntries(
  provider: VirtualProvider,
  policy: PortLogWorkspacePathPolicy,
  signal: AbortSignal,
): Promise<ProviderReadResult> {
  const entries = new Map<string, SnapshotEntry>();
  const suppressedPrefixes = new Set<string>();
  let scannedEntries = 0;
  let totalBytes = 0;
  let scanComplete = true;

  const visit = async (directory: string): Promise<void> => {
    if (signal.aborted) throw new TerminalAbortError("external");
    const children = (await provider.readdir(directory ? `/${directory}` : "/"))
      .map((item) => (typeof item === "string" ? item : item.name))
      .sort();
    const remaining = Math.max(0, MAX_DIFF_SCAN_ENTRIES - scannedEntries);
    if (children.length > remaining) scanComplete = false;
    const names = children.slice(0, remaining);
    for (const name of names) {
      if (scannedEntries >= MAX_DIFF_SCAN_ENTRIES) {
        scanComplete = false;
        break;
      }
      scannedEntries += 1;
      const relativePath = directory ? `${directory}/${name}` : name;
      let normalized: string;
      try {
        normalized = normalizeWorkspaceRelativePath(relativePath);
      } catch {
        suppressedPrefixes.add(relativePath);
        continue;
      }
      const path = `/${normalized}`;
      const status = provider.lstat ? await provider.lstat(path) : await provider.stat(path);
      const kind = status.isDirectory() ? "directory" : "file";
      if (!policy.evaluate(normalized, kind).include) {
        suppressedPrefixes.add(normalized);
        continue;
      }
      if (status.isSymbolicLink() || (!status.isDirectory() && !status.isFile())) {
        suppressedPrefixes.add(normalized);
        continue;
      }
      if (status.isDirectory()) {
        entries.set(normalized, {
          entryType: "directory",
          path: normalized,
          mode: status.mode & 0o777,
        });
        await visit(normalized);
      } else {
        if (
          !provider.readFile ||
          status.size > MAX_SNAPSHOT_FILE_BYTES ||
          totalBytes + status.size > MAX_SNAPSHOT_BYTES
        ) {
          suppressedPrefixes.add(normalized);
          continue;
        }
        const value = await provider.readFile(path);
        const bytes = Buffer.isBuffer(value) ? value : Buffer.from(String(value));
        if (
          bytes.byteLength > MAX_SNAPSHOT_FILE_BYTES ||
          totalBytes + bytes.byteLength > MAX_SNAPSHOT_BYTES
        ) {
          suppressedPrefixes.add(normalized);
          continue;
        }
        totalBytes += bytes.byteLength;
        entries.set(normalized, {
          entryType: "file",
          path: normalized,
          bytes,
          digest: digestBytes(bytes),
          mode: status.mode & 0o777,
        });
      }
    }
  };
  await visit("");
  return { entries, suppressedPrefixes, scanComplete };
}

function sameSnapshotEntry(left: SnapshotEntry, right: SnapshotEntry): boolean {
  if (left.entryType !== right.entryType || left.mode !== right.mode) return false;
  if (left.entryType === "directory" || right.entryType === "directory") return true;
  return left.digest === right.digest && left.bytes.byteLength === right.bytes.byteLength;
}

type OutputCapture = {
  stdout: string;
  stderr: string;
  stdoutBytes: number;
  stderrBytes: number;
  stdoutCapturedBytes: number;
  stderrCapturedBytes: number;
  stdoutDroppedBytes: number;
  stderrDroppedBytes: number;
  stdoutTruncated: boolean;
  stderrTruncated: boolean;
};

function emptyOutputCapture(): OutputCapture {
  return {
    stdout: "",
    stderr: "",
    stdoutBytes: 0,
    stderrBytes: 0,
    stdoutCapturedBytes: 0,
    stderrCapturedBytes: 0,
    stdoutDroppedBytes: 0,
    stderrDroppedBytes: 0,
    stdoutTruncated: false,
    stderrTruncated: false,
  };
}

function createMetadata(input: {
  options: GondolinBashRunnerOptions;
  request: NormalizedBashRequest;
  startedAt: Date;
  completedAt: Date;
  commandDigest: string;
  snapshot?: WorkspaceSnapshot;
  output: OutputCapture;
  cleanup: BashExecutionMetadata["cleanup"];
  terminalCause?: TerminalCause;
  diffArtifact?: BashDiffArtifact;
}): BashExecutionMetadata {
  const cwd = input.snapshot
    ? input.snapshot.cwd.replace(/^\/workspace\/?/u, "") || "."
    : relative(input.options.workspaceRoot, input.request.cwd).split("\\").join("/") || ".";
  return {
    schemaVersion: 1,
    backend: GONDOLIN_BACKEND,
    image: input.options.imageIdentity ?? GONDOLIN_IMAGE,
    commandProfile: GONDOLIN_BASH_COMMAND_PROFILE,
    network: "disabled",
    policyDigest: input.options.policyDigest,
    workspacePolicyDigest:
      input.snapshot?.policy.policyDigest ?? PORTLOG_WORKSPACE_PATH_POLICY_DIGEST,
    ignoreDigest: input.snapshot?.policy.ignoreDigest ?? EMPTY_DIGEST,
    snapshotDigest: input.snapshot?.digest ?? EMPTY_DIGEST,
    commandDigest: input.commandDigest,
    timeoutMs: input.request.timeoutMs,
    snapshotFiles: input.snapshot?.fileCount ?? 0,
    snapshotDirectories: input.snapshot?.directoryCount ?? 0,
    snapshotBytes: input.snapshot?.byteLength ?? 0,
    cwd,
    startedAt: input.startedAt.toISOString(),
    completedAt: input.completedAt.toISOString(),
    durationMs: Math.max(0, input.completedAt.getTime() - input.startedAt.getTime()),
    stdoutBytes: input.output.stdoutBytes,
    stderrBytes: input.output.stderrBytes,
    stdoutCapturedBytes: input.output.stdoutCapturedBytes,
    stderrCapturedBytes: input.output.stderrCapturedBytes,
    stdoutDroppedBytes: input.output.stdoutDroppedBytes,
    stderrDroppedBytes: input.output.stderrDroppedBytes,
    stdoutTruncated: input.output.stdoutTruncated,
    stderrTruncated: input.output.stderrTruncated,
    cleanup: input.cleanup,
    ...(input.terminalCause === undefined ? {} : { terminalCause: input.terminalCause }),
    exclusions: input.snapshot?.exclusions ?? {
      protected: 0,
      ignored: 0,
      defaultIgnored: 0,
      symlinks: 0,
    },
    ...(input.diffArtifact === undefined
      ? {}
      : {
          diffDigest: input.diffArtifact.digest,
          diffTruncated: input.diffArtifact.truncated,
          diffEntries: input.diffArtifact.entries.length,
        }),
  };
}

async function withCleanupTimeout(operation: Promise<void>): Promise<void> {
  let timeoutId: NodeJS.Timeout | undefined;
  try {
    await Promise.race([
      operation,
      new Promise<never>((_resolve, reject) => {
        timeoutId = setTimeout(() => reject(new Error("Cleanup timed out.")), CLEANUP_TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timeoutId);
  }
}

function assertSnapshotActive(signal: AbortSignal, deadline: number): void {
  if (signal.aborted)
    throw new TerminalAbortError(Date.now() >= deadline ? "deadline" : "external");
  if (Date.now() >= deadline) throw new TerminalAbortError("deadline");
}

function isWithin(root: string, candidate: string): boolean {
  const suffix = relative(root, candidate);
  return suffix === "" || (!suffix.startsWith("..") && !isAbsolute(suffix));
}

function digestBytes(value: Uint8Array): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function digestText(value: string): string {
  return digestBytes(Buffer.from(value, "utf8"));
}

class TerminalAbortError extends Error {
  readonly cause: TerminalCause;

  constructor(cause: TerminalCause) {
    super(cause === "external" ? "Operation cancelled." : "Operation timed out.");
    this.cause = cause;
  }
}

class PolicyError extends Error {}
class SnapshotError extends Error {}
class StartupError extends Error {}
