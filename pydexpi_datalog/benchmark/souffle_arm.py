"""Arm C: agent + Souffle + rule packs (bead pydexpi-datalog-1-3q1.9).

Arm A agentic's sandbox and episode machinery, plus ``souffle`` on PATH and
the repository's bundled rule-pack markdown inside the sandbox - the CODORD
generate-revise loop and leading candidate for the new system.  The agent
authors Datalog, runs it against real engine output, iterates against the
diagnostics it observes, and submits executed results with witnesses.  The
exact executed program ships with the answer for post-hoc audit.

The delta over Arm A is deliberately small and declarative:

- **Bundle composition**: the read-only ``/input`` additionally carries the
  pre-rendered EDB facts (``graph_facts.dl``), the shared IDB semantics
  layer (``graph_topology_semantics.dl``), and every bundled rule pack as
  canonical markdown - the same EDB/IDB layers and packs ADR 0008 pins for
  the one shared Souffle engine.
- **Prompt framing**: generate -> execute -> observe -> revise, with the
  rule-pack markdown offered as trusted prior art.
- **Audit**: the submission must include ``/workspace/analysis.dl``, the
  exact program whose executed output supports the answer; the generated
  verifier rejects submissions without it, and the adapter ships it in the
  transcript.

Budgets, episode interface, artifact parsing, and grading are byte-for-byte
the shared :mod:`pydexpi_datalog.benchmark.agentic_arm` machinery.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Mapping

from pydexpi_datalog.benchmark.agentic_arm import (
    AGENTIC_ARM_MODELS,
    ANSWER_FILENAME,
    PROGRAM_FILENAME,
    AgenticArm,
    EpisodeBudgets,
    HarborKiraEpisodeRunner,
    build_task,
    validate_bundle,
)
from pydexpi_datalog.benchmark.contract import POSTURES, VERDICTS
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.rmso_openrouter_gateway import (
    LockedOpenRouterGateway,
)
from pydexpi_datalog.semantics.derive_graph_semantics import (
    build_graph_facts_datalog,
    load_graph_topology_idb,
)
from pydexpi_datalog.verification.souffle_rule_pack import RULE_PACKS_DIR

# The model matrix is identical to Arm A agentic: same friendly keys, same
# OpenRouter routing, so the arms differ only in what the sandbox offers.
SOUFFLE_ARM_MODELS = dict(AGENTIC_ARM_MODELS)

ARM_LABEL = "c-souffle"


class FaithfulnessProgramError(ValueError):
    """An Arm B program cannot be replayed safely across frozen EDBs."""


def validate_faithfulness_program(program: str) -> None:
    """Validate the portable query-module contract used by faithfulness probes."""
    required_patterns = {
        "graph-facts include": (
            r'^\s*\.include\s+"/input/graph_facts\.dl"\s*$'
        ),
        "topology-semantics include": (
            r'^\s*\.include\s+"/input/graph_topology_semantics\.dl"\s*$'
        ),
        "result_witness declaration": (
            r"^\s*\.decl\s+result_witness\s*\(\s*id\s*:\s*symbol\s*\)\s*$"
        ),
        "result_witness output": r"^\s*\.output\s+result_witness\s*$",
    }
    for label, pattern in required_patterns.items():
        if re.search(pattern, program, flags=re.MULTILINE) is None:
            raise FaithfulnessProgramError(
                f"Portable faithfulness program is missing {label}."
            )

    edb_predicates = "node|node_attribute|graph_edge|graph_edge_attribute"
    if re.search(
        rf"^\s*\.decl\s+(?:{edb_predicates})\s*\(",
        program,
        flags=re.MULTILINE,
    ):
        raise FaithfulnessProgramError(
            "Portable faithfulness program contains an embedded EDB declaration."
        )
    if re.search(
        rf'^\s*(?:{edb_predicates})\s*\(\s*"[^\n]*\)\s*\.\s*$',
        program,
        flags=re.MULTILINE,
    ):
        raise FaithfulnessProgramError(
            "Portable faithfulness program contains an embedded EDB fact."
        )
    if re.search(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b",
        program,
    ):
        raise FaithfulnessProgramError(
            "Portable faithfulness program contains a hidden drawing UUID."
        )

# Extra Dockerfile setup: souffle installed from the souffle-lang apt
# repository.  CI never builds this image (scripted episodes only); the
# live-matrix bead (3q1.14) validates the build before any measured run.
SOUFFLE_ENGINE_SETUP = """\

RUN apt-get update \\
    && apt-get install -y --no-install-recommends ca-certificates wget \\
    && wget -qO /usr/share/keyrings/souffle-archive-keyring.gpg \\
        https://souffle-lang.github.io/ppa/souffle-key.public \\
    && echo "deb [signed-by=/usr/share/keyrings/souffle-archive-keyring.gpg] https://souffle-lang.github.io/ppa/ubuntu/ stable main" \\
        > /etc/apt/sources.list.d/souffle.list \\
    && apt-get update \\
    && apt-get install -y --no-install-recommends souffle \\
    && rm -rf /var/lib/apt/lists/*
"""


def build_souffle_harbor_task(
    *,
    question: BenchmarkQuestion,
    drawing_ref: Path,
    output_dir: Path,
    budgets: EpisodeBudgets,
) -> Path:
    """Generate the Arm C Harbor task for one benchmark question."""
    bundle_dir = validate_bundle(drawing_ref)
    return build_task(
        question=question,
        drawing_ref=drawing_ref,
        output_dir=output_dir,
        budgets=budgets,
        instruction=_render_souffle_instruction(question),
        tags=("arm-c-souffle", "pydexpi-datalog-1-3q1.9"),
        extra_input_files=_souffle_input_files(bundle_dir),
        engine_setup=SOUFFLE_ENGINE_SETUP,
        extra_workspace_files=(PROGRAM_FILENAME,),
    )


def _souffle_input_files(bundle_dir: Path) -> dict[str, str]:
    """The Datalog layers and rule-pack prior art mounted beside the bundle.

    The EDB facts are pre-rendered from the bundle's own canonical base
    fact layer, so the agent composes programs instead of re-deriving the
    fact encoding; the IDB and rule packs ship verbatim from the repo.
    """
    artifact = json.loads(
        (bundle_dir / "graph_facts.json").read_text(encoding="utf-8")
    )
    files = {
        "graph_facts.dl": build_graph_facts_datalog(artifact),
        "graph_topology_semantics.dl": load_graph_topology_idb(),
    }
    for pack_path in sorted(RULE_PACKS_DIR.glob("*.md")):
        files[f"rule_pack_{pack_path.stem}.md"] = pack_path.read_text(
            encoding="utf-8"
        )
    return files


def _render_souffle_instruction(question: BenchmarkQuestion) -> str:
    verdicts = json.dumps(list(VERDICTS))
    postures = json.dumps(list(POSTURES))
    pack_lines = "\n".join(
        f"- `/input/rule_pack_{pack_path.stem}.md`: a reviewed rule pack"
        " (restatement prose plus fenced Souffle programs) you may adapt."
        for pack_path in sorted(RULE_PACKS_DIR.glob("*.md"))
    )
    return f"""\
# P&ID review question (Datalog-first)

Answer one question about the engineering drawing mounted read-only under
`/input`, using the `souffle` Datalog engine installed on PATH:

- `/input/drawing.xml`: the original DEXPI source drawing.
- `/input/graph_facts.json`: the canonical base fact layer extracted from it.
- `/input/graph.json`: a NetworkX node-link JSON export of those same facts.
- `/input/graph_facts.dl`: those same facts pre-rendered as Souffle EDB
  (`node`, `node_attribute`, `graph_edge`, `graph_edge_attribute`).
- `/input/graph_topology_semantics.dl`: the shared IDB semantics layer
  (derived topology predicates over the EDB).
- `/input/README.md`: orientation and witness-citation guide.

Reviewed prior art you are encouraged to compose from:

{pack_lines}

## Question

{question.question}

## Method: generate, execute, observe, revise

1. Author a portable Datalog query module at `/workspace/analysis.dl` that
   begins with these exact includes, then adds only your own IDB rules:

   ```souffle
   .include "/input/graph_facts.dl"
   .include "/input/graph_topology_semantics.dl"
   .decl result_witness(id:symbol)
   .output result_witness
   ```

   `result_witness` must contain exactly the exhaustive witness IDs for the
   question. Do not copy EDB declarations or facts into your program and do
   not hard-code drawing UUIDs or precomputed witness IDs. This portable
   query module will be replayed unchanged against the paired drawing and
   frozen counterfactual EDB probes.
2. Execute it for real: `souffle /workspace/analysis.dl -D /workspace/out`.
3. Observe the actual engine output and diagnostics.  If the program fails
   or the output does not answer the question, revise the program and run
   it again.  Do not answer from unexecuted reasoning.
4. Base your verdict and witnesses on the final executed output only.

- The input is read-only.  Do not attempt to modify it.
- Base your answer only on the drawing data under `/input`.

## Submission

Write `/workspace/{ANSWER_FILENAME}` containing exactly one JSON object:

```json
{{
  "verdict": one of {verdicts},
  "witness_ids": a list of object IDs from the drawing that are the evidence
    for your verdict (empty if none apply),
  "posture": one of {postures},
  "answer_text": a concise explanation of the result
}}
```

- "violation_found" / "no_violation" assert a conclusion from the drawing
  and require posture "source_grounded".
- If the drawing lacks required data, use "unanswerable" with posture
  "source_data_unavailable". For an ambiguous request that needs a criterion
  or object, use "needs_clarification". For an off-domain request, use
  "out_of_scope". Do not invent witness IDs.
- For an unanswerable, ambiguous, or off-domain request, answer_text must name
  the source limitation or ambiguity and offer a concrete source-grounded next step.
- Every witness ID must be copied exactly from `/input/graph_facts.json`
  (`facts.nodes[*].node_id`, or edge `source_id`/`target_id`/`edge_key`);
  never invent IDs.

Also leave `/workspace/{PROGRAM_FILENAME}` containing the exact Datalog
program you executed for your final answer - it ships with your answer for
post-hoc audit and the task is rejected without it.

Verify both files exist before marking the task complete.
"""


def create_souffle_arm(
    model_key: str,
    *,
    kira_dir: Path,
    budgets: EpisodeBudgets,
    environ: Mapping[str, str] | None = None,
    request_gateway: LockedOpenRouterGateway | None = None,
) -> AgenticArm:
    """Build the live Arm C adapter for one friendly model key."""
    env = dict(os.environ if environ is None else environ)
    if model_key not in SOUFFLE_ARM_MODELS:
        raise ValueError(
            f"unknown souffle arm model {model_key!r}; "
            f"expected one of {sorted(SOUFFLE_ARM_MODELS)}"
        )
    if not env.get("OPENROUTER_API_KEY"):
        raise ValueError(
            "OPENROUTER_API_KEY is required for live souffle-arm episodes"
        )
    runner = HarborKiraEpisodeRunner(
        kira_dir=kira_dir,
        model=SOUFFLE_ARM_MODELS[model_key],
        environ=env,
        request_gateway=request_gateway,
    )
    return AgenticArm(
        runner=runner,
        budgets=budgets,
        model_name=model_key,
        arm_label=ARM_LABEL,
        task_builder=build_souffle_harbor_task,
        require_executed_program=True,
        program_validator=validate_faithfulness_program,
    )
