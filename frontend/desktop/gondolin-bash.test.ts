import assert from "node:assert/strict";
import { link, mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type { VMOptions, VirtualProvider } from "@earendil-works/gondolin";

import { createGondolinBashRunner, type GondolinBashProcess } from "./gondolin-bash.ts";

test("Gondolin Bash executes one whole request in an isolated writable snapshot", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-gondolin-bash-"));
  const workspaceRoot = join(root, "workspace");
  await mkdir(join(workspaceRoot, "sources"), { recursive: true });
  await writeFile(join(workspaceRoot, "sources", "input.txt"), "approved input");
  await writeFile(join(workspaceRoot, ".env"), "SHOULD_NOT_ENTER_GUEST=1");
  await symlink("sources/input.txt", join(workspaceRoot, "linked-input.txt"));
  await mkdir(join(workspaceRoot, "ignored"));
  await writeFile(join(workspaceRoot, ".portlogignore"), "ignored/**\n");
  await writeFile(join(workspaceRoot, "ignored", "private.txt"), "ignore me");

  let execCalls = 0;
  let closed = false;
  try {
    const runner = createGondolinBashRunner({
      workspaceRoot,
      qemuPath: "/absolute/qemu-system-aarch64",
      policyDigest: "sha256:test-policy",
      createVm: async (vmOptions: VMOptions) => {
        assert.equal(vmOptions.sandbox?.netEnabled, false);
        assert.deepEqual(vmOptions.env, []);
        const provider = vmOptions.vfs?.mounts?.["/workspace"] as VirtualProvider | undefined;
        assert.ok(provider?.readFile);
        assert.ok(provider.writeFile);
        const input = await provider.readFile("/sources/input.txt");
        assert.equal(typeof input === "string" ? input : input.toString("utf8"), "approved input");
        await assert.rejects(provider.stat("/.env"));
        await assert.rejects(provider.stat("/linked-input.txt"));
        await assert.rejects(provider.stat("/ignored/private.txt"));

        return {
          exec(command, options) {
            execCalls += 1;
            assert.deepEqual(command, [
              "/bin/sh",
              "-c",
              "cat sources/input.txt && printf guest-only > generated.txt",
            ]);
            assert.equal(options?.cwd, "/workspace");
            assert.equal(options?.pty, false);
            assert.equal(options?.stdin, false);
            assert.equal(options?.stdout, "pipe");
            assert.equal(options?.stderr, "pipe");
            assert.deepEqual(options?.env, {
              HOME: "/tmp",
              LANG: "C.UTF-8",
              LC_ALL: "C.UTF-8",
              PATH: "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
              TMPDIR: "/tmp",
            });
            const completion = (async () => {
              await provider.writeFile!("/.env", Buffer.from("guest-generated-secret"));
              await provider.writeFile!("/generated.txt", Buffer.from("guest-only"));
              return { exitCode: 0, stdout: "", stderr: "" };
            })();
            return {
              then: completion.then.bind(completion),
              async *output() {
                yield {
                  stream: "stdout" as const,
                  data: Buffer.from("approved input"),
                  text: "approved input",
                };
                yield {
                  stream: "stderr" as const,
                  data: Buffer.from("guest warning"),
                  text: "guest warning",
                };
              },
            };
          },
          async close() {
            closed = true;
          },
        };
      },
    });

    const updates: Array<{ stdout: string; stderr: string }> = [];
    const result = await runner(
      {
        command: "cat sources/input.txt && printf guest-only > generated.txt",
        cwd: workspaceRoot,
        timeoutMs: 3_000,
        pty: false,
        env: {},
      },
      new AbortController().signal,
      (update) => updates.push(update),
    );

    assert.equal(result.outcome, "admitted", result.diagnostic);
    assert.equal(execCalls, 1);
    assert.equal(closed, true);
    assert.equal(result.stdout, "approved input");
    assert.equal(result.stderr, "guest warning");
    assert.equal(result.exitCode, 0);
    assert.equal(result.metadata?.backend.id, "gondolin-qemu-hvf");
    assert.equal(result.metadata?.policyDigest, "sha256:test-policy");
    assert.match(result.metadata?.commandDigest ?? "", /^sha256:[a-f0-9]{64}$/u);
    assert.match(result.metadata?.snapshotDigest ?? "", /^sha256:[a-f0-9]{64}$/u);
    assert.equal(result.metadata?.commandProfile.id, "normal-bash-request");
    assert.match(result.metadata?.commandProfile.digest ?? "", /^sha256:[a-f0-9]{64}$/u);
    assert.equal(result.metadata?.network, "disabled");
    assert.match(result.metadata?.workspacePolicyDigest ?? "", /^sha256:[a-f0-9]{64}$/u);
    assert.equal(result.metadata?.snapshotFiles, 2);
    assert.equal(result.metadata?.snapshotDirectories, 2);
    assert.ok((result.metadata?.snapshotBytes ?? 0) > 0);
    assert.doesNotMatch(JSON.stringify(result.metadata), /cat sources|portlog-gondolin-bash-/);
    assert.equal(result.metadata?.stdoutBytes, 14);
    assert.equal(result.metadata?.stderrBytes, 13);
    assert.equal(result.metadata?.cleanup, "completed");
    assert.equal(result.metadata?.exclusions.protected, 1);
    assert.equal(result.metadata?.exclusions.ignored, 1);
    assert.deepEqual(
      result.diffArtifact?.entries.map(({ path, status }) => ({ path, status })),
      [{ path: "generated.txt", status: "added" }],
    );
    assert.equal(result.diffArtifact?.truncated, true);
    assert.doesNotMatch(JSON.stringify(result.diffArtifact), /\.env|guest-generated-secret/);
    assert.equal(result.diffArtifact?.authority, "ordinary");
    assert.equal(result.diffArtifact?.applicable, false);
    assert.equal(result.metadata?.diffEntries, 1);
    assert.ok(updates.length >= 2);
    await assert.rejects(readFile(join(workspaceRoot, "generated.txt")));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Gondolin Bash aborts a running guest at the request deadline and still closes it", async () => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-gondolin-timeout-"));
  let execCalls = 0;
  let closed = false;
  let fireDeadline: (() => void) | undefined;
  try {
    const runner = createGondolinBashRunner({
      workspaceRoot,
      qemuPath: "/absolute/qemu-system-aarch64",
      policyDigest: "sha256:test-policy",
      scheduleTimeout(callback) {
        fireDeadline = callback;
        return "deadline";
      },
      cancelTimeout() {},
      createVm: async () => ({
        exec(_command, options) {
          execCalls += 1;
          assert.ok(options?.signal);
          const process = blockingProcess(options.signal);
          fireDeadline?.();
          return process;
        },
        async close() {
          closed = true;
        },
      }),
    });

    const result = await runner(
      {
        command: "sleep 60",
        cwd: workspaceRoot,
        timeoutMs: 30,
        pty: false,
        env: {},
      },
      new AbortController().signal,
    );

    assert.equal(execCalls, 1);
    assert.equal(closed, true);
    assert.equal(result.outcome, "timed_out");
    assert.equal(result.exitCode, undefined);
    assert.equal(result.diffArtifact, undefined);
    assert.equal(result.metadata?.terminalCause, "deadline");
    assert.equal(result.metadata?.cleanup, "completed");
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("Gondolin Bash propagates cancellation without returning a partial diff", async () => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-gondolin-cancel-"));
  const controller = new AbortController();
  let closed = false;
  try {
    const runner = createGondolinBashRunner({
      workspaceRoot,
      qemuPath: "/absolute/qemu-system-aarch64",
      policyDigest: "sha256:test-policy",
      createVm: async () => ({
        exec(_command, options) {
          assert.ok(options?.signal);
          const process = blockingProcess(options.signal);
          controller.abort();
          return process;
        },
        async close() {
          closed = true;
        },
      }),
    });

    const result = await runner(
      {
        command: "sleep 60",
        cwd: workspaceRoot,
        timeoutMs: 3_000,
        pty: false,
        env: {},
      },
      controller.signal,
    );

    assert.equal(closed, true);
    assert.equal(result.outcome, "cancelled");
    assert.equal(result.diffArtifact, undefined);
    assert.equal(result.metadata?.terminalCause, "external");
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("Gondolin Bash bounds captured and live output with explicit byte accounting", async () => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-gondolin-output-"));
  const rawOutput = Buffer.alloc(80 * 1024, 0x61);
  try {
    const runner = createGondolinBashRunner({
      workspaceRoot,
      qemuPath: "/absolute/qemu-system-aarch64",
      policyDigest: "sha256:test-policy",
      createVm: async () => ({
        exec() {
          return completedProcess([
            { stream: "stdout", data: rawOutput, text: rawOutput.toString("utf8") },
          ]);
        },
        async close() {},
      }),
    });
    const updates: Array<{
      stdout: string;
      stderr: string;
      sequence?: number;
      truncated?: boolean;
    }> = [];

    const result = await runner(
      {
        command: "yes a",
        cwd: workspaceRoot,
        timeoutMs: 3_000,
        pty: false,
        env: {},
      },
      new AbortController().signal,
      (update) => updates.push(update),
    );

    assert.equal(result.outcome, "admitted");
    assert.equal(Buffer.byteLength(result.stdout), 8 * 1024);
    assert.equal(result.metadata?.stdoutBytes, 80 * 1024);
    assert.equal(result.metadata?.stdoutCapturedBytes, 8 * 1024);
    assert.equal(result.metadata?.stdoutDroppedBytes, 72 * 1024);
    assert.equal(result.metadata?.stdoutTruncated, true);
    assert.equal(
      updates.reduce((total, update) => total + Buffer.byteLength(update.stdout), 0),
      64 * 1024,
    );
    assert.ok(updates.every((update) => Buffer.byteLength(update.stdout) <= 4 * 1024));
    assert.deepEqual(
      updates.map((update) => update.sequence),
      updates.map((_update, index) => index + 1),
    );
    assert.equal(updates.at(-1)?.truncated, true);
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("Gondolin Bash preserves a bounded proposed diff when the command exits nonzero", async () => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-gondolin-nonzero-"));
  try {
    const runner = createGondolinBashRunner({
      workspaceRoot,
      qemuPath: "/absolute/qemu-system-aarch64",
      policyDigest: "sha256:test-policy",
      createVm: async (vmOptions: VMOptions) => {
        const provider = vmOptions.vfs?.mounts?.["/workspace"] as VirtualProvider;
        return {
          exec() {
            const completion = (async () => {
              await provider.writeFile!("/partial.txt", Buffer.from("partial"));
              return { exitCode: 2, stdout: "", stderr: "" };
            })();
            return {
              then: completion.then.bind(completion),
              async *output() {
                yield {
                  stream: "stderr" as const,
                  data: Buffer.from("command failed"),
                  text: "command failed",
                };
              },
            };
          },
          async close() {},
        };
      },
    });

    const result = await runner(
      {
        command: "printf partial > partial.txt && false",
        cwd: workspaceRoot,
        timeoutMs: 3_000,
        pty: false,
        env: {},
      },
      new AbortController().signal,
    );

    assert.equal(result.outcome, "failed");
    assert.equal(result.exitCode, 2);
    assert.equal(result.stderr, "command failed");
    assert.deepEqual(
      result.diffArtifact?.entries.map(({ path, status }) => ({ path, status })),
      [{ path: "partial.txt", status: "added" }],
    );
    assert.equal(result.diffArtifact?.authority, "ordinary");
    assert.equal(result.diffArtifact?.applicable, false);
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("Gondolin Bash fails closed when guest cleanup fails after a zero exit", async () => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-gondolin-cleanup-"));
  try {
    const runner = createGondolinBashRunner({
      workspaceRoot,
      qemuPath: "/absolute/qemu-system-aarch64",
      policyDigest: "sha256:test-policy",
      createVm: async () => ({
        exec() {
          return completedProcess([]);
        },
        async close() {
          throw new Error("close failed");
        },
      }),
    });

    const result = await runner(
      {
        command: "true",
        cwd: workspaceRoot,
        timeoutMs: 3_000,
        pty: false,
        env: {},
      },
      new AbortController().signal,
    );

    assert.equal(result.outcome, "failed");
    assert.equal(result.exitCode, undefined);
    assert.equal(result.diffArtifact, undefined);
    assert.equal(result.metadata?.cleanup, "failed");
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("Gondolin Bash rejects hard-linked workspace input before guest creation", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-gondolin-hardlink-"));
  const workspaceRoot = join(root, "workspace");
  let createCalls = 0;
  try {
    await mkdir(workspaceRoot);
    const outside = join(root, "outside-secret.txt");
    await writeFile(outside, "outside secret");
    await link(outside, join(workspaceRoot, "innocent.txt"));
    const runner = createGondolinBashRunner({
      workspaceRoot,
      qemuPath: "/absolute/qemu-system-aarch64",
      policyDigest: "sha256:test-policy",
      createVm: async () => {
        createCalls += 1;
        throw new Error("Guest creation must not run.");
      },
    });

    const result = await runner(
      {
        command: "cat innocent.txt",
        cwd: workspaceRoot,
        timeoutMs: 3_000,
        pty: false,
        env: {},
      },
      new AbortController().signal,
    );

    assert.equal(createCalls, 0);
    assert.equal(result.outcome, "unavailable");
    assert.match(result.diagnostic, /file identity changed/i);
    assert.doesNotMatch(result.diagnostic, /outside-secret|outside secret/i);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

function blockingProcess(signal: AbortSignal): GondolinBashProcess {
  const completion = new Promise<{ exitCode: number; stdout: string; stderr: string }>(
    (resolve) => {
      const finish = () => resolve({ exitCode: 143, stdout: "", stderr: "" });
      if (signal.aborted) finish();
      else signal.addEventListener("abort", finish, { once: true });
    },
  );
  return {
    then: completion.then.bind(completion),
    async *output() {
      if (!signal.aborted)
        await new Promise<void>((resolve) =>
          signal.addEventListener("abort", () => resolve(), { once: true }),
        );
    },
  };
}

function completedProcess(
  chunks: Array<{ stream: "stdout" | "stderr"; data: Buffer; text: string }>,
  exitCode = 0,
): GondolinBashProcess {
  const completion = Promise.resolve({ exitCode, stdout: "", stderr: "" });
  return {
    then: completion.then.bind(completion),
    async *output() {
      for (const chunk of chunks) yield chunk;
    },
  };
}
