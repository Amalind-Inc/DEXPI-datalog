/*
 * Minimal portable component contract derived from
 * /tmp/oh-my-pi/packages/tui/src/tui.ts at 3a8591a8af5b6d200088d12ca75a5517cb064fa8.
 * The full upstream TUI renderer is intentionally not vendored: PortLog owns
 * terminal lifecycle and only hosts the upstream Editor component.
 */

export interface Component {
  render(width: number): readonly string[];
  handleInput?(data: string): void;
  wantsKeyRelease?: boolean;
  invalidate?(): void;
  dispose?(): void;
}

export interface Focusable {
  focused: boolean;
  setUseTerminalCursor?(useTerminalCursor: boolean): void;
}

/** Zero-width upstream cursor anchor emitted by focused components. */
export const CURSOR_MARKER = "\x1b_pi:c\x07";
