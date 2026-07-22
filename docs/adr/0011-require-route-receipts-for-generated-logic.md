---
status: accepted
---

# Require route receipts before generated logic

The grounded-QA harness will preserve model-planned capability selection while enforcing the cheap-first cascade through backend-issued route receipts. Generated Datalog is unavailable until the runtime has recorded template no-fit, exhausted binding correction, template faithfulness failure, or another explicitly non-template-eligible outcome; the model may consume but cannot invent this receipt. This avoids both an unenforced prompt-level preference that models can skip and a duplicate deterministic intent router, while making every escalation auditable.
