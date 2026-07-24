// Browser-side storage for bring-your-own-key credentials.
//
// Keys live in this browser only: nothing is persisted server-side, and a
// credential leaves the machine solely as the body of the provider-settings
// call the turn route forwards to the Python backend (ADR 0014).
//
// This module is deliberately ignorant of *which* providers exist. The
// provider/model set comes from the vendored models.dev catalogue at runtime
// (byok-catalog.ts, ADR 0015), and the server re-validates every payload, so
// gatekeeping here would only duplicate that check and go stale.

export const BYOK_STORAGE_KEY = "pydexpi.byok.v1";

export type ByokKeyEntry = {
  credential: string;
  model: string;
  /** Epoch millis, for the "added <date>" column. */
  savedAt: number;
  /** A local model server authenticates by endpoint, not by credential. */
  isLocal?: boolean;
};

export type ByokStore = {
  activeProvider: string | null;
  keys: Record<string, ByokKeyEntry>;
};

export type BackendProviderSettings = {
  provider: string;
  model: string;
  credential: string;
};

/** Shows enough of a key to recognise it, never enough to use it. */
export function maskCredential(credential: string): string {
  const trimmed = credential.trim();
  if (trimmed.length <= 8) return "…";
  return `${trimmed.slice(0, 4)}…${trimmed.slice(-4)}`;
}

function storageOrNull(explicit?: Storage): Storage | null {
  if (explicit) return explicit;
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    // Private-mode / blocked storage: BYOK degrades to "no stored keys".
    return null;
  }
}

export function readByokStore(storage?: Storage): ByokStore {
  const target = storageOrNull(storage);
  if (!target) return { activeProvider: null, keys: {} };

  let parsed: unknown;
  try {
    const raw = target.getItem(BYOK_STORAGE_KEY);
    if (!raw) return { activeProvider: null, keys: {} };
    parsed = JSON.parse(raw);
  } catch {
    return { activeProvider: null, keys: {} };
  }
  if (typeof parsed !== "object" || parsed === null) return { activeProvider: null, keys: {} };

  const record = parsed as Record<string, unknown>;
  const keys: Record<string, ByokKeyEntry> = {};
  const rawKeys = record.keys;
  if (typeof rawKeys === "object" && rawKeys !== null && !Array.isArray(rawKeys)) {
    for (const [providerId, value] of Object.entries(rawKeys as Record<string, unknown>)) {
      if (typeof value !== "object" || value === null) continue;
      const entry = value as Record<string, unknown>;
      const model = typeof entry.model === "string" ? entry.model.trim() : "";
      if (!model) continue;
      const credential = typeof entry.credential === "string" ? entry.credential.trim() : "";
      const isLocal = entry.isLocal === true;
      if (!credential && !isLocal) continue;
      keys[providerId] = {
        credential,
        model,
        savedAt: typeof entry.savedAt === "number" ? entry.savedAt : 0,
        ...(isLocal ? { isLocal: true } : {}),
      };
    }
  }

  const active = record.activeProvider;
  return {
    activeProvider: typeof active === "string" && keys[active] ? active : null,
    keys,
  };
}

function writeByokStore(store: ByokStore, storage?: Storage): ByokStore {
  const target = storageOrNull(storage);
  if (target) target.setItem(BYOK_STORAGE_KEY, JSON.stringify(store));
  return store;
}

export function saveByokKey(
  input: { provider: string; credential: string; model: string; isLocal?: boolean },
  storage?: Storage,
): ByokStore {
  const credential = input.credential.trim();
  const model = input.model.trim();
  if (!model) throw new Error("Choose a model before saving this provider.");
  if (!credential && !input.isLocal) {
    throw new Error("A credential is required to save a provider key.");
  }

  const current = readByokStore(storage);
  const keys = {
    ...current.keys,
    [input.provider]: {
      credential,
      model,
      savedAt: Date.now(),
      ...(input.isLocal ? { isLocal: true } : {}),
    },
  };
  // First key wins the active slot; later keys are added without hijacking a
  // provider the user already chose to run with.
  const activeProvider = current.activeProvider ?? input.provider;
  return writeByokStore({ activeProvider, keys }, storage);
}

export function selectActiveProvider(provider: string, storage?: Storage): ByokStore {
  const current = readByokStore(storage);
  if (!current.keys[provider]) throw new Error(`${provider} has no stored key to activate.`);
  return writeByokStore({ ...current, activeProvider: provider }, storage);
}

export function setProviderModel(provider: string, model: string, storage?: Storage): ByokStore {
  const trimmed = model.trim();
  if (!trimmed) throw new Error("Choose a model.");
  const current = readByokStore(storage);
  const entry = current.keys[provider];
  if (!entry) throw new Error(`${provider} has no stored key.`);
  return writeByokStore(
    { ...current, keys: { ...current.keys, [provider]: { ...entry, model: trimmed } } },
    storage,
  );
}

export function clearByokKey(provider: string, storage?: Storage): ByokStore {
  const current = readByokStore(storage);
  const keys = { ...current.keys };
  delete keys[provider];
  const activeProvider =
    current.activeProvider === provider
      ? // Dropping the active key promotes whichever key is still around, so the
        // assistant keeps working instead of silently reverting to the stub.
        (Object.keys(keys)[0] ?? null)
      : current.activeProvider;
  return writeByokStore({ activeProvider, keys }, storage);
}

export function providerSettingsFromStore(store: ByokStore): BackendProviderSettings | null {
  const provider = store.activeProvider;
  if (!provider) return null;
  const entry = store.keys[provider];
  if (!entry) return null;
  return { provider, model: entry.model, credential: entry.credential };
}
