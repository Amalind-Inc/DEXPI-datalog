---
status: accepted
---

# Use an extensible, governed execution trace

The product will expose a structured execution trace as a curated projection of routing, validation, execution, tool, and evidence events rather than a raw chain-of-thought transcript or a fixed prose log. Events share a stable envelope but use extensible namespaced kinds so agents and extensions can add new activity without changing the core contract; rendering policy governs visibility, redaction, grouping, size, and evidence requirements, and unknown kinds receive a safe generic presentation. This preserves harness flexibility while preventing secrets, private model reasoning, unbounded tool output, and unsupported engineering claims from entering the user-visible trace.
