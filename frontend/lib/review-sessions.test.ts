import assert from "node:assert/strict";
import test from "node:test";
import { listReviewSessions } from "./review-backend.ts";

function fakeFetcher(body: unknown, status = 200) {
  return async () =>
    ({
      status,
      json: async () => body,
    }) as unknown as Response;
}

test("listReviewSessions: returns the catalog's sessions", async () => {
  const result = await listReviewSessions({
    baseUrl: "http://backend",
    fetcher: fakeFetcher({
      sessions: [
        {
          session_id: "s1",
          source_filename: "E06.xml",
          created_at: "2026-07-24T00:00:00Z",
          artifact_prefix: "local/s1",
        },
      ],
    }),
  });

  assert.equal(result.status, 200);
  assert.equal(result.sessions.length, 1);
  assert.equal(result.sessions[0].session_id, "s1");
  assert.equal(result.sessions[0].source_filename, "E06.xml");
});

test("listReviewSessions: tolerates a body with no sessions key", async () => {
  const result = await listReviewSessions({
    baseUrl: "http://backend",
    fetcher: fakeFetcher({}),
  });

  assert.deepEqual(result.sessions, []);
});
