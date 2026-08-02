export type ExecutionDetailLevel = "concise" | "standard" | "detailed";

export const EXECUTION_DETAIL_LEVELS = ["concise", "standard", "detailed"] as const;
export const DEFAULT_EXECUTION_DETAIL_LEVEL: ExecutionDetailLevel = "standard";
export const EXECUTION_DETAIL_STORAGE_KEY = "pydexpi.executionDetail.v1";

export const EXECUTION_DETAIL_OPTIONS: ReadonlyArray<{
  value: ExecutionDetailLevel;
  label: string;
  description: string;
}> = [
  {
    value: "concise",
    label: "Concise",
    description: "Answer and evidence summary",
  },
  {
    value: "standard",
    label: "Standard",
    description: "Named steps and execution summaries",
  },
  {
    value: "detailed",
    label: "Detailed",
    description: "Sanitized inputs, outputs, and trace artifacts",
  },
];

type ExecutionDetailStorage = Pick<Storage, "getItem" | "setItem">;

export function readExecutionDetailLevel(
  storage: ExecutionDetailStorage | null | undefined = readBrowserStorage(),
): ExecutionDetailLevel {
  try {
    const value = storage?.getItem(EXECUTION_DETAIL_STORAGE_KEY);
    return isExecutionDetailLevel(value) ? value : DEFAULT_EXECUTION_DETAIL_LEVEL;
  } catch {
    return DEFAULT_EXECUTION_DETAIL_LEVEL;
  }
}

export function writeExecutionDetailLevel(
  storage: ExecutionDetailStorage | null | undefined,
  value: ExecutionDetailLevel,
): void {
  if (!isExecutionDetailLevel(value)) return;
  try {
    (storage ?? readBrowserStorage())?.setItem(EXECUTION_DETAIL_STORAGE_KEY, value);
  } catch {
    // A blocked or unavailable localStorage must not affect chat rendering.
  }
}

export function isExecutionDetailLevel(value: unknown): value is ExecutionDetailLevel {
  return (
    typeof value === "string" && (EXECUTION_DETAIL_LEVELS as readonly string[]).includes(value)
  );
}

const MAX_DETAIL_STRING_LENGTH = 400;
const MAX_DETAIL_DEPTH = 3;
const MAX_DETAIL_KEYS = 16;
const MAX_DETAIL_ITEMS = 10;
const BLOCKED_DETAIL_KEY_PARTS = [
  "api_key",
  "authorization",
  "chain_of_thought",
  "credential",
  "password",
  "private",
  "secret",
  "system_prompt",
  "token",
];

/**
 * Defense-in-depth projection for values that the backend has already
 * sanitized. The UI must not accidentally turn a malformed or future payload
 * into a secret, hidden-reasoning, or unbounded disclosure.
 */
export function sanitizeExecutionDetailValue(value: unknown, depth = 0): unknown {
  if (value === null || typeof value === "boolean" || typeof value === "number") {
    return value;
  }
  if (typeof value === "string") return value.slice(0, MAX_DETAIL_STRING_LENGTH);
  if (depth >= MAX_DETAIL_DEPTH) return undefined;
  if (Array.isArray(value)) {
    return value
      .slice(0, MAX_DETAIL_ITEMS)
      .map((item) => sanitizeExecutionDetailValue(item, depth + 1))
      .filter((item) => item !== undefined);
  }
  if (typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value).slice(0, MAX_DETAIL_KEYS)) {
      const lowered = key.toLowerCase();
      if (BLOCKED_DETAIL_KEY_PARTS.some((part) => lowered.includes(part))) continue;
      const sanitized = sanitizeExecutionDetailValue(item, depth + 1);
      if (sanitized !== undefined) result[key] = sanitized;
    }
    return result;
  }
  return undefined;
}

function readBrowserStorage(): ExecutionDetailStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

type Storage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
};
