// Bring-your-own-key storage for the LLM providers the review backend can
// drive. Keys live in the browser only: nothing is persisted server-side, and
// a credential leaves the machine solely as the body of the provider-settings
// call that the turn route forwards to the Python backend.
//
// The model lists here are not cosmetic. The backend rejects any provider/model
// pair outside NATIVE_TOOL_CAPABLE_MODELS (pydexpi_datalog/llm/model_access.py)
// because grounded QA needs native tool calls, so this catalogue must stay a
// mirror of that set.

export const BYOK_STORAGE_KEY = "pydexpi.byok.v1";

export type ByokProviderId = "openrouter" | "openai" | "anthropic" | "gemini";

export type ByokProviderInfo = {
  id: ByokProviderId;
  label: string;
  /** Where a user goes to mint the key. */
  consoleUrl: string;
  /** Shape hint shown under the input, and used for the soft format warning. */
  keyPrefix: string;
  models: string[];
  defaultModel: string;
};

export const BYOK_PROVIDERS: ByokProviderInfo[] = [
  {
    id: "openrouter",
    label: "OpenRouter",
    consoleUrl: "https://openrouter.ai/keys",
    keyPrefix: "sk-or-",
    models: ["anthropic/claude-sonnet-4", "deepseek/deepseek-v4-pro"],
    defaultModel: "anthropic/claude-sonnet-4",
  },
  {
    id: "openai",
    label: "OpenAI",
    consoleUrl: "https://platform.openai.com/api-keys",
    keyPrefix: "sk-",
    models: ["gpt-4.1"],
    defaultModel: "gpt-4.1",
  },
  {
    id: "anthropic",
    label: "Anthropic (Claude)",
    consoleUrl: "https://console.anthropic.com/settings/keys",
    keyPrefix: "sk-ant-",
    models: ["claude-sonnet-4"],
    defaultModel: "claude-sonnet-4",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    consoleUrl: "https://aistudio.google.com/app/apikey",
    keyPrefix: "AIza",
    models: ["gemini-2.5-pro"],
    defaultModel: "gemini-2.5-pro",
  },
];

const PROVIDER_BY_ID: Record<string, ByokProviderInfo> = Object.fromEntries(
  BYOK_PROVIDERS.map((entry) => [entry.id, entry]),
);

export type ByokKeyEntry = {
  credential: string;
  model: string;
  /** Epoch millis, for the "added <date>" column. */
  savedAt: number;
};

export type ByokStore = {
  activeProvider: ByokProviderId | null;
  keys: Partial<Record<ByokProviderId, ByokKeyEntry>>;
};

export type BackendProviderSettings = {
  provider: ByokProviderId;
  model: string;
  credential: string;
};

const EMPTY_STORE: ByokStore = { activeProvider: null, keys: {} };

export function byokProvider(id: ByokProviderId): ByokProviderInfo {
  const info = PROVIDER_BY_ID[id];
  if (!info) throw new Error(`unknown BYOK provider: ${id}`);
  return info;
}

export function isByokProviderId(value: unknown): value is ByokProviderId {
  return typeof value === "string" && value in PROVIDER_BY_ID;
}

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
  if (!target) return { ...EMPTY_STORE, keys: {} };

  let parsed: unknown;
  try {
    const raw = target.getItem(BYOK_STORAGE_KEY);
    if (!raw) return { ...EMPTY_STORE, keys: {} };
    parsed = JSON.parse(raw);
  } catch {
    return { ...EMPTY_STORE, keys: {} };
  }
  if (typeof parsed !== "object" || parsed === null) return { ...EMPTY_STORE, keys: {} };

  const record = parsed as Record<string, unknown>;
  const keys: ByokStore["keys"] = {};
  const rawKeys = record.keys;
  if (typeof rawKeys === "object" && rawKeys !== null && !Array.isArray(rawKeys)) {
    for (const [providerId, value] of Object.entries(rawKeys as Record<string, unknown>)) {
      if (!isByokProviderId(providerId)) continue;
      if (typeof value !== "object" || value === null) continue;
      const entry = value as Record<string, unknown>;
      const credential = typeof entry.credential === "string" ? entry.credential.trim() : "";
      if (!credential) continue;
      const info = byokProvider(providerId);
      const model =
        typeof entry.model === "string" && info.models.includes(entry.model)
          ? entry.model
          : info.defaultModel;
      keys[providerId] = {
        credential,
        model,
        savedAt: typeof entry.savedAt === "number" ? entry.savedAt : 0,
      };
    }
  }

  const active = record.activeProvider;
  return {
    activeProvider: isByokProviderId(active) && keys[active] ? active : null,
    keys,
  };
}

function writeByokStore(store: ByokStore, storage?: Storage): ByokStore {
  const target = storageOrNull(storage);
  if (target) target.setItem(BYOK_STORAGE_KEY, JSON.stringify(store));
  return store;
}

export function saveByokKey(
  input: { provider: ByokProviderId; credential: string; model?: string },
  storage?: Storage,
): ByokStore {
  const info = byokProvider(input.provider);
  const credential = input.credential.trim();
  if (!credential) throw new Error("A credential is required to save a provider key.");

  const model = input.model ?? info.defaultModel;
  if (!info.models.includes(model)) {
    throw new Error(`${info.label} cannot use model "${model}".`);
  }

  const current = readByokStore(storage);
  const keys = { ...current.keys, [input.provider]: { credential, model, savedAt: Date.now() } };
  // First key wins the active slot; later keys are added without hijacking a
  // provider the user already chose to run with.
  const activeProvider = current.activeProvider ?? input.provider;
  return writeByokStore({ activeProvider, keys }, storage);
}

export function selectActiveProvider(provider: ByokProviderId, storage?: Storage): ByokStore {
  const current = readByokStore(storage);
  if (!current.keys[provider]) {
    throw new Error(`${byokProvider(provider).label} has no stored key to activate.`);
  }
  return writeByokStore({ ...current, activeProvider: provider }, storage);
}

export function setProviderModel(
  provider: ByokProviderId,
  model: string,
  storage?: Storage,
): ByokStore {
  const info = byokProvider(provider);
  if (!info.models.includes(model)) throw new Error(`${info.label} cannot use model "${model}".`);
  const current = readByokStore(storage);
  const entry = current.keys[provider];
  if (!entry) throw new Error(`${info.label} has no stored key.`);
  return writeByokStore(
    { ...current, keys: { ...current.keys, [provider]: { ...entry, model } } },
    storage,
  );
}

export function clearByokKey(provider: ByokProviderId, storage?: Storage): ByokStore {
  const current = readByokStore(storage);
  const keys = { ...current.keys };
  delete keys[provider];
  const activeProvider =
    current.activeProvider === provider
      ? // Dropping the active key promotes whichever key is still around, so the
        // assistant keeps working instead of silently reverting to the stub.
        (BYOK_PROVIDERS.find((entry) => keys[entry.id])?.id ?? null)
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

/**
 * Validate a provider-settings payload that arrived from the browser. Keys are
 * held client-side, so the turn route receives them as untrusted request data;
 * anything that the backend's native-tool-capable allow-list would reject is
 * dropped here, letting the caller fall back to server-side configuration.
 */
export function providerSettingsFromRequest(value: unknown): BackendProviderSettings | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  const provider = record.provider;
  if (!isByokProviderId(provider)) return null;

  const credential = typeof record.credential === "string" ? record.credential.trim() : "";
  if (!credential) return null;

  const model = typeof record.model === "string" ? record.model : "";
  if (!byokProvider(provider).models.includes(model)) return null;

  return { provider, model, credential };
}
