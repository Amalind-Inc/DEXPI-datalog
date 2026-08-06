/*
 * Portable adaptation of the utility surface consumed by the vendored Oh My Pi
 * Editor. It follows packages/tui/src/utils.ts at
 * 3a8591a8af5b6d200088d12ca75a5517cb064fa8, replacing Bun/native text sizing
 * with Unicode-grapheme implementations suitable for Node's strip-types runtime.
 */

import { DEFAULT_TAB_WIDTH } from "./pi-utils.ts";

export const Ellipsis = {
  Unicode: "…",
  ThreeDots: "...",
  Omit: "",
} as const;
export type Ellipsis = (typeof Ellipsis)[keyof typeof Ellipsis];

export interface SliceResult {
  readonly text: string;
  readonly width: number;
}

const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
const ANSI_SEQUENCE =
  /\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][\s\S]*?(?:\x07|\x1b\\)|\x1b_[\s\S]*?(?:\x07|\x1b\\)/gu;
const COMBINING_OR_ZERO_WIDTH = /[\p{Mark}\u200c\u200d\ufe0e\ufe0f]/u;
const WIDE_OR_EMOJI =
  /[\u1100-\u115f\u2329\u232a\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe10-\ufe6f\uff00-\uff60\uffe0-\uffe6\u{1f000}-\u{1faff}]/u;

let widthConfigEpoch = 0;

function displayWidthOfGrapheme(grapheme: string): number {
  const visible = grapheme.replace(ANSI_SEQUENCE, "");
  if (visible.length === 0 || COMBINING_OR_ZERO_WIDTH.test(visible)) return 0;
  return WIDE_OR_EMOJI.test(visible) ? 2 : 1;
}

function splitStyledGraphemes(
  text: string,
): readonly { readonly text: string; readonly width: number }[] {
  const parts: { text: string; width: number }[] = [];
  let offset = 0;
  while (offset < text.length) {
    ANSI_SEQUENCE.lastIndex = offset;
    const match = ANSI_SEQUENCE.exec(text);
    if (match?.index === offset) {
      parts.push({ text: match[0], width: 0 });
      offset += match[0].length;
      continue;
    }
    const nextEscape = match?.index ?? text.length;
    const plain = text.slice(offset, nextEscape);
    for (const item of segmenter.segment(plain)) {
      parts.push({ text: item.segment, width: displayWidthOfGrapheme(item.segment) });
    }
    offset = nextEscape;
  }
  return parts;
}

export function getSegmenter(): Intl.Segmenter {
  return segmenter;
}

export function getWidthConfigEpoch(): number {
  return widthConfigEpoch;
}

export function visibleWidth(text: string): number {
  return splitStyledGraphemes(text).reduce((total, item) => total + item.width, 0);
}

export function replaceTabs(text: string): string {
  return text.replaceAll("\t", " ".repeat(DEFAULT_TAB_WIDTH));
}

export function padding(width: number): string {
  return " ".repeat(Math.max(0, Math.floor(width)));
}

export function sliceWithWidth(
  text: string,
  startColumn: number,
  length: number,
  strict = false,
): SliceResult {
  const start = Math.max(0, Math.floor(startColumn));
  const end = start + Math.max(0, Math.floor(length));
  let column = 0;
  let result = "";
  for (const part of splitStyledGraphemes(text)) {
    if (part.width === 0) {
      if (column >= start && column < end) result += part.text;
      continue;
    }
    const nextColumn = column + part.width;
    if (nextColumn > start && column < end && (!strict || (column >= start && nextColumn <= end))) {
      result += part.text;
    }
    column = nextColumn;
    if (column >= end) break;
  }
  return { text: result, width: visibleWidth(result) };
}

export function sliceByColumn(
  text: string,
  startColumn: number,
  length: number,
  strict = false,
): string {
  return sliceWithWidth(text, startColumn, length, strict).text;
}

export function truncateToWidth(
  text: string,
  maximumWidth: number,
  ellipsis: Ellipsis | "" | null = Ellipsis.Unicode,
  pad = false,
): string {
  const width = Math.max(0, Math.floor(maximumWidth));
  if (visibleWidth(text) <= width) return pad ? text + padding(width - visibleWidth(text)) : text;
  const suffix = ellipsis ?? Ellipsis.Unicode;
  const suffixWidth = visibleWidth(suffix);
  const contentWidth = Math.max(0, width - suffixWidth);
  const value =
    sliceWithWidth(text, 0, contentWidth, true).text + (suffixWidth <= width ? suffix : "");
  return pad ? value + padding(width - visibleWidth(value)) : value;
}

export function wrapTextWithAnsi(text: string, width: number): string[] {
  const maximum = Math.max(1, Math.floor(width));
  const lines: string[] = [];
  for (const logicalLine of text.split("\n")) {
    if (logicalLine.length === 0) {
      lines.push("");
      continue;
    }
    let remaining = logicalLine;
    while (visibleWidth(remaining) > maximum) {
      const piece = sliceWithWidth(remaining, 0, maximum, true).text;
      if (piece.length === 0) break;
      lines.push(piece);
      remaining = remaining.slice(piece.length);
    }
    lines.push(remaining);
  }
  return lines;
}

export type WordNavKind = "whitespace" | "delimiter" | "cjk" | "word" | "other";

export function getWordNavKind(grapheme: string): WordNavKind {
  if (/^\p{White_Space}$/u.test(grapheme)) return "whitespace";
  if (/^[\p{P}\p{S}]$/u.test(grapheme)) return "delimiter";
  if (/^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]$/u.test(grapheme))
    return "cjk";
  if (/^[\p{L}\p{N}]$/u.test(grapheme)) return "word";
  return "other";
}

export function moveWordLeft(text: string, cursor: number): number {
  const parts = Array.from(segmenter.segment(text));
  let index = parts.findIndex((part) => part.index >= cursor);
  if (index === -1) index = parts.length;
  while (index > 0 && getWordNavKind(parts[index - 1]?.segment ?? "") === "whitespace") index -= 1;
  const kind = getWordNavKind(parts[index - 1]?.segment ?? "");
  while (index > 0 && getWordNavKind(parts[index - 1]?.segment ?? "") === kind) index -= 1;
  return parts[index]?.index ?? text.length;
}

export function moveWordRight(text: string, cursor: number): number {
  const parts = Array.from(segmenter.segment(text));
  let index = parts.findIndex((part) => part.index >= cursor);
  if (index === -1) return text.length;
  while (index < parts.length && getWordNavKind(parts[index]?.segment ?? "") === "whitespace")
    index += 1;
  const kind = getWordNavKind(parts[index]?.segment ?? "");
  while (index < parts.length && getWordNavKind(parts[index]?.segment ?? "") === kind) index += 1;
  return parts[index]?.index ?? text.length;
}

export function setPortableWidthConfigEpochForTests(): void {
  widthConfigEpoch += 1;
}
