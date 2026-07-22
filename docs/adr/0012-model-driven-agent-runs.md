---
status: accepted
---

# Use model-driven runs with user steering and optional constraints

Grounded-QA runs will follow the mainstream agent-loop contract: the model continues through authorized tool calls and handoffs until it returns a final response without further tool calls. There is no fixed semantic repair-attempt count and no bespoke semantic-progress detector in v1; repetition telemetry may inform a later stop condition if real use demonstrates the need. Users may optionally constrain turns, duration, provider cost, or capabilities, and may select **Answer Now** or **Stop** during a run. Answer Now returns the best completed grounded state—a validated deterministic answer when available, or otherwise established facts, rejected attempts, and the blocker—and never permits an ungrounded estimate or bypasses validation. Capability policy and provider or infrastructure ceilings remain mandatory operational safeguards rather than answer-quality strategy.
