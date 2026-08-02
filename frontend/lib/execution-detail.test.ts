import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_EXECUTION_DETAIL_LEVEL,
  EXECUTION_DETAIL_LEVELS,
  EXECUTION_DETAIL_STORAGE_KEY,
  readExecutionDetailLevel,
  sanitizeExecutionDetailValue,
  writeExecutionDetailLevel,
} from "./execution-detail.ts";

function memoryStorage(initial: string | null = null): Storage {
  let value = initial;
  return {
    getItem: () => value,
    setItem: (_key, next) => {
      value = next;
    },
    removeItem: () => {
      value = null;
    },
    clear: () => {
      value = null;
    },
    key: () => null,
    length: 0,
  };
}

test("execution detail preference exposes the three supported levels", () => {
  assert.deepEqual(EXECUTION_DETAIL_LEVELS, ["concise", "standard", "detailed"]);
  assert.equal(DEFAULT_EXECUTION_DETAIL_LEVEL, "standard");
});

test("execution detail preference falls back safely for missing or invalid storage", () => {
  assert.equal(readExecutionDetailLevel(memoryStorage()), DEFAULT_EXECUTION_DETAIL_LEVEL);
  assert.equal(readExecutionDetailLevel(memoryStorage("verbose")), DEFAULT_EXECUTION_DETAIL_LEVEL);
});

test("execution detail preference persists only supported values", () => {
  const storage = memoryStorage();

  writeExecutionDetailLevel(storage, "detailed");

  assert.equal(storage.getItem(EXECUTION_DETAIL_STORAGE_KEY), "detailed");
  assert.equal(readExecutionDetailLevel(storage), "detailed");
});

test("execution detail sanitizer drops secrets and bounds disclosure values", () => {
  assert.deepEqual(
    sanitizeExecutionDetailValue({
      equipment_id: "pump-1",
      api_key: "secret",
      nested: { authorization: "Bearer secret", safe: "visible" },
    }),
    {
      equipment_id: "pump-1",
      nested: { safe: "visible" },
    },
  );
});
