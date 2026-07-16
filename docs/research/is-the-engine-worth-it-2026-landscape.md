# Is the grounded engine worth building? — mid-2026 landscape check

**Question.** New models are very good and cheap. Why not just BYOK a frontier model,
build a nice front end, let it reason over the DEXPI XML, and spend our effort on
OCR/rule-extraction instead? We need to be *sure* the engine is worth it.

**Verdict.** Worth it — *conditional on product ambition*. If the product is
**high-assurance, auditable, exhaustive compliance verdicts** (safety cases, HAZOP,
MOC sign-off), the engine is both **necessary** (the failure we measured is structural,
not a model-maturity gap) and **defensible** (it is exactly the 2026 moat). If the
product is **navigation / search / "chat with your P&ID"**, a BYOK wrapper is fine and
the engine is over-engineering — but that market is crowded and commoditized. The
strategic fork below decides it.

## Finding 1 — The grounding gap is *structural* and still unsolved in 2026

Our A-direct result (verdict ~80%, exact witnesses 0–4%) is not a weak-model artifact
that scaling has since fixed. The mid-2026 long-context literature shows the exact
failure mode persists across all frontier models:

- **Multi-fact retrieval degrades**: "as generation goes on, the model gradually loses
  track of the information to be retrieved and tends to retrieve incomplete or incorrect
  information." Multi-needle (8) runs **10–25 pts below** single-needle
  ([NeedleBench 2407.11963](https://arxiv.org/html/2407.11963v1); [digitalapplied 2026](https://www.digitalapplied.com/blog/long-context-retrieval-needle-in-haystack-2026)).
  Exhaustive witnessing *is* multi-fact retrieval.
- **Lost-in-the-middle / context rot**: **30%+ accuracy drop** in mid-window positions
  across all 18 frontier models tested (Chroma); U-shaped accuracy; root cause is
  architectural (RoPE decay), not fixable by more context
  ([Context Rot / TMLS](https://www.tmls.nyc/research/context-rot-mechanistic); [Atlan 2026](https://atlan.com/know/llm-context-window-limitations/)).
- **"Context length alone hurts performance despite perfect retrieval"**
  ([2510.05381](https://arxiv.org/pdf/2510.05381)); effective context (MECW) gaps reach
  99% on complex tasks. A large P&ID XML puts objects "in the middle," where they get
  dropped.

**So scaling context has not solved exhaustive grounding, and the mechanism suggests it
won't soon.** Dumping XML into a frontier model reproduces the 0–4% witness failure.

## Finding 2 — Neuro-symbolic is winning on *our* problem class in 2026

- Compositional neuro-symbolic models "consistently outperform monolithic LLMs of
  comparable size," with smaller NS models matching far larger closed LLMs
  ([REASON 2601.20784](https://arxiv.org/pdf/2601.20784)).
- Consensus framing is **augmentation, not replacement**: "LLMs alone cannot solve
  enterprise reasoning; neuro-symbolic blends LLMs + knowledge graphs + symbolic logic
  for auditable answers" ([Stanford Tech Review 2026](https://www.stanfordtechreview.com/articles/neuro-symbolic-ai-in-silicon-valley-2026); [Security Podcast SV](https://thesecuritypodcastofsiliconvalley.com/blog/neuro-symbolic-ai-enterprise-llm-limitations)).
- **Bitter-Lesson nuance**: scaling wins on *unstructured perception*; **structured
  reasoning, long-horizon, and high-stakes enterprise favor hybrids**. Our
  compliance-over-graph is structured + high-stakes. Even framed by scaling advocates,
  the Bitter Lesson points *away* from pure-scaling here
  ([Econlib](https://www.econlib.org/econlog/learning-the-bitter-lesson-in-2026/); [Gary Marcus](https://garymarcus.substack.com/p/the-biggest-advance-in-ai-since-the)).

## Finding 3 — Grounding is an accuracy *and* regulatory necessity

- Grounded systems show **30–50% higher accuracy** on knowledge questions
  ([elephas 2026](https://elephas.app/blog/what-is-ai-grounding)).
- Even RAG-grounded **legal** tools still hallucinate in 2026 — retrieval alone is
  insufficient; you need *verifiable* grounding (execution + witnesses), not just
  context ([legal AI reliability 2026](https://www.researchgate.net/publication/391086271)).
- **EU AI Act** high-risk obligations apply **2 Aug 2026**; NIST AI RMF + ISO/IEC 42001
  demand accuracy and *auditor-inspectable* controls; groundedness detection is tied to
  the Act's accuracy requirements ([getmaxim governance 2026](https://www.getmaxim.ai/articles/top-5-ai-governance-tools-for-regulatory-compliance-in-2026/)).
  Process-safety compliance is squarely "high-risk."

## Finding 4 — Thin wrappers have no moat; the engine *is* the moat

- "**Model access is not a moat**"; thin wrappers are commodities labs can absorb —
  e.g., Anthropic's $100M Claude Partner Network (Accenture/Deloitte/…) reaches your
  customers directly ([Valtorian](https://www.valtorian.com/blog/ai-moats-2026); [Stanford Law moats PDF](https://law.stanford.edu/wp-content/uploads/2026/06/Defensible-Moats-for-Vertical-AI-Application-Companies-in-a-New-Competitive-Landscape.pdf)).
- Durable moats in 2026: **workflow depth, a proprietary decision graph, regulated-
  compliance status, and auditability** — "the new moat is a graph you build around your
  customer's decisions." A canonical DEXPI graph + logic + witnesses + audit trail *is*
  that graph-plus-compliance-plus-audit moat. BYOK+frontend is the exact wrapper with
  none of it.

## Finding 5 — Don't build OCR; the extraction layer is commoditized

Pivoting effort to OCR/extraction would enter the **most crowded, commoditized** part
of the stack, against funded incumbents already claiming ~99.5% extraction and
compliance monitoring:

- SymphonyAI **IRIS Foundry** (70–80% asset-hierarchy automation, MOC), Acuvate
  **DiagramIQ**, Scry **Collatio SchematicIQ**, **Markovate**, LTTS **Ainfonix**,
  Pathnovo (99.5% claim); multimodal-LLM P&ID→graph papers mid-2026.
- These do **extraction + digitization + discrepancy monitoring**; their "compliance" is
  largely prescriptive/discrepancy detection — **not grounded logical verdicts with
  witnesses and audit**. That reasoning/verification layer is comparatively open.
- **We already have DEXPI XML** — we are past the extraction bottleneck for our inputs.
  Consume extraction (buy/license) if raw drawings ever matter; invest our engineering
  in the reasoning/verification moat.

## The steelman for "just BYOK + frontend" — and when it's right

Real and honest: models are converging and cheap (GLM-5.2 ~1/6 US-frontier cost;
skills close the cheap-vs-frontier gap to a few points), neuro-symbolic has **no
standard framework and needs significant custom engineering**, and a wrapper ships in
days. **If the product's value is exploration/search/Q&A convenience, build the
wrapper** — the engine is not worth it and the grounding gap is tolerable.

## The strategic fork that actually decides "worth it"

- **(I) Verdict product** — trustworthy, auditable, exhaustive compliance verdicts a
  process-safety engineer can put in a HAZOP/MOC/safety case. → Engine **required**
  (Findings 1,3), **defensible** (Finding 4), differentiation lives here (Finding 5).
- **(II) Navigation product** — nicer way to explore/search/ask about drawings. →
  Wrapper suffices; engine is over-engineering; but crowded/commoditized (Finding 5).

## Implication for the map

If (I): destination B stands, and the **faithfulness spike** (~$5) is the cheap way to
be *sure* on the one real technical unknown (can a cheap model author faithful Datalog).
Being "sure" = run that spike before committing build effort — not more debate.
