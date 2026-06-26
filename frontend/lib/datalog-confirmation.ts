export const DATALOG_CONFIRMATION_PREFIX = "pydexpi:datalog-confirmation:";

export type DatalogConfirmationState = {
  plainLanguageMeaning: string;
  generatedDatalog: string;
  validationStatus: string;
  allowedActions: string[];
  raw: Record<string, unknown>;
};

export function serializeDatalogConfirmation(state: DatalogConfirmationState) {
  return `${DATALOG_CONFIRMATION_PREFIX}${JSON.stringify(state)}`;
}

export function parseDatalogConfirmationMessage(text: string): DatalogConfirmationState | null {
  if (!text.startsWith(DATALOG_CONFIRMATION_PREFIX)) return null;
  try {
    const parsed = JSON.parse(text.slice(DATALOG_CONFIRMATION_PREFIX.length));
    if (!isRecord(parsed)) return null;
    if (typeof parsed.plainLanguageMeaning !== "string") return null;
    if (typeof parsed.generatedDatalog !== "string") return null;
    if (typeof parsed.validationStatus !== "string") return null;
    if (!Array.isArray(parsed.allowedActions)) return null;
    if (!parsed.allowedActions.every((action) => typeof action === "string")) {
      return null;
    }
    return {
      plainLanguageMeaning: parsed.plainLanguageMeaning,
      generatedDatalog: parsed.generatedDatalog,
      validationStatus: parsed.validationStatus,
      allowedActions: parsed.allowedActions,
      raw: isRecord(parsed.raw) ? parsed.raw : {},
    };
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
