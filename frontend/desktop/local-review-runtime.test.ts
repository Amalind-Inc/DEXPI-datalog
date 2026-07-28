import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { startLocalReviewRuntime } from "./local-review-runtime.ts";

const HEALTHY_SERVER = `
  const http = require("node:http");
  const server = http.createServer((request, response) => {
    if (request.url === "/health") {
      response.writeHead(200).end("ok");
      return;
    }
    response.writeHead(404).end();
  });
  server.listen(0, "127.0.0.1", () => {
    process.stdout.write(String(server.address().port) + "\\n");
  });
  process.on("SIGTERM", () => server.close(() => process.exit(0)));
`;

const LOCAL_PROFILE_SERVER = `
  if (process.env.HARBORFIELD_DEPLOYMENT_PROFILE !== "local") {
    process.exit(2);
  }
  ${HEALTHY_SERVER}
`;

const SILENT_SERVER = `
  const fs = require("node:fs");
  const net = require("node:net");
  const server = net.createServer().listen(0, "127.0.0.1");
  process.on("SIGTERM", () => {
    fs.writeFileSync(process.env.TERMINATION_MARKER, "stopped");
    server.close(() => process.exit(0));
  });
`;

test("starts a loopback review sidecar only after its health endpoint responds", async () => {
  const runtime = await startLocalReviewRuntime({
    command: process.execPath,
    args: ["-e", HEALTHY_SERVER],
    endpointFromStdout: (line) => `http://127.0.0.1:${line.trim()}`,
    healthPath: "/health",
  });

  try {
    const response = await fetch(`${runtime.endpoint}/health`);
    assert.equal(response.status, 200);
  } finally {
    await runtime.stop();
  }
});

test("passes the local deployment profile to the supervised sidecar", async () => {
  const runtime = await startLocalReviewRuntime({
    command: process.execPath,
    args: ["-e", LOCAL_PROFILE_SERVER],
    environment: { HARBORFIELD_DEPLOYMENT_PROFILE: "local" },
    endpointFromStdout: (line) => `http://127.0.0.1:${line.trim()}`,
    healthPath: "/health",
  });

  await runtime.stop();
});

test("terminates a silent sidecar when it cannot publish an endpoint by the startup deadline", async () => {
  const marker = join(tmpdir(), `portlog-sidecar-${process.pid}-${Date.now()}`);
  await writeFile(marker, "");
  await rm(marker);

  await assert.rejects(
    startLocalReviewRuntime({
      command: process.execPath,
      args: ["-e", SILENT_SERVER],
      environment: { TERMINATION_MARKER: marker },
      endpointFromStdout: () => null,
      healthPath: "/health",
      startupTimeoutMs: 50,
    }),
    /did not publish an endpoint.*50ms/i,
  );

  assert.equal(existsSync(marker), true, "the timed-out sidecar receives SIGTERM");
  await rm(marker);
});
