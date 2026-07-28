import assert from "node:assert/strict";
import test from "node:test";

import { SessionManager } from "@earendil-works/pi-coding-agent";

test("constructs the pinned upstream Pi in-memory session manager without credentials", () => {
  const manager = SessionManager.inMemory(process.cwd());

  assert.ok(manager);
  assert.equal(typeof manager, "object");
});
