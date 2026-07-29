import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { readFile, mkdtemp, rm } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const repositoryRoot = join(import.meta.dirname, "../../..");
const fixture = join(repositoryRoot, "TrainingTestCases/dexpi 1.3/example pids/E06 Pump, HeatExchanger, Nozzles Connected With PNS/E06V01-VER.EX01.xml");

async function freePort(): Promise<number> {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") return reject(new Error("no loopback port"));
      server.close((error) => error ? reject(error) : resolve(address.port));
    });
  });
}

async function start(port: number, artifacts: string): Promise<ChildProcess> {
  const child = spawn(process.env.PYTHON ?? join(repositoryRoot, ".venv/bin/python"), ["-m", "uvicorn", "pydexpi_datalog.web.asgi:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: repositoryRoot,
    env: { ...process.env, HARBORFIELD_DEPLOYMENT_PROFILE: "local", HARBORFIELD_REVIEW_ARTIFACT_ROOT: artifacts },
    stdio: "ignore",
  });
  const endpoint = `http://127.0.0.1:${port}/openapi.json`;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(endpoint)).ok) return child; } catch { /* process is not ready */ }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  child.kill("SIGTERM");
  throw new Error("local PortLog sidecar did not become ready");
}

async function stop(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await new Promise<void>((resolve) => child.once("exit", () => resolve()));
}

test("real local sidecar prepares a DEXPI review and restores topology after restart", { timeout: 30_000 }, async () => {
  const artifacts = await mkdtemp(join(tmpdir(), "portlog-sidecar-artifacts-"));
  const port = await freePort();
  const source = await readFile(fixture, "utf8");
  let first: ChildProcess | undefined;
  let second: ChildProcess | undefined;
  try {
    first = await start(port, artifacts);
    const prepared = await fetch(`http://127.0.0.1:${port}/api/review/sessions/desktop-reopen/prepare`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ filename: "E06.xml", content: source }) });
    assert.equal(prepared.status, 200);
    const initial = await prepared.json() as { topology_view: { nodes: unknown[] } };
    assert.ok(initial.topology_view.nodes.length > 0);
    await stop(first); first = undefined;
    second = await start(port, artifacts);
    const restored = await fetch(`http://127.0.0.1:${port}/api/review/sessions/desktop-reopen/topology`);
    assert.equal(restored.status, 200);
    const topology = await restored.json() as { graph_objects: unknown[] };
    assert.ok(topology.graph_objects.length > 0);
  } finally {
    if (first) await stop(first);
    if (second) await stop(second);
    await rm(artifacts, { recursive: true, force: true });
  }
});
