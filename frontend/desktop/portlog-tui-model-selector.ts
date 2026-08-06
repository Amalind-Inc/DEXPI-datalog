const MODEL_CONTROL_PATTERN = /[\u0000-\u001f\u007f-\u009f]/u;

export const SUPPORTED_TUI_PROVIDERS = ["openrouter", "anthropic", "openai-codex"] as const;

export type TuiModelProvider = (typeof SUPPORTED_TUI_PROVIDERS)[number];

export interface TuiModelSelection {
  readonly provider: TuiModelProvider;
  readonly model: string;
}

export interface TuiModelChoice extends TuiModelSelection {
  readonly label: string;
}
export interface TuiCurrentModelSelection {
  readonly provider: string;
  readonly model: string;
}

export function parseTuiModelSpec(value: string): TuiModelSelection | undefined {
  const separator = value.indexOf(":");
  if (separator < 1) return undefined;
  const provider = value.slice(0, separator).trim();
  const model = value.slice(separator + 1).trim();
  if (!isSupportedProvider(provider) || !isSafeTuiText(model)) return undefined;
  return { provider, model };
}

export type TuiCommand = "model" | "unknown";

export function parseTuiCommand(value: string): TuiCommand | undefined {
  const normalized = value.trim();
  if (normalized === "/model") return "model";
  if (normalized.startsWith("/")) return "unknown";
  return undefined;
}

export function buildTuiModelChoices(
  current: TuiCurrentModelSelection,
  configuredRaw = "",
): readonly TuiModelChoice[] {
  const selections = [
    toTuiModelSelection(current),
    ...configuredRaw.split(",").map(parseTuiModelSpec).filter(isSelection),
  ].filter(isSafeSelection);
  const seen = new Set<string>();
  return selections.flatMap((selection) => {
    const key = `${selection.provider}:${selection.model}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ ...selection, label: `${selection.provider} / ${selection.model}` }];
  });
}

export function parseTuiModelSelection(
  value: string,
  choices: readonly TuiModelChoice[],
): TuiModelSelection | undefined {
  const normalized = value.trim();
  if (!normalized) return undefined;
  if (/^\d+$/.test(normalized)) {
    const choice = choices[Number(normalized) - 1];
    return choice ? { provider: choice.provider, model: choice.model } : undefined;
  }
  return parseTuiModelSpec(normalized);
}

function isSupportedProvider(value: string): value is TuiModelProvider {
  return (SUPPORTED_TUI_PROVIDERS as readonly string[]).includes(value);
}
function isSelection(value: TuiModelSelection | undefined): value is TuiModelSelection {
  return value !== undefined;
}

function isSafeTuiText(value: string): boolean {
  return value.length > 0 && !MODEL_CONTROL_PATTERN.test(value);
}

function isSafeSelection(value: TuiModelSelection | undefined): value is TuiModelSelection {
  return isSelection(value) && isSafeTuiText(value.provider) && isSafeTuiText(value.model);
}
function toTuiModelSelection(value: TuiCurrentModelSelection): TuiModelSelection | undefined {
  if (
    !isSupportedProvider(value.provider) ||
    !isSafeTuiText(value.provider) ||
    !isSafeTuiText(value.model)
  )
    return undefined;
  return { provider: value.provider, model: value.model };
}
