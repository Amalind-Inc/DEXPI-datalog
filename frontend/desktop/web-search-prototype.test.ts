import assert from "node:assert/strict";
import test from "node:test";

import {
  createWebSearchTool,
  runBoundedExternalSearch,
  type ExternalSearchProvider,
} from "./web-search-prototype.ts";

const result = (title: string, url: string) => ({
  title,
  url,
  snippet: `${title} snippet`,
});

function textOf(value: { content: Array<{ type: "text"; text: string }> }): unknown {
  const text = value.content.find((part) => part.type === "text")?.text;
  assert.ok(text);
  return JSON.parse(text);
}

test("web search returns bounded ordinary untrusted external context", async () => {
  const providers: ExternalSearchProvider[] = [
    {
      id: "fixture-a",
      async search() {
        return { results: [result("A", "https://a.example/"), result("B", "https://b.example/")] };
      },
    },
  ];

  const response = await runBoundedExternalSearch(
    { query: "pump discharge", maxResults: 1 },
    providers,
    { deadlineMs: 500 },
  );

  assert.equal(response.status, "ok");
  assert.equal(response.authority, "ordinary");
  assert.equal(response.origin, "external_web");
  assert.equal(response.untrusted, true);
  assert.equal(response.pageFetch, "none");
  assert.equal(response.results.length, 1);
  assert.equal(response.truncated, true);
  assert.deepEqual(response.providers, [{ id: "fixture-a", status: "ok", resultCount: 2 }]);
});

test("partial provider failures remain visible while successful results survive", async () => {
  const providers: ExternalSearchProvider[] = [
    {
      id: "healthy",
      async search() {
        return { results: [result("Healthy", "https://healthy.example/")] };
      },
    },
    {
      id: "broken",
      async search() {
        throw new Error("provider secret must not escape");
      },
    },
  ];

  const response = await runBoundedExternalSearch({ query: "valve" }, providers, {
    deadlineMs: 500,
  });

  assert.equal(response.status, "ok");
  assert.equal(response.results[0]?.title, "Healthy");
  assert.deepEqual(response.providers, [
    { id: "healthy", status: "ok", resultCount: 1 },
    { id: "broken", status: "failed", resultCount: 0, diagnostic: "provider failure" },
  ]);
});

test("all provider failures become unavailable without a page or browser fallback", async () => {
  const providers: ExternalSearchProvider[] = [
    {
      id: "broken-a",
      async search() {
        throw new Error("nope");
      },
    },
    {
      id: "broken-b",
      async search() {
        throw new Error("nope");
      },
    },
  ];

  const response = await runBoundedExternalSearch({ query: "pump" }, providers, {
    deadlineMs: 500,
  });

  assert.equal(response.status, "unavailable");
  assert.deepEqual(response.results, []);
  assert.equal(response.pageFetch, "none");
  assert.deepEqual(
    response.providers.map(({ id, status }) => ({ id, status })),
    [
      { id: "broken-a", status: "failed" },
      { id: "broken-b", status: "failed" },
    ],
  );
});

test("provider deadlines and caller cancellation are bounded even if a provider ignores signals", async () => {
  const pending: ExternalSearchProvider = {
    id: "stuck",
    async search() {
      return await new Promise(() => {});
    },
  };

  const timedOut = await runBoundedExternalSearch({ query: "pump" }, [pending], {
    deadlineMs: 100,
  });
  assert.equal(timedOut.status, "unavailable");
  assert.deepEqual(timedOut.providers, [
    { id: "stuck", status: "timed_out", resultCount: 0, diagnostic: "provider deadline exceeded" },
  ]);

  const controller = new AbortController();
  const cancelledPromise = runBoundedExternalSearch({ query: "pump" }, [pending], {
    deadlineMs: 1_000,
    signal: controller.signal,
  });
  controller.abort();
  const cancelled = await cancelledPromise;
  assert.equal(cancelled.status, "cancelled");
  assert.deepEqual(cancelled.providers, [
    { id: "stuck", status: "cancelled", resultCount: 0, diagnostic: "search cancelled" },
  ]);
});

test("tool exposes an Oh My Pi-shaped web_search result envelope", async () => {
  const tool = createWebSearchTool({
    providers: [
      {
        id: "fixture",
        async search({ query }) {
          return { results: [result(query, "https://fixture.example/")] };
        },
      },
    ],
    deadlineMs: 500,
  });

  const response = await tool.execute("call-1", { query: "P-101", maxResults: 3 });
  const value = textOf(response) as Record<string, unknown>;

  assert.equal(tool.name, "web_search");
  assert.equal(value.status, "ok");
  assert.equal(value.authority, "ordinary");
  assert.equal(value.origin, "external_web");
  assert.equal(value.untrusted, true);
});
