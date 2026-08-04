# DeepSeek v4 Flash PortLog capability findings

Bead context: `pydexpi-datalog-1-3u3t`

## Scope and method

This note records a manual review of the 25-case live exploratory matrix run against the prepared E06 PortLog project. It is an answer-and-trace assessment, not a deterministic answer benchmark.

The run used DeepSeek v4 Flash through the existing governed terminal review path. The persisted artifacts are:

- Full observable trace: `.tmp/portlog-exploration-deepseek-v4-flash.json`
- Readable answer digest: `.tmp/portlog-exploration-deepseek-v4-flash-digest.json`
- Answer transcript used for manual review: `.tmp/portlog-exploration-deepseek-v4-flash-answers.txt`
- Prepared topology reference: `.tmp/portlog-user-data/reviews/local/pid-f43e520e-a365-48c7-b7cf-703cd3865656/topology_view.json`

The manual review checks each answer against the bounded topology and the observable PortLog tool results. It does not attempt to judge hidden reasoning.

## Run shape

| Measure | Result |
| --- | ---: |
| Cases | 25 |
| Inspect cases | 16 |
| Verify cases | 5 |
| Review cases | 4 |
| Total observable events | 6,490 |
| Assistant text-delta events | 6,244 |
| Tool requests | 98 |
| Tool results | 98 |
| Completed turns | 25 |
| `portlog_evidence` calls | 78 |
| `portlog_rule_check` calls | 16 |
| `portlog_isolated_command` calls | 4 |
| Evidence calls with `no_matching_evidence` | 6 |
| Completed rule checks | 7 |
| Rejected rule-check requests | 9 |
| Isolated commands admitted | 4 of 4 |

All 25 turns reached a completed terminal record. The isolated-command calls all ran through `gondolin-qemu-hvf`, returned exit code 0, and produced the admitted `result.json` candidate artifact.

## Manual answer classification

The labels below describe answer quality, not model confidence:

- **Strong**: the answer is materially supported by the returned evidence and respects the question's scope.
- **Partial / bounded**: the answer is useful or safely cautious, but omits a material fact, leaves a supported inference unused, or overstates a limited result.
- **Materially wrong / incomplete**: the answer contradicts the topology, misses the central relationship, or answers a different question.

### Inspect posture

| Case | Classification | Finding |
| --- | --- | --- |
| `inspect-01-equipment-tags` | Strong | Correctly identifies the only tagged equipment: H-1009 and P-4713. |
| `inspect-02-heat-exchanger-type` | Strong | Correctly identifies H-1009 as a Plate Heat Exchanger. |
| `inspect-03-pump-type` | Strong | Correctly identifies P-4713 as a Centrifugal Pump. |
| `inspect-04-heat-exchanger-connections` | Strong | Correctly distinguishes H-1009's four nozzle/connection-point memberships from the one explicit external path, P-4713/N-2 to H-1009/N-1. The long retry sequence was inefficient but the final answer was grounded. |
| `inspect-05-pump-connections` | Materially wrong / incomplete | The answer says no pipe or equipment is identified beyond P-4713's PipingNodes. The trace already returned `sourceItem` references from the Pipe and PipingNetworkSegment to P-4713/N-2, and the prepared topology contains the corresponding target H-1009/N-1. |
| `inspect-06-heat-exchanger-nozzles` | Strong | Correctly lists all four H-1009 nozzles and their identifiers. |
| `inspect-07-pump-nozzles` | Partial / bounded | Correctly lists both P-4713 nozzles and refuses to invent an explicit suction/discharge attribute. It should have added the narrower supported inference that N-2 is the source/outlet of the represented directed segment. |
| `inspect-08-lines` | Partial / bounded | Correctly identifies Line 47132 and its segment/pipe. It overstates the topology by saying the line connects H-1009 through multiple nozzles; the explicit source/target path is P-4713/N-2 to H-1009/N-1. |
| `inspect-09-missing-p101` | Strong | Correctly treats the no-match result as bounded absence and does not claim global non-existence. |
| `inspect-10-missing-valve` | Strong | Correctly reports that no check-valve entity is present in the prepared topology. |
| `inspect-11-pump-downstream` | Materially wrong / incomplete | It reports only P-4713's terminal PipingNodes and misses the explicit Pipe/segment path to H-1009/N-1. |
| `inspect-12-heat-exchanger-upstream` | Materially wrong / incomplete | It invents or misstates a P-4713/N-1 to H-1009 relationship and summarizes the path as if both pump nozzles participate. The supported directed relationship is P-4713/N-2 to H-1009/N-1. |
| `inspect-13-tagged-ids` | Strong | Correctly returns the two tagged equipment items with canonical IDs and classes. |
| `inspect-14-untagged-objects` | Strong | Correctly enumerates the 16 untagged objects and distinguishes them from the two tagged equipment nodes. |
| `inspect-15-pump-heat-path` | Strong | Correctly reconstructs the path through P-4713/N-2, Pipe, Line 47132 segment, and H-1009/N-1. |
| `inspect-16-ambiguous-nozzle` | Partial / bounded | Correctly recognizes that “the nozzle” is ambiguous and identifies the main P-4713/N-2 to H-1009/N-1 path. It incompletely reports available nozzle names and treats retrieval omissions as if they were topology omissions. |

For the 16 inspect cases, the manual classification is **10 strong, 3 partial/bounded, and 3 materially wrong/incomplete**. The central weakness is not simple entity lookup. It is relation completion and direction-preserving graph interpretation.

### Verify posture

| Case | Classification | Finding |
| --- | --- | --- |
| `verify-01-pump-check-valve` | Strong | Recovers from an invalid canonical-node scope, retries with a valid identifier, and reports the governed `violated` result and reason code. |
| `verify-02-pump-rule-by-tag` | Strong | Uses the tag scope directly and reports the governed violation accurately. |
| `verify-03-universal-connected-rule` | Materially wrong / incomplete | The question asks about a universal rule, but the answer runs the pump-specific check repeatedly and reports only one pump violation. It does not explain that one failed pump check cannot establish a universal claim. |
| `verify-04-heat-exchanger-rule` | Partial / bounded | Safely refuses to provide an engineering outcome after the pump-only rule rejects H-1009 as an invalid scope. The final text should state that scope/type rejection explicitly. |
| `verify-05-rule-explanation` | Strong | Reports the deterministic reason and ordered topology IDs. It is terse, but the result is accurate and directly traceable to the governed check. |

The verify posture shows reliable governed-result recovery for valid pump scopes and safe failure for invalid scopes. It does not yet reliably distinguish a question about **the rule's result** from a question about **the rule's applicability or quantification**.

### Review posture

| Case | Classification | Finding |
| --- | --- | --- |
| `review-01-governed-e06` | Strong | Correctly separates E06 no-match evidence, invalid rule scope, and an admitted isolated artifact. It does not turn the admitted artifact into an engineering conclusion. |
| `review-02-native-analysis` | Partial / bounded | Correctly reports the P-4713 violation and the admitted isolated run. However, the candidate artifact only proves that the approved review-bundle command ran; it does not prove that native analysis found no conflicts. |
| `review-03-evidence-rule-discrepancy` | Strong | Recovers from E06 no-matches by using a broader pump claim, then correctly concludes that the evidence and deterministic result agree. |
| `review-04-artifact-provenance` | Strong | Clearly explains what the admitted artifact proves—execution, admission, provenance, and `result.json` integrity—and what it does not prove about E06 or engineering correctness. |

The review posture is the strongest overall. The model generally preserves the boundary between evidence, deterministic checks, and isolated-command provenance. The remaining issue is occasional overinterpretation of what a successful candidate command proves.

## Strengths

1. **Entity and class lookup is reliable.** Equipment tags, classes, nozzle membership, canonical IDs, and untagged-object enumeration were consistently handled.
2. **Bounded absence is usually handled safely.** The P-101 and E06 cases distinguish “no matching evidence in this scope” from a universal claim that the object cannot exist.
3. **Governed rule use is effective for the supported scope.** Once a valid pump identifier is available, the model reports the deterministic outcome and reason code without changing it into free-form engineering advice.
4. **The model can reconstruct a multi-hop path when the prompt names the path and relevant objects.** `inspect-15-pump-heat-path` is the clearest successful example.
5. **Review provenance boundaries are mostly respected.** In particular, `review-04-artifact-provenance` does not treat an admitted isolated artifact as topology evidence.
6. **Observable execution is complete.** Every case completed, every tool result is recorded, and all four isolated-command invocations were admitted with host-authored provenance.

## Failure modes

### 1. Relation retrieval is not relation comprehension

The evidence tool can return a `sourceItem` relationship to P-4713/N-2 without returning the paired `targetItem` in the same narrow result. The model then reports that no piping connection exists. Follow-up retrieval needs to be relation-aware: once a source or target reference is found, fetch the referenced object and its paired endpoint before answering.

### 2. Negative conclusions are too strong after incomplete retrieval

The answers to `inspect-05` and `inspect-11` convert “the returned slice does not show the full path” into “the path is not evidenced.” The correct wording must distinguish:

- no matching evidence;
- evidence that contains one endpoint of a relationship;
- a complete path with both endpoints;
- a genuine topology absence.

### 3. Direction and endpoint identity are fragile

`inspect-12` demonstrates a material endpoint substitution: P-4713/N-1 is used where the explicit path is P-4713/N-2. The model needs to preserve `sourceItem` and `targetItem` identity through every summarization step and should not merge nozzle membership with external connectivity.

### 4. Caution can discard useful supported inferences

`inspect-07` correctly refuses to invent a nozzle-role field, but it discards the weaker, evidence-based statement that N-2 is the source/outlet of the represented directed segment. Answers should separate explicit facts from derived graph semantics instead of choosing between overclaiming and total refusal.

### 5. Tool use does not guarantee question understanding

`verify-03` performs several valid tool calls but answers the wrong logical question. A rule result for P-4713 cannot establish a universal statement about every connected object. The evaluator must grade question interpretation separately from tool-call validity.

### 6. Successful isolation is sometimes overread

An admitted `review-bundle-candidate` proves bounded command admission and artifact production. It does not prove that native engineering analysis was performed or that the underlying topology is correct. The model mostly understands this boundary, but `review-02` contains a small overclaim.

### 7. Retry and verbosity costs grow with graph questions

The hardest inspect cases generated long tool loops and large assistant transcripts: `inspect-04`, `inspect-11`, `inspect-12`, `inspect-15`, and `inspect-16`. The problem is not just latency. Repeated broad retrieval increases the chance that the model merges partial result sets incorrectly.

## Recommended evaluation contract

Do not reduce this matrix to an exact-answer score. Grade each case on independent observable axes:

1. **Trace integrity** — did the turn complete and persist the expected record?
2. **Tool policy** — were evidence, rule-check, and isolated-command tools used only when appropriate?
3. **Grounding** — are named entities and relationships present in returned evidence?
4. **Relation fidelity** — are source/target, composition, and reference edges preserved?
5. **Bounded uncertainty** — does the answer distinguish no-match, incomplete evidence, and confirmed absence?
6. **Deterministic truthfulness** — when a governed check runs, does the answer preserve its outcome, reason, and scope?
7. **Isolation provenance** — when a VM command runs, does the answer state what the admitted artifact proves and does not prove?
8. **Question fit** — does the answer address the user's actual logical request rather than merely repeat the last tool result?

A future matrix can retain open-ended natural-language answers while using these behavioral labels as the rubric. The expected result should be a set of observable obligations, not a single canonical paragraph.

## Follow-up prompt bank recommendations

1. Add paired relation prompts that differ only by endpoint: P-4713/N-2 to H-1009/N-1 versus P-4713/N-1 to H-1009/N-1.
2. Add source/target reversal prompts and require the answer to preserve direction without assuming process semantics that are not present.
3. Add “partial evidence” cases where the first result contains one endpoint and a second lookup is required to complete the path.
4. Add contrast cases for membership versus external connectivity: “which nozzles belong to H-1009?” versus “which nozzles are connected by a Pipe?”
5. Add absence cases with three outcomes: no match, incomplete slice, and confirmed class absence.
6. Add ambiguity cases that require clarification when an entity name is non-unique, then compare with a case where the model should answer all matches.
7. Add rule-applicability questions: valid pump scope, invalid equipment scope, unsupported rule, and universal quantification over a set.
8. Add provenance traps where an isolated command succeeds but explicitly returns no engineering facts; grade whether the model keeps that boundary.
9. Record per-case labels for retrieval completeness, relation fidelity, question fit, and provenance discipline in a separate report rather than scoring only the final prose.
10. Keep a small set of representative high-fidelity traces and a larger set of cheap prompt variations. Use the large set to discover failure patterns and the representative traces to verify fixes.

## Bottom line

DeepSeek v4 Flash is already useful for a governed PortLog terminal workflow when the task is entity lookup, bounded absence, a named deterministic pump check, or a clearly specified path reconstruction. The model is not yet dependable for unconstrained “what is connected/upstream/downstream?” questions over a sparse graph. The next improvement target is relation-aware retrieval plus source/target-preserving answer construction, not more deterministic answer fixtures.
