/*
 * Safe local replacement for the @oh-my-pi/pi-natives calls used by PortLog's
 * vendored editor. It preserves the raw terminal key forms the editor needs
 * while avoiding the upstream Bun native extension.
 *
 * Source contracts: packages/tui/src/keys.ts and autocomplete.ts at
 * 3a8591a8af5b6d200088d12ca75a5517cb064fa8.
 */

export type KeyEventType = "press" | "repeat" | "release";

export interface ParsedKittySequence {
  readonly codepoint: number;
  readonly shiftedKey?: number;
  readonly baseLayoutKey?: number;
  readonly modifier: number;
  readonly eventType?: KeyEventType;
}

const BASIC_KEY_NAMES: Readonly<Record<number, string>> = {
  9: "tab",
  13: "enter",
  27: "escape",
  127: "backspace",
  57350: "up",
  57351: "down",
  57352: "left",
  57353: "right",
  57354: "home",
  57355: "end",
  57358: "pageUp",
  57359: "pageDown",
  57360: "insert",
  57361: "delete",
};

const LEGACY_SEQUENCES: Readonly<Record<string, string>> = {
  "\r": "enter",
  "\n": "enter",
  "\t": "tab",
  "\x7f": "backspace",
  "\b": "backspace",
  "\x1b": "escape",
  "\x1b[A": "up",
  "\x1b[B": "down",
  "\x1b[C": "right",
  "\x1b[D": "left",
  "\x1b[H": "home",
  "\x1b[F": "end",
  "\x1b[3~": "delete",
  "\x1b[5~": "pageUp",
  "\x1b[6~": "pageDown",
};

function modifierPrefix(modifier: number): string {
  const parts: string[] = [];
  if (modifier & 4) parts.push("ctrl");
  if (modifier & 1) parts.push("shift");
  if (modifier & 2) parts.push("alt");
  if (modifier & 8) parts.push("super");
  return parts.length === 0 ? "" : `${parts.join("+")}+`;
}

function keyNameForCodepoint(codepoint: number): string | undefined {
  const special = BASIC_KEY_NAMES[codepoint];
  if (special !== undefined) return special;
  if (codepoint >= 32 && codepoint !== 127) {
    try {
      return String.fromCodePoint(codepoint);
    } catch {
      return undefined;
    }
  }
  return undefined;
}

function parseCsiU(data: string): ParsedKittySequence | undefined {
  const match = /^\x1b\[(\d+)(?::(\d+))?(?:;(\d+)(?::(\d+))?)?(?:;(\d+))?u$/u.exec(data);
  if (!match) return undefined;
  const codepoint = Number(match[1]);
  if (!Number.isFinite(codepoint)) return undefined;
  const modifiers = [match[3], match[5]]
    .filter((value): value is string => value !== undefined)
    .map((value) => Number(value) - 1)
    .filter(Number.isFinite)
    .reduce((combined, value) => combined | value, 0);
  const event = match[4] === "2" ? "repeat" : match[4] === "3" ? "release" : undefined;
  const shiftedKey = match[2] === undefined ? undefined : Number(match[2]);
  return {
    codepoint,
    ...(Number.isFinite(shiftedKey) ? { shiftedKey } : {}),
    modifier: modifiers,
    ...(event === undefined ? {} : { eventType: event }),
  };
}

function parseModifyOtherKeys(data: string): { readonly codepoint: number; readonly modifier: number } | undefined {
  const match = /^\x1b\[27;(\d+);(\d+)~$/u.exec(data);
  if (!match) return undefined;
  const modifier = Number(match[1]) - 1;
  const codepoint = Number(match[2]);
  return Number.isFinite(modifier) && Number.isFinite(codepoint) ? { codepoint, modifier } : undefined;
}

export function parseKittySequence(data: string): ParsedKittySequence | null {
  return parseCsiU(data) ?? null;
}

export function parseKey(data: string, _kittyProtocolActive = false): string | undefined {
  const legacy = LEGACY_SEQUENCES[data];
  if (legacy !== undefined) return legacy;

  const csiU = parseCsiU(data);
  if (csiU) {
    const name = keyNameForCodepoint(csiU.codepoint);
    return name === undefined ? undefined : `${modifierPrefix(csiU.modifier)}${name}`;
  }

  const modifyOtherKeys = parseModifyOtherKeys(data);
  if (modifyOtherKeys) {
    const name = keyNameForCodepoint(modifyOtherKeys.codepoint);
    return name === undefined ? undefined : `${modifierPrefix(modifyOtherKeys.modifier)}${name}`;
  }

  const legacyEnter = /^\x1b\[13;(\d+)~$/u.exec(data);
  if (legacyEnter) {
    return `${modifierPrefix(Number(legacyEnter[1]) - 1)}enter`;
  }

  if (data.length === 1) {
    const codepoint = data.codePointAt(0) ?? 0;
    if (codepoint > 0 && codepoint < 27) return `ctrl+${String.fromCharCode(codepoint + 96)}`;
    if (codepoint >= 32 && codepoint !== 127) return data;
  }
  return undefined;
}

export function matchesKey(data: string, keyId: string, kittyProtocolActive = false): boolean {
  const parsed = parseKey(data, kittyProtocolActive);
  if (parsed === undefined) return false;
  const canonical = (value: string): string => {
    const pieces = value.toLowerCase().split("+");
    const rawBase = pieces.pop() ?? "";
    const base = rawBase === "return" ? "enter" : rawBase;
    const modifiers = ["ctrl", "shift", "alt", "super"].filter((modifier) => pieces.includes(modifier));
    return modifiers.length === 0 ? base : `${modifiers.join("+")}+${base}`;
  };
  return canonical(parsed) === canonical(keyId);
}

export async function fuzzyFind(_profile: {
  readonly query: string;
  readonly path: string;
}): Promise<{ readonly matches: readonly { readonly path: string }[] }> {
  // PortLog does not attach an autocomplete provider. Return an empty, typed
  // result if an upstream provider is attached accidentally rather than trying
  // to load Oh My Pi's native filesystem search capability.
  return { matches: [] };
}
