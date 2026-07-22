# Use a Web-Native Grounded Agent Harness

The Python backend owns a resumable, provider-neutral grounded-QA run loop, and
web or future CLI clients consume the same review-session, conversation, turn,
item, approval, interruption, and streamed-event lifecycle. This borrows the
public Codex App Server interaction model without depending on its coding-agent
runtime, because topology tools, evidence semantics, and model qualification
remain product-specific. The React client renders streamed state and submits
review actions; it does not execute tools or own agent state.

Within this backend-owned harness, the model drives the ordinary agent loop by
requesting domain capabilities and returning a final response when no further
tool call is needed. The backend remains authoritative for capability
authorization, route receipts, validation, deterministic execution, artifacts,
and interruption. This is a restricted model-driven harness, not a deterministic
intent cascade or an unrestricted autonomous agent, and v1 does not add a
general-purpose agent-framework dependency.
