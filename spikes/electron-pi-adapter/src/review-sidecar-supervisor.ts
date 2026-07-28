export interface ReviewSidecarSpec {
  python: string;
  module: string;
  cwd: string;
  port: number;
  healthPath: string;
}

export interface SpawnedProcess {
  kill(): void;
}

export interface ReviewSidecarPorts {
  spawn(
    command: string,
    args: string[],
    options: { cwd: string },
  ): SpawnedProcess;
  waitForReady(url: string): Promise<void>;
  waitForExit(child: SpawnedProcess): Promise<Error>;
}

/** Electron-main-process-compatible ownership of the local review API process. */
export class ReviewSidecarSupervisor {
  private child: SpawnedProcess | undefined;
  private readonly ports: ReviewSidecarPorts;

  constructor(ports: ReviewSidecarPorts) {
    this.ports = ports;
  }

  async start(spec: ReviewSidecarSpec): Promise<void> {
    if (this.child !== undefined) {
      throw new Error("review sidecar is already running");
    }
    const child = this.ports.spawn(
      spec.python,
      [
        "-m",
        "uvicorn",
        spec.module,
        "--host",
        "127.0.0.1",
        "--port",
        String(spec.port),
      ],
      { cwd: spec.cwd },
    );
    this.child = child;
    const healthUrl = `http://127.0.0.1:${spec.port}${spec.healthPath}`;
    try {
      await Promise.race([
        this.ports.waitForReady(healthUrl),
        this.ports.waitForExit(child).then((error) => Promise.reject(error)),
      ]);
    } catch (error) {
      child.kill();
      this.child = undefined;
      throw error;
    }
  }

  async stop(): Promise<void> {
    this.child?.kill();
    this.child = undefined;
  }
}
