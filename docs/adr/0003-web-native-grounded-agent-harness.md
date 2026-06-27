# Use a Web-Native Grounded Agent Harness

The Python backend owns a resumable, provider-neutral grounded-QA run loop, and
web or future CLI clients consume the same review-session, conversation, turn,
item, approval, interruption, and streamed-event lifecycle. This borrows the
public Codex App Server interaction model without depending on its coding-agent
runtime, because topology tools, evidence semantics, and model qualification
remain product-specific. The React client renders streamed state and submits
review actions; it does not execute tools or own agent state.
