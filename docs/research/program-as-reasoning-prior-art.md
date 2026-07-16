# Prior art: "code/program as a reasoning engine" for grounded QA

**Question.** Has our chosen direction — an LLM authors an *executable logic program*
grounded in deterministically-extracted facts, runs it, and returns the answer plus
the witnesses the execution produced — been done before, especially for technical
documents and with a cost focus? And is "code as a reasoning engine" the right frame
when *not all queries are logic-shaped*?

**Answer: yes, extensively — and the design we converged on (destination B) is a
named, published, effective paradigm, not a novel gamble.** The prior art both
*validates* the approach (including the cheap-model bet) and *sharpens* the two risks
we already flagged (autoformalization faithfulness; expressivity of pure Datalog).
The genuine novelty is the *domain* (process-engineering / DEXPI P&IDs), not the
mechanism.

This note feeds the forthcoming wayfinder map; it is the linked asset for the
"prior art" research ticket.

## 1. The Arm C loop is Logic-LM (2023)

Logic-LM ([arXiv:2305.12295](https://arxiv.org/abs/2305.12295)) is exactly our loop:

1. LLM translates the NL problem into a **symbolic formulation**;
2. a **deterministic solver** runs inference;
3. a result interpreter maps the solver output back to NL;
4. a **self-refinement module uses the solver's error messages** to revise the
   formalization, iterating until no errors or a max-revision cap.

That is the CODORD "generate → execute → observe → revise" loop, published. Reported
**+39.2% over standard prompting, +18.4% over chain-of-thought** across ProofWriter,
PrOntoQA, FOLIO, LogicalDeduction, AR-LSAT. Framed explicitly as "faithful logical
reasoning."

**Sharpening warning.** Logic-LM++ ([arXiv:2407.02514](https://arxiv.org/html/2407.02514v1))
found the original solver-error self-refinement "shows almost no improvement after
multiple iterations": error-message feedback fixes *executability* (syntax, unbound
variables), **not semantic faithfulness**. This independently confirms our risk #1 —
a program that *runs* is not a program that *means the right thing*. Our revise loop
needs a faithfulness check (roundtrip/back-translation), not just "does it execute."

## 2. "Code as a reasoning engine" is PAL / PoT / Chain-of-Code — and it favours cheap models

- **PAL** (Program-Aided Language models, ICML 2023,
  [proceedings](https://proceedings.mlr.press/v202/gao23f/gao23f.pdf)): the LLM emits a
  program as the reasoning steps and offloads solving to a Python interpreter. A
  small model + interpreter **beat PaLM-540B (CoT) by 15% on GSM8K**. Offloading the
  *execution* of reasoning to a deterministic runtime is the whole point.
- **Chain of Code** ([site](https://chain-of-code.github.io/)): crucially, unlike CoT
  (which only helps the largest models), CoC **also helps smaller models** — "it's
  easier for smaller models to output structured code as intermediate steps rather
  than natural language." Direct support for the cheap-model bet: *code is a better
  medium than prose for a weak reasoner.*
- **Cascades / learned offload** (SplitReason [arXiv:2504.16379](https://arxiv.org/abs/2504.16379)):
  run most generation on the cheap model, defer only the hardest ~1–5% to a large one;
  1.35% offload beats 10% random. This is the cost lever that makes "cheap-model-viable"
  real without inverting cost.

## 3. The mechanism is decades-old KBQA / semantic parsing

NL → executable query over a knowledge base/graph → answer, with returned rows as
grounded evidence, is the entire tradition of **text-to-SQL / text-to-SPARQL / KBQA**.
Our EDB-as-knowledge-base + Datalog query sits squarely in it; the witness set is the
query's result provenance. Nothing exotic about "the answer is what the query returned."

## 4. Domain sibling: BIM / IFC Automated Compliance Checking (ACC)

Our closest applied precedent is **automated code-compliance checking in construction**:

- Standard pipeline = *rule interpretation → model preparation → rule execution →
  reporting*, where **"rule interpretation is the most vital and complex stage"**
  ([review](https://ieeexplore.ieee.org/document/8002486/)) — the autoformalization
  bottleneck, independently named in another domain.
- **IFC** (Industry Foundation Classes) is the BIM analog of **DEXPI**: a neutral
  exchange format turned into a knowledge graph, with **Datalog/Prolog rules modelling
  "obligations, prohibitions, and conditions"** (i.e. deontic rules) over the graph
  ([Sci Reports](https://www.nature.com/articles/s41598-023-34342-1);
  [survey](https://www.researchgate.net/publication/391156820)).
- Neuro-symbolic ACC combining deep learning with **Answer Set Programming** exists,
  including a close analog: **compliance checking of electrical control panels**
  ([arXiv:2305.10113](https://arxiv.org/pdf/2305.10113)) — electrical panels are a
  near neighbour of P&IDs.
- LLM-based rule interpretation reports **97% F1 / 97.7% execution accuracy** on BIM
  ACC ([ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0926580525007472)).
- Reported gap: ACC work is "mostly prescriptive rules and geometric constraints, with
  limited progress on performance-based requirements," and full automation (extracting
  rules from regulatory text) remains open.

**Implication.** The paradigm is proven in a sister domain; **process-engineering /
DEXPI P&IDs are a comparatively under-explored application** — that is our novelty
niche, not the mechanism. It also re-confirms the Datalog-vs-ASP expressivity tension:
the compliance/deontic literature reaches for ASP once rules become defeasible.

## 5. "Not all queries are logic" is the hybrid-routing result — you're right

The literature's recommended architecture is **not** "code as *the* reasoning engine";
it is a **router** that sends logic-shaped queries to the symbolic path and others to
neural, with a cost cascade:

- Hybrid / dynamic selection between neural and symbolic per query (or per step) is the
  recommended design ([comparative study](https://www.arxiv.org/pdf/2508.03366)).
- **Rule-driven selective routing beats naive concatenation**; use cheap keyword match
  → semantic classification → LLM-assisted routing (tiered).
- **Cascade** cheap-first, defer hard cases to a bigger model — cost down without
  accuracy loss; "single LLM for all tasks overpays by 40–85%" vs routing.
- Adaptive *formalism* selection hit 96% on mixed logical-reasoning data, +25% over the
  best single-formalism baseline — supporting a Datalog/ASP choice *driven by query
  type* (which, again, reopens the multi-solver question the moment rules get
  defeasible).

This is precisely the user's framing — "the ones that are logic get coded up, tested,
and viewed" — and it is the state of the art, not a compromise.

## What this means for the destination (B)

- **Keep going.** "Reasoning = one executed grounded program" (Logic-LM / PAL) is
  proven and is *especially* suited to cheap models (Chain-of-Code). The cheap-model,
  low-cost-per-grounded-answer bet has direct empirical backing.
- **The revise loop must check faithfulness, not just executability** (Logic-LM++).
- **Build the router early**, not late: a classifier that decides logic-path vs
  neural-path per query, with a cheap-first cascade, is the SOTA shape and it directly
  serves the cost metric.
- **Expect the Datalog→ASP pressure** as soon as rules are defeasible; the compliance
  literature is unanimous on this.
- **Novelty is the domain.** Frame contributions around DEXPI/P&ID grounded compliance,
  where prior ACC work is thin, rather than around the (well-established) mechanism.

## Primary sources

- Logic-LM — [arXiv:2305.12295](https://arxiv.org/abs/2305.12295);
  Logic-LM++ — [arXiv:2407.02514](https://arxiv.org/html/2407.02514v1)
- PAL — [PMLR v202](https://proceedings.mlr.press/v202/gao23f/gao23f.pdf);
  Chain of Code — [chain-of-code.github.io](https://chain-of-code.github.io/);
  SplitReason — [arXiv:2504.16379](https://arxiv.org/abs/2504.16379)
- BIM ACC review — [IEEE 8002486](https://ieeexplore.ieee.org/document/8002486/);
  BIM+KG — [Sci Reports s41598-023-34342-1](https://www.nature.com/articles/s41598-023-34342-1);
  electrical-panel neuro-symbolic ACC — [arXiv:2305.10113](https://arxiv.org/pdf/2305.10113);
  LLM for BIM ACC — [ScienceDirect S0926580525007472](https://www.sciencedirect.com/science/article/pii/S0926580525007472)
- Neuro-symbolic hybrid/routing comparative study — [arXiv:2508.03366](https://www.arxiv.org/pdf/2508.03366)
- Adjacent to our per-step idea: VeriCoT [arXiv:2511.04662](https://arxiv.org/abs/2511.04662);
  LOGicalThought [arXiv:2510.01530](https://arxiv.org/abs/2510.01530);
  ReTraceQA [arXiv:2510.09351](https://arxiv.org/abs/2510.09351)
