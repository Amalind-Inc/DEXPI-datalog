/*
 * Portable replacements for the small @oh-my-pi/pi-utils surface required by
 * the vendored TUI modules. Derived from the upstream call contracts at
 * revision 3a8591a8af5b6d200088d12ca75a5517cb064fa8.
 */

export const DEFAULT_TAB_WIDTH = 4;

export function getProjectDir(): string {
  return process.cwd();
}

export const logger = {
  error(message: string, details?: unknown): void {
    // History persistence is not enabled by PortLog's prompt, but preserve the
    // upstream failure path without importing its application logger.
    console.error(message, details);
  },
};

// Select-list uses these only as optional observability brackets around a
// synchronous local fuzzy filter.
export function pushLoopPhase(_phase: string): void {}
export function popLoopPhase(): void {}
