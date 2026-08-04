export const PUMP_DISCHARGE_CHECK_ID = "pump_discharge_check_valve" as const;

export type AskChoice = {
  id: "all-centrifugal-pumps" | "connected-objects" | "applicable-equipment";
  label: string;
  question: string;
};

export type AskRoute =
  | { kind: "evidence"; posture: "inspect" }
  | {
      kind: "rule";
      posture: "verify";
      checkId: typeof PUMP_DISCHARGE_CHECK_ID;
      scopeEntityId: string;
    }
  | {
      kind: "universal_rule";
      posture: "verify";
      checkId: typeof PUMP_DISCHARGE_CHECK_ID;
      domain: "centrifugal_pumps";
    }
  | {
      kind: "clarification";
      posture: "inspect";
      prompt: string;
      choices: AskChoice[];
    };

const ENTITY_IDENTIFIER = /\b[A-Za-z]+[-_]?\d+(?:[\/._-][A-Za-z0-9]+)*/g;
const RULE_LANGUAGE = /\b(check[\s-]?valve|discharge|downstream|rule)\b/i;
const UNIVERSAL_LANGUAGE = /\b(all|every|each)\b/i;
const PUMP_IDENTIFIER = /^p[-_]?\d+/i;
const PUMP_LANGUAGE = /\b(centrifugal\s+)?pumps?\b/i;
const CONNECTED_LANGUAGE = /\bconnected\b/i;

export function routeLocalAsk(question: string): AskRoute {
  const normalized = question.trim();
  const identifiers = extractEntityIdentifiers(normalized);
  const universal = UNIVERSAL_LANGUAGE.test(normalized);
  const asksAboutRule = RULE_LANGUAGE.test(normalized);
  const asksAboutPump = PUMP_LANGUAGE.test(normalized);
  const asksAboutConnectedObjects = CONNECTED_LANGUAGE.test(normalized);

  if (universal && asksAboutConnectedObjects) return clarificationRoute(normalized, identifiers[0]);

  if (universal && asksAboutPump && asksAboutRule) {
    return {
      kind: "universal_rule",
      posture: "verify",
      checkId: PUMP_DISCHARGE_CHECK_ID,
      domain: "centrifugal_pumps",
    };
  }

  if (asksAboutRule) {
    if (identifiers.length === 1 && PUMP_IDENTIFIER.test(identifiers[0])) {
      return {
        kind: "rule",
        posture: "verify",
        checkId: PUMP_DISCHARGE_CHECK_ID,
        scopeEntityId: identifiers[0],
      };
    }
    return clarificationRoute(normalized, identifiers[0]);
  }

  return { kind: "evidence", posture: "inspect" };
}

export function extractEntityIdentifiers(question: string): string[] {
  return Array.from(new Set(question.match(ENTITY_IDENTIFIER) ?? []));
}

function clarificationRoute(question: string, identifier: string | undefined): AskRoute {
  const pumpId = identifier && PUMP_IDENTIFIER.test(identifier) ? identifier : "P-4713";
  return {
    kind: "clarification",
    posture: "inspect",
    prompt:
      "I can help evaluate this, but I need a precise scope. The supported pump discharge rule applies to one centrifugal pump or to all centrifugal pumps.",
    choices: [
      {
        id: "all-centrifugal-pumps",
        label: "All centrifugal pumps",
        question:
          "Do all centrifugal pumps in the prepared topology have a downstream check valve?",
      },
      {
        id: "connected-objects",
        label: `Objects connected to ${pumpId}`,
        question: `What objects are connected to ${pumpId}?`,
      },
      {
        id: "applicable-equipment",
        label: "All equipment using applicable rules",
        question: "Which applicable rules can be evaluated for the prepared equipment?",
      },
    ],
  };
}

export function enumerateCentrifugalPumpScopes(payload: unknown): string[] {
  const source =
    isRecord(payload) && isRecord(payload.topology_view) ? payload.topology_view : payload;
  const nodes = isRecord(source) && Array.isArray(source.nodes) ? source.nodes : [];
  return Array.from(
    new Set(
      nodes
        .filter((node) => {
          if (!isRecord(node)) return false;
          const className = String(
            node.class_name ?? node.className ?? node.class ?? node.kind ?? "",
          )
            .toLowerCase()
            .replace(/[^a-z]/g, "");
          return className.includes("centrifugalpump");
        })
        .map((node) => {
          if (!isRecord(node)) return "";
          return String(node.tag_name ?? node.display_name ?? node.label ?? node.id ?? "");
        })
        .filter(Boolean),
    ),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
