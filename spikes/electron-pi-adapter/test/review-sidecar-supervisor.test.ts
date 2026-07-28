import assert from "node:assert/strict";
import test from "node:test";

import { ReviewSidecarSupervisor } from "../src/review-sidecar-supervisor.ts";

test("starts the review sidecar, waits for readiness, then terminates it", async () => {
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
  });

  await supervisor.start({
    python: "/bundle/python",
    module: "pydexpi_datalog.web.asgi:app",
    cwd: "/bundle/app",
    healthUrl: "http://127.0.0.1:8000/openapi.json",
  });
  await supervisor.stop();

  assert.deepEqual(calls, [
    "spawn:/bundle/python:-m,uvicorn,pydexpi_datalog.web.asgi:app,--host,127.0.0.1,--port,8000:/bundle/app",
    "ready:http://127.0.0.1:8000/openapi.json",
  ]);
  assert.equal(killed, true);
});
