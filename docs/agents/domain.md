# Domain Docs

How the engineering skills should consume this repo's domain documentation. This repo is
**single-context**: one `CONTEXT.md` and one `docs/adr/` at the repo root (no
`CONTEXT-MAP.md`).

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — product sentence (§ Product: P&ID workbench)
  plus the domain glossary / ubiquitous language.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in. Current ADRs
  include `0002-control-deterministic-boundaries-not-model-prose`,
  `0003-web-native-grounded-agent-harness`,
  `0007-first-confirmation-trust-for-authored-rules`, and
  `0008-one-souffle-engine-for-rule-packs-and-ad-hoc-queries` — the last is load-bearing for
  any grounded-reasoning / Datalog work.

If a file doesn't exist, proceed silently; `/domain-modeling` creates them lazily when terms
or decisions actually get resolved.

## File structure

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-web-review-shell.md
│   ├── ...
│   └── 0008-one-souffle-engine-for-rule-packs-and-ad-hoc-queries.md
└── pydexpi_datalog/
```

## Use the glossary's vocabulary

When your output names a domain concept (issue title, refactor proposal, hypothesis, test
name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary avoids.
If the concept isn't in the glossary yet, that's a signal — either you're inventing language
the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently
overriding:

> _Contradicts ADR-0008 (one Soufflé engine for rule packs and ad-hoc queries) — but worth
> reopening because…_
