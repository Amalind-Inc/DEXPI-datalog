# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the
actual label strings used in this repo's beads tracker. Apply them with
`br label add <id> <label>`.

| Canonical role     | Label in our tracker | Meaning                                  |
| ------------------ | -------------------- | ---------------------------------------- |
| `needs-triage`     | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`       | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`  | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`  | `ready-for-human`    | Requires human implementation            |
| `wontfix`          | `wontfix`            | Will not be actioned                     |

Notes:

- `ready-for-agent` is **already in use** in this repo's beads (several PRDs carry it), so the
  default mapping matches existing practice — do not introduce a synonym.
- When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the label string
  from the right-hand column.

Edit the right-hand column if the vocabulary ever changes.
