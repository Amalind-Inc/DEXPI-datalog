import assert from "node:assert/strict";
import test from "node:test";

import { ReviewSidecarSupervisor } from "../src/review-sidecar-supervisor.ts";

test("uses one allocated port for Uvicorn and readiness, then terminates the sidecar", async () => {
  const calls: string[] = [];
  let killed = false;
  const supervisor = new ReviewSidecarSupervisor({
    spawn(command, args, options) {
      calls.push(`spawn:${command}:${args.join(",")}:${options.cwd}`);
      return { kill: () => { killed = true; } };
    },
    async waitForReady(url) {
      calls.push(`ready:${url}`);
    },
    waitForExit() {
      return new Promise<never>(() => {});
    },
  });

  await supervisor.start({
    python: "/bundle/python",
    module: "pydexpi_datalog.web.asgi:app",
    cwd: "/bundle/app",
    port: 8123,
    healthPath: "/openapi.json",
  });
  await supervisor.stop();

  assert.deepEqual(calls, [
    "spawn:/bundle/python:-m,uvicorn,pydexpi_datalog.web.asgi:app,--host,127.0.0.1,--port,8123:/bundle/app",
    "ready:http://127.0.0.1:8123/openapi.json",
  ]);
  assert.equal(killed, true);
});

test("fails instead of accepting readiness after the child exits", async () => {
  let killed = false;
  const supervisor = new ReviewSidecarSupervisor({
    spawn() {
      return { kill: () => { killed = true; } };
    },
    async waitForReady() {
      return new Promise<void>(() => {});
    },
    waitForExit() {
      return Promise.resolve(new Error("sidecar exited: 1"));
    },
  });

  await assert.rejects(
    supervisor.start({
      python: "/bundle/python",
      module: "pydexpi_datalog.web.asgi:app",
      cwd: "/bundle/app",
      port: 8123,
      healthPath: "/openapi.json",
    }),
    /sidecar exited: 1/,
  );
  assert.equal(killed, true);
});
