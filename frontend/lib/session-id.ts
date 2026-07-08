export const SESSION_KEY = "pydexpi.pidQa.sessionId.v1";

export function readOrCreateSessionId(): string {
  if (typeof window === "undefined") return `pid-${crypto.randomUUID()}`;
  const existing = window.localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const created = `pid-${crypto.randomUUID()}`;
  window.localStorage.setItem(SESSION_KEY, created);
  return created;
}
