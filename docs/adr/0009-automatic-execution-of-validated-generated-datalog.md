---
status: accepted
---

# Automatically execute validated generated Datalog

Temporary read-only generated Datalog will execute without per-query user confirmation after backend safety and semantic-faithfulness validation succeeds. The user’s engineering question supplies execution intent; after execution, the product discloses the query’s engineer-readable semantics, route, validation outcomes, inspectable Datalog, deterministic result, and evidence. This deliberately replaces the earlier generated-Datalog confirmation gate: requiring approval reduced flow without changing the read-only nature of execution, while validation and deterministic evidence remain backend-owned safeguards. Confirmation is still required when promoting generated logic into a reusable authored rule, and this decision does not authorize graph mutation, design approval, or execution after failed validation.
Automatic execution is authorized only by layered faithfulness verification:
deterministic intent and contract checks plus applicable counterfactual probes.
A model verifier may veto or request repair, but cannot authorize execution by
itself; unresolved or conflicting evidence fails closed.

During implementation, the existing confirmation path may remain behind an
internal, unreleased migration guard until safety validation, layered
faithfulness verification, post-execution disclosure, Answer Now steering, and
end-to-end tests are complete. The released hybrid workflow has no confirmation
prompt for read-only template or generated-query execution, and the temporary
legacy path is removed after cutover.
