/**
 * PortLog's focused compatibility adapter for the upstream Pi multiline editor.
 *
 * This is a small, source-backed adaptation, not a verbatim vendoring of the
 * full editor. Its wrapping, grapheme handling, and input-sequence contract
 * were derived from:
 * https://github.com/can1357/oh-my-pi/blob/3a8591a8af5b6d200088d12ca75a5517cb064fa8/packages/tui/src/components/editor.ts
 *
 * The full @oh-my-pi TypeScript package is not a Node runtime dependency here.
 * This adapter keeps only the APIs needed by PortLog's terminal chat prompt.
 * Attribution and the upstream MIT license are recorded in ./LICENSE.
 */

export interface EditorTheme {
  readonly borderColor?: (text: string) => string;
}

const ANSI_ESCAPE = /\u001b\[[0-?]*[ -/]*[@-~]/gu;
const SHIFT_ENTER_SEQUENCES = new Set(["\u001b[13;2u", "\u001b[27;2;13~", "\u001b\r"]);
const SUBMIT_SEQUENCES = new Set([
  "\r",
  "\n",
  "\u001b[13;5u",
  "\u001b[13;2;5u",
  "\u001b[27;5;13~",
  "\u001b[27;2;5;13~",
]);

function graphemes(value: string): string[] {
  if (typeof Intl.Segmenter === "function") {
    const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
    return Array.from(segmenter.segment(value), ({ segment }) => segment);
  }
  return Array.from(value);
}

function graphemeWidth(value: string): number {
  const clean = value.replace(ANSI_ESCAPE, "");
  if (!clean || /^[\u0000-\u001f\u007f-\u009f]$/u.test(clean)) return 0;
  // Keep the same terminal-cell intent as Pi's visibleWidth helper without
  // importing its Bun/terminal capability graph into the desktop package.
  if (
    /^[\u1100-\u115f\u2329\u232a\u2e80-\u303e\u3040-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe10-\ufe19\ufe30-\ufe6f\uff00-\uff60\uffe0-\uffe6]/u.test(
      clean,
    )
  ) {
    return 2;
  }
  return 1;
}

function visibleWidth(value: string): number {
  return graphemes(value).reduce((total, item) => total + graphemeWidth(item), 0);
}

function takeToWidth(items: readonly string[], maxWidth: number): number {
  let width = 0;
  let count = 0;
  while (count < items.length) {
    const itemWidth = graphemeWidth(items[count]!);
    if (count > 0 && width + itemWidth > maxWidth) break;
    if (count === 0 && itemWidth > maxWidth) return 1;
    width += itemWidth;
    count += 1;
  }
  return Math.max(1, count);
}

/**
 * Word-wrap one logical line, falling back to grapheme wrapping for a long
 * word. This mirrors the upstream Editor's user-visible layout contract:
 * whitespace is a preferred break and no grapheme is split.
 */
function wordWrapLine(line: string, maxWidth: number): string[] {
  if (!line) return [""];
  const width = Math.max(1, maxWidth);
  if (visibleWidth(line) <= width) return [line];

  const result: string[] = [];
  let remaining = line;
  while (remaining) {
    const items = graphemes(remaining);
    const count = takeToWidth(items, width);
    let cut = items.slice(0, count).join("");
    if (count < items.length) {
      const whitespace = cut.search(/\s+[^\s]*$/u);
      if (whitespace > 0) cut = cut.slice(0, whitespace).trimEnd();
    }
    if (!cut) cut = items[0]!;
    result.push(cut);
    remaining = remaining.slice(cut.length).replace(/^\s+/u, "");
  }
  return result;
}

export class Editor {
  onSubmit?: (text: string) => void | Promise<void>;
  onChange?: (text: string) => void;

  #text = "";
  #multiline = true;

  constructor(_theme: EditorTheme = {}, options: { multiline?: boolean } = {}) {
    this.#multiline = options.multiline !== false;
  }

  getText(): string {
    return this.#text;
  }

  setText(text: string): void {
    this.#text = text.replace(/\r\n?/gu, "\n").replace(/[\u0000-\u0008\u000b-\u001f\u007f]/gu, "");
    this.onChange?.(this.#text);
  }

  submit(): void {
    this.onSubmit?.(this.#text);
  }

  handleInput(data: string): void {
    if (!data) return;
    if (SHIFT_ENTER_SEQUENCES.has(data)) {
      if (this.#multiline) this.#insert("\n");
      return;
    }
    if (SUBMIT_SEQUENCES.has(data)) {
      this.submit();
      return;
    }
    if (data === "\u007f" || data === "\b") {
      this.#deleteBackward();
      return;
    }
    // Kitty key protocol sequences are complete strings when passed by the
    // adapter. Other escape/control sequences are commands, not text.
    if (data.startsWith("\u001b") || /[\u0000-\u001f\u007f]/u.test(data)) return;
    this.#insert(data);
  }

  getExpandedText(): string {
    return this.#text;
  }

  render(width: number): readonly string[] {
    const contentWidth = Math.max(1, Math.floor(width));
    return this.#text.split("\n").flatMap((line) => wordWrapLine(line, contentWidth));
  }

  #insert(value: string): void {
    if (!value) return;
    this.#text += value;
    this.onChange?.(this.#text);
  }

  #deleteBackward(): void {
    if (!this.#text) return;
    const items = graphemes(this.#text);
    items.pop();
    this.#text = items.join("");
    this.onChange?.(this.#text);
  }
}
