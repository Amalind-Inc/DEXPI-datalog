# Hybrid Rule Packs: Advisory Guidance vs Executable Rules

A rule pack is a hybrid artifact: it may contain advisory pack guidance
(including pasted HAZOP/EPA highlights) and zero or more executable rules.
Only rules may produce rule evaluation outcomes. Advisory text may become
attached pack skill context and drive an agentic walkthrough on rule-pack
run, but never mints satisfied/violated/indeterminate engine verdicts.

Rejected alternatives: (1) treating every authored clause as soon-to-be
executable compliance logic (bulk EPA/HAZOP compilation), and (2) reducing
packs to MikeOSS-style instruction skills with no durable Souffle path.
Markdown pack ingest stores content immediately without compile-on-upload;
compilation starts only on explicit per-clause promote into a draft rule,
and only inside the expressible predicate island. Executable rules share one
generic runner behind a fixed rule outcome convention so authored fences do
not need per-rule Python adapters. OSS v1 stays on stratified Souffle/Datalog
(no ASP); open-ended defeasible prose abstains unless later made crisp via
session exception facts.

Governing related ADRs: 0007 (author-confirmed rule trust), 0008 (one Souffle
engine). Supersedes the bead-311 compile-on-upload contract.
