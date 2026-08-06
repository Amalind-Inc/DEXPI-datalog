# Oh My Pi TUI vendor provenance

This directory contains a bounded source-backed adaptation of Oh My Pi TUI source from the local clone at `/tmp/oh-my-pi`, revision `3a8591a8af5b6d200088d12ca75a5517cb064fa8`.

Vendored upstream source files retain their upstream implementation. Local adaptation is limited to replacing unavailable `@oh-my-pi/pi-utils`, `@oh-my-pi/pi-natives`, Bun, and full-TUI runtime dependencies with the adjacent portable shims (`pi-utils.ts`, `pi-natives.ts`, `utils.ts`, `tui.ts`, and `terminal-capabilities.ts`). PortLog supplies its own theme and owns session, worker, cancellation, and prompt lifecycle behavior.

The upstream project is MIT licensed. See `LICENSE` in this directory.
