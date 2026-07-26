import assert from "node:assert/strict";
import test from "node:test";

import { createPidLatencyTrace } from "./pid-latency-trace.ts";

test("P&ID latency trace separates browser phases and preserves server metrics", () => {
  const ticks = [100, 112, 170, 185, 189, 193, 240, 255];
  const trace = createPidLatencyTrace({
    filename: "plant.xml",
    uploadBytes: 4096,
    now: () => ticks.shift() ?? 255,
  });

  trace.endPhase("file_read");
  trace.endPhase("upload_proxy");
  trace.endPhase("response_transfer");
  trace.endPhase("json_decode");
  trace.setServerMetrics({
    schema_version: 1,
    total_ms: 51,
    phases_ms: { xml_parse: 12, graph_extraction: 18 },
    counts: { graph_nodes: 18, graph_edges: 21 },
  });
  trace.endPhase("state_apply");
  trace.endPhase("layout");
  trace.complete({ svgElements: 85, renderedEntities: 39, responseBytes: 8192 });

  assert.deepEqual(trace.snapshot(), {
    schemaVersion: 1,
    status: "interactive",
    filename: "plant.xml",
    totalMs: 155,
    phasesMs: {
      file_read: 12,
      upload_proxy: 58,
      response_transfer: 15,
      json_decode: 4,
      state_apply: 4,
      layout: 47,
      react_commit_to_interactive: 15,
    },
    server: {
      schema_version: 1,
      total_ms: 51,
      phases_ms: { xml_parse: 12, graph_extraction: 18 },
      counts: { graph_nodes: 18, graph_edges: 21 },
    },
    counts: {
      uploadBytes: 4096,
      responseBytes: 8192,
      renderedEntities: 39,
      svgElements: 85,
    },
  });
});
