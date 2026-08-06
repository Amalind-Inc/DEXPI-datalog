/*
 * Portable capability seam for the vendored key parser. The upstream check is
 * used only to disambiguate raw backspace in Windows Terminal sessions.
 */
export function isInsideTerminalMultiplexer(environment: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(environment.TMUX || environment.STY || environment.ZELLIJ);
}
