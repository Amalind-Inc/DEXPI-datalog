# AGENTS.md

## Project workflow

This repository uses Beads (`bd`) as the task source of truth.

Before starting implementation:
- Run `bd ready` or inspect the specific bead provided by the user.
- Work on exactly one bead at a time.
- Do not start unrelated work.
- Do not close a bead unless the implementation is complete and validation passes.
- Leave progress notes in Beads when work is incomplete or blocked.

## Development discipline

Prefer small vertical slices.

For feature work and bug fixes:
- Use test-driven development when requested.
- Write tests against public behavior, not private implementation details.
- Prefer integration-style tests over brittle unit tests.
- Do not mock internal collaborators unless they cross a true external boundary.
- Do not write all tests up front.
- Use red-green-refactor:
  1. Write one failing behavior test.
  2. Implement the minimum code to pass.
  3. Refactor only after tests are green.
  4. Repeat.

## Validation

Before committing:
- Discover the correct validation commands from project files.
- Use the repo’s actual tooling.
- Run relevant tests.

## Commit policy

- Commit only changes for the active bead.
- Do not commit unrelated files.
- Use a commit message that references the bead id.
- Do not commit if validation is failing unless the user explicitly asks for a checkpoint commit.