# First-Confirmation Trust for User-Authored Rules

User-authored rules — written via the interactive rule-authoring flow,
generated into Datalog with an engineer-readable restatement, and confirmed
once by their author through the existing generated-Datalog confirmation gate
— become trusted to run without repeating that gate on later runs of the
exact same confirmed version. This is a second, narrower trust tier alongside
`bundled rule-pack trust`, not an extension of it: it is scoped to one
confirmed rule version and its author, is never shared across users, and any
edit to the rule's logic produces a new version that requires fresh
confirmation.

The stricter alternative — requiring the confirmation gate on every run of an
authored rule, forever — was rejected on the user's explicit instruction,
trading strict per-run review for the same run-without-friction experience
bundled packs already get after their one-time repository review. The looser
alternative — letting a confirmed authored rule quietly earn the same standing
as a maintainer-bundled rule (e.g. running silently as part of a mixed pack
without visual distinction) — was rejected because `bundled rule-pack trust`
is deliberately maintainer-exclusive; blurring it would let a single user's
unreviewed judgment present with the same authority as repository-reviewed
content.

Consequence: any UI surfacing rule results (in-thread rule results, rule-pack
run cards) must keep first-confirmation-trust rules visibly distinguished from
bundled-trust rules, even though neither prompts a confirmation dialog on a
repeat run. An authored rule's version identity must be part of its stored
state so that any edit invalidates prior trust rather than silently reusing
it.
