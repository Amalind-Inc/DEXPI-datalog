import assert from "node:assert/strict";
import test from "node:test";

import { persistDocumentSelection } from "./document-selection.ts";

test("rejected active-source persistence restores the prior local selection", async () => {
  let localActive = "source-a";
  let durableActive = "source-a";
  const result = await persistDocumentSelection({
    activate: () => {
      localActive = "source-b";
    },
    restore: () => {
      localActive = "source-a";
    },
    request: async () => ({ ok: false }),
  });

  assert.equal(result, false);
  assert.equal(localActive, "source-a");
  assert.equal(durableActive, "source-a");
});

test("unreachable active-source persistence restores the prior local selection", async () => {
  let localActive = "source-a";
  const result = await persistDocumentSelection({
    activate: () => {
      localActive = "source-b";
    },
    restore: () => {
      localActive = "source-a";
    },
    request: async () => {
      throw new TypeError("fetch failed");
    },
  });

  assert.equal(result, false);
  assert.equal(localActive, "source-a");
});

test("an obsolete failed write cannot roll back a newer selection", async () => {
  let localActive = "source-a";
  let current = 1;
  let resolveRequest!: (response: { ok: boolean }) => void;
  const request = new Promise<{ ok: boolean }>((resolve) => {
    resolveRequest = resolve;
  });
  const first = persistDocumentSelection({
    activate: () => {
      localActive = "source-b";
    },
    restore: () => {
      localActive = "source-a";
    },
    request: async () => request,
    isCurrent: () => current === 1,
  });

  current = 2;
  localActive = "source-c";
  resolveRequest({ ok: false });

  assert.equal(await first, false);
  assert.equal(localActive, "source-c");
});
