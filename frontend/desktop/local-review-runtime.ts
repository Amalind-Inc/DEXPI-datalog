import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";

export type LocalReviewRuntime = {
  endpoint: string;
  stop(): Promise<void>;
};

export type LocalReviewRuntimeOptions = {
  command: string;
  args: readonly string[];
  endpointFromStdout(line: string): string | null;
  healthPath: string;
  startupTimeoutMs?: number;
  workingDirectory?: string;
  environment?: Partial<NodeJS.ProcessEnv>;
};

const DEFAULT_STARTUP_TIMEOUT_MS = 10_000;
const HEALTH_RETRY_INTERVAL_MS = 50;

export async function startLocalReviewRuntime(
  options: LocalReviewRuntimeOptions,
): Promise<LocalReviewRuntime> {
  const child = spawn(options.command, [...options.args], {
    cwd: options.workingDirectory,
    env: { ...process.env, ...options.environment },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stopped = false;
  let exitError: Error | null = null;

  child.once("error", (error) => {
    exitError = error;
  });
  child.once("exit", (code, signal) => {
    if (!stopped) {
      exitError = new Error(
        `Local review sidecar exited before becoming healthy (code ${code ?? "none"}, signal ${signal ?? "none"}).`,
      );
    }
  });

  const startupTimeoutMs = options.startupTimeoutMs ?? DEFAULT_STARTUP_TIMEOUT_MS;
  try {
    const endpoint = await readEndpoint(child, options, startupTimeoutMs);
    await waitForHealth(endpoint, options.healthPath, startupTimeoutMs, () => exitError);
    return {
      endpoint,
      async stop(): Promise<void> {
        if (stopped || child.exitCode !== null) {
          return;
        }
        stopped = true;
        await terminate(child);
      },
    };
  } catch (error) {
    stopped = true;
    await terminate(child);
    throw error;
  }
}

async function readEndpoint(
  child: ChildProcess,
  options: LocalReviewRuntimeOptions,
  startupTimeoutMs: number,
): Promise<string> {
  if (child.stdout === null && child.stderr === null) {
    throw new Error("Local review sidecar did not expose process output.");
  }

  const result = Promise.withResolvers<string>();
  const streams = [child.stdout, child.stderr].filter(
    (stream): stream is NonNullable<typeof stream> => stream !== null,
  );
  const lines = streams.map((stream) => createInterface({ input: stream }));
  const timeout = setTimeout(() => {
    cleanup();
    result.reject(
      new Error(`Local review sidecar did not publish an endpoint within ${startupTimeoutMs}ms.`),
    );
  }, startupTimeoutMs);
  const rejectOnExit = (code: number | null, signal: NodeJS.Signals | null) => {
    cleanup();
    result.reject(
      new Error(
        `Local review sidecar exited before publishing an endpoint (code ${code ?? "none"}, signal ${signal ?? "none"}).`,
      ),
    );
  };
  const rejectOnError = (error: Error) => {
    cleanup();
    result.reject(error);
  };
  const onLine = (line: string) => {
    const endpoint = options.endpointFromStdout(line);
    if (endpoint === null) {
      return;
    }
    cleanup();
    result.resolve(endpoint);
  };
  const cleanup = () => {
    clearTimeout(timeout);
    for (const lineReader of lines) {
      lineReader.close();
      lineReader.off("line", onLine);
    }
    child.off("exit", rejectOnExit);
    child.off("error", rejectOnError);
  };

  child.on("exit", rejectOnExit);
  child.on("error", rejectOnError);
  for (const lineReader of lines) {
    lineReader.on("line", onLine);
  }
  return result.promise;
}

async function waitForHealth(
  endpoint: string,
  healthPath: string,
  startupTimeoutMs: number,
  readExitError: () => Error | null,
): Promise<void> {
  const deadline = Date.now() + startupTimeoutMs;
  while (Date.now() < deadline) {
    const exitError = readExitError();
    if (exitError !== null) {
      throw exitError;
    }
    try {
      const response = await fetch(new URL(healthPath, endpoint));
      if (response.ok) {
        return;
      }
    } catch {
      // The child may still be binding its loopback listener.
    }
    await delay(HEALTH_RETRY_INTERVAL_MS);
  }
  throw new Error(
    `Local review sidecar did not become healthy at ${new URL(healthPath, endpoint)} within ${startupTimeoutMs}ms.`,
  );
}

async function terminate(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) {
    return;
  }
  const completion = Promise.withResolvers<void>();
  child.once("exit", () => completion.resolve());
  child.kill("SIGTERM");
  await completion.promise;
}

function delay(milliseconds: number): Promise<void> {
  const completion = Promise.withResolvers<void>();
  setTimeout(completion.resolve, milliseconds);
  return completion.promise;
}
