# Control Deterministic Boundaries, Not Model Prose

The application controls what can be executed, validates operation arguments,
preserves source provenance, bounds retrieval, and exposes evidence and
limitations. The model remains responsible for interpreting open-ended user
language, handling conversational ambiguity, and writing the natural-language
answer because forcing those behaviors through deterministic application logic
would add brittle complexity without removing model limitations. Internal
structured output may link an answer to known evidence, but the product does not
attempt to prescribe the model's prose or guarantee behavior beyond the
deterministic evidence boundary.
