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
- **Audit**: obligation submissions must include ``/workspace/analysis.dl``,
  the exact program whose executed output supports the answer.  The two
  preregistered permission/defeasible controls instead require a closed,
  mechanically checked abstention and prohibit a verdict program.

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
    PERMISSION_CONTROL_IDS,
    build_task,
    validate_bundle,
)
from pydexpi_datalog.benchmark.contract import POSTURES, VERDICTS, StructuredAnswer
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.graph_inspection import build_graph_inspection_index
from pydexpi_datalog.benchmark.rmso_openrouter_gateway import (
    LockedOpenRouterGateway,
)
from pydexpi_datalog.benchmark.rmso_kira import (
    CHECKPOINT_FIELD,
    CHECKPOINT_VALUE,
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
RMSO_CHECKPOINT_AGENT_IMPORT_PATH = (
    "rmso_kira:CheckpointTerminusKira"
)


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


def _run_preregistered_faithfulness_gate(
    program: str, question: BenchmarkQuestion
) -> dict[str, object] | None:
    # Lazy import avoids coupling the generic task builder to the RMSO suite
    # while keeping the scored Arm B constructor fail-closed on core entries.
    from pydexpi_datalog.benchmark.rmso_faithfulness import (
        run_preregistered_faithfulness_gate,
    )

    return run_preregistered_faithfulness_gate(program, question.question_id)


def requires_executed_program(question: BenchmarkQuestion) -> bool:
    """Return whether this preregistered question belongs on the verdict path."""
    return question.question_id not in PERMISSION_CONTROL_IDS


def verify_souffle_answer_trace(
    answer: StructuredAnswer,
    drawing_ref: Path,
    program: str | None,
    question: BenchmarkQuestion,
) -> dict[str, object]:
    from dataclasses import asdict

    from pydexpi_datalog.benchmark.audit_trace import (
        verify_audit_trace,
        verify_souffle_audit_trace,
    )

    graph_path = (
        drawing_ref / "graph_facts.json" if drawing_ref.is_dir() else drawing_ref
    )
    graph_facts = json.loads(graph_path.read_text(encoding="utf-8"))
    if not requires_executed_program(question):
        if (program or "").strip():
            raise ValueError(
                "permission/defeasible controls must abstain without an executable "
                "verdict program"
            )
        return asdict(
            verify_audit_trace(
                answer=answer,
                graph_facts=graph_facts,
                allow_policy_abstention=True,
            )
        )
    if not (program or "").strip():
        raise ValueError("source conclusions require an executed Datalog program")
    return asdict(
        verify_souffle_audit_trace(
            answer=answer,
            graph_facts=graph_facts,
            executed_program=program,
        )
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

RMSO_ANALYSIS_TEMPLATE = """\
.include "/input/graph_facts.dl"
.include "/input/graph_topology_semantics.dl"
.decl result_witness(id:symbol)
.output result_witness

// Add only portable IDB rules below. Never hard-code drawing UUIDs.
"""

_RMSO_RUN_QUERY_HELPER_TEMPLATE = '''\
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys


def write_checkpoint(program: Path, witnesses: list[str]) -> None:
    inspection = json.loads(
        (Path(__file__).resolve().parent / "graph_inspection.json").read_text(
            encoding="utf-8"
        )
    )
    known_ids = {node["id"] for node in inspection["nodes"]}
    unknown_ids = sorted(set(witnesses) - known_ids)
    if unknown_ids:
        raise ValueError(f"query emitted IDs outside the graph: {unknown_ids}")
    verdict = "violation_found" if witnesses else "no_violation"
    answer = {
        "verdict": verdict,
        "witness_ids": witnesses,
        "posture": "source_grounded",
        "answer_text": "Result produced by the latest executed Souffle query.",
        "support": {
            "steps": [
                {
                    "id": "scope",
                    "kind": "graph_scope",
                    "node_count": inspection["node_count"],
                    "edge_count": inspection["edge_count"],
                    "dependencies": [],
                },
                {
                    "id": "execution",
                    "kind": "souffle_execution",
                    "artifact": "analysis.dl",
                    "relation": "result_witness",
                    "witness_ids": witnesses,
                    "dependencies": ["scope"],
                },
            ],
            "claims": [
                {"claim": "verdict", "step_ids": ["execution"]},
                *(
                    {"claim": f"witness:{witness}", "step_ids": ["execution"]}
                    for witness in witnesses
                ),
            ],
        },
    }
    answer_path = program.parent / "structured_answer.json"
    temporary = answer_path.with_name(f".{answer_path.name}.tmp")
    temporary.write_text(
        json.dumps(answer, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    temporary.replace(answer_path)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_query.py PROGRAM", file=sys.stderr)
        return 2
    program = Path(sys.argv[1]).resolve()
    if program.name != "analysis.dl":
        print("PROGRAM must be named analysis.dl", file=sys.stderr)
        return 2
    output = program.parent / ".query-out"
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)
    completed = subprocess.run(
        ["souffle", str(program), "-D", str(output)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        diagnostics = (completed.stderr or completed.stdout)[-4000:]
        print(diagnostics, file=sys.stderr)
        return completed.returncode
    result = output / "result_witness.csv"
    if not result.is_file():
        print("Souffle did not produce result_witness.csv", file=sys.stderr)
        return 1
    witnesses = []
    with result.open(newline="", encoding="utf-8") as stream:
        witnesses = [row[0] for row in csv.reader(stream, delimiter="\\t") if row]
    witnesses = sorted(set(witnesses))
    write_checkpoint(program, witnesses)
    print(json.dumps({
        "ok": True,
        "__RMSO_CHECKPOINT_FIELD__": "__RMSO_CHECKPOINT_VALUE__",
        "witness_ids": witnesses,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
RMSO_RUN_QUERY_HELPER = _RMSO_RUN_QUERY_HELPER_TEMPLATE.replace(
    "__RMSO_CHECKPOINT_FIELD__", CHECKPOINT_FIELD
).replace("__RMSO_CHECKPOINT_VALUE__", CHECKPOINT_VALUE)


def build_souffle_harbor_task(
    *,
    question: BenchmarkQuestion,
    drawing_ref: Path,
    output_dir: Path,
    budgets: EpisodeBudgets,
) -> Path:
    """Generate the Arm C Harbor task for one benchmark question."""
    bundle_dir = validate_bundle(drawing_ref)
    program_required = requires_executed_program(question)
    return build_task(
        question=question,
        drawing_ref=drawing_ref,
        output_dir=output_dir,
        budgets=budgets,
        instruction=_render_souffle_instruction(question),
        tags=("arm-c-souffle", "pydexpi-datalog-1-3q1.9"),
        extra_input_files=_souffle_input_files(bundle_dir),
        engine_setup=SOUFFLE_ENGINE_SETUP,
        extra_workspace_files=(PROGRAM_FILENAME,) if program_required else (),
    )


def build_rmso_souffle_harbor_task(
    *,
    question: BenchmarkQuestion,
    drawing_ref: Path,
    output_dir: Path,
    budgets: EpisodeBudgets,
) -> Path:
    """Generate the locked RMSO engine arm with only approved EDB/IDB inputs."""
    bundle_dir = validate_bundle(
        drawing_ref, required_files=("graph_facts.json",)
    )
    program_required = requires_executed_program(question)
    return build_task(
        question=question,
        drawing_ref=drawing_ref,
        output_dir=output_dir,
        budgets=budgets,
        instruction=_render_souffle_instruction(question, rmso_locked=True),
        tags=("arm-b-rmso-souffle", "pydexpi-datalog-1-rmso.1"),
        input_bundle_files=("graph_facts.json",),
        extra_input_files=_rmso_souffle_input_files(bundle_dir),
        engine_setup=SOUFFLE_ENGINE_SETUP,
        extra_workspace_files=(PROGRAM_FILENAME,) if program_required else (),
        workspace_seed_files=(
            {PROGRAM_FILENAME: "analysis_template.dl"} if program_required else None
        ),
        base_image="--platform=linux/amd64 ubuntu:22.04",
        base_packages=("python3", "tmux"),
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


def _rmso_souffle_input_files(bundle_dir: Path) -> dict[str, str]:
    artifact = json.loads(
        (bundle_dir / "graph_facts.json").read_text(encoding="utf-8")
    )
    return {
        "analysis_template.dl": RMSO_ANALYSIS_TEMPLATE,
        "graph_facts.dl": build_graph_facts_datalog(artifact),
        "graph_topology_semantics.dl": load_graph_topology_idb(),
        "graph_inspection.json": build_graph_inspection_index(artifact),
        "run_query.py": RMSO_RUN_QUERY_HELPER,
    }


def _render_souffle_instruction(
    question: BenchmarkQuestion, *, rmso_locked: bool = False
) -> str:
    if not requires_executed_program(question):
        return _render_permission_abstention_instruction(question)
    verdicts = json.dumps(list(VERDICTS))
    postures = json.dumps(list(POSTURES))
    if rmso_locked:
        input_lines = """\
- `/input/graph_facts.json`: the canonical graph-mirrored base fact layer.
- `/input/graph_inspection.json`: the same compact answer-neutral node/edge index given
  to the direct arm.
- `/input/graph_facts.dl`: those facts as the allowed Souffle EDB.
- `/input/graph_topology_semantics.dl`: the allowed derived-predicate contract."""
        prior_art = (
            "No raw XML, graph export, README guidance, rule pack, oracle, or "
            "project reasoning code is available in this locked arm."
        )
    else:
        input_lines = """\
- `/input/drawing.xml`: the original DEXPI source drawing.
- `/input/graph_facts.json`: the canonical base fact layer extracted from it.
- `/input/graph.json`: a NetworkX node-link JSON export of those same facts.
- `/input/graph_facts.dl`: those same facts pre-rendered as Souffle EDB
  (`node`, `node_attribute`, `graph_edge`, `graph_edge_attribute`).
- `/input/graph_topology_semantics.dl`: the shared IDB semantics layer
  (derived topology predicates over the EDB).
- `/input/README.md`: orientation and witness-citation guide."""
        pack_lines = "\n".join(
            f"- `/input/rule_pack_{pack_path.stem}.md`: a reviewed rule pack"
            " (restatement prose plus fenced Souffle programs) you may adapt."
            for pack_path in sorted(RULE_PACKS_DIR.glob("*.md"))
        )
        prior_art = f"Reviewed prior art you are encouraged to compose from:\n\n{pack_lines}"
    return f"""\
# P&ID review question (Datalog-first)

Answer one question about the engineering drawing mounted read-only under
`/input`, using the `souffle` Datalog engine installed on PATH:

{input_lines}

{prior_art}

## Question

{question.question}

## Method: generate, execute, observe, revise

Use bounded inspection (`grep`, `head`, `sed`, or standard-library Python).
Avoid printing an entire large input when a targeted query will answer the question. The compact index
already contains every graph UUID, source Proteus ID, label, tag, edge label, and
`attr_name`.

1. Edit the preloaded `/workspace/analysis.dl` portable skeleton immediately.

   It begins with these exact declarations; add only your own IDB rules:

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
2. Execute it for real with the bounded helper:

   `python3 /input/run_query.py /workspace/analysis.dl`

   The helper clears stale output, compiles and runs Souffle, bounds diagnostics,
   prints the exact `result_witness` IDs as JSON, and writes a valid provisional structured answer.
   Each successful rerun replaces that checkpoint, so an
   executed answer remains available even if later analysis runs out of time.
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
  "answer_text": a concise explanation of the result,
  "support": {{
    "steps": [
      {{
        "id": "scope",
        "kind": "graph_scope",
        "node_count": exact facts.nodes count,
        "edge_count": exact facts.edges count,
        "dependencies": []
      }},
      {{
        "id": "execution",
        "kind": "souffle_execution",
        "artifact": "analysis.dl",
        "relation": "result_witness",
        "witness_ids": the exact IDs emitted by result_witness,
        "dependencies": ["scope"]
      }}
    ],
    "claims": [
      {{"claim": "verdict", "step_ids": ["execution"]}},
      one {{"claim": "witness:<exact ID>", "step_ids": ["execution"]}}
        for every submitted witness
    ]
  }}
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
- The support graph is mandatory for a source conclusion. Keep failed and
  superseded work in the observable command history, but link final claims
  only to the final `execution` step. Free-form reasoning is preserved for
  human review but is not a mechanically creditable support step.

Also leave `/workspace/{PROGRAM_FILENAME}` containing the exact Datalog
program you executed for your final answer - it ships with your answer for
post-hoc audit and the task is rejected without it.

Verify both files exist before marking the task complete.
"""


def _render_permission_abstention_instruction(question: BenchmarkQuestion) -> str:
    return f"""\
# P&ID review question (policy-boundary control)

Answer one question about the engineering drawing mounted read-only under
`/input`.

## Question

{question.question}

## Required policy behavior

This is a permission/defeasible-exception control. The monotone drawing facts
cannot soundly establish permission or resolve an exception. You must abstain;
you must not author or execute a Datalog verdict program for this question.

Write `/workspace/{ANSWER_FILENAME}` containing exactly this closed result
shape (the explanation wording may be concise but must name the limitation):

```json
{{
  "verdict": "unanswerable",
  "witness_ids": [],
  "posture": "source_data_unavailable",
  "answer_text": "Permission is not soundly decidable from monotone drawing facts.",
  "support": {{
    "steps": [
      {{
        "id": "policy",
        "kind": "policy_abstention",
        "operation": "permission_or_defeasible_not_decidable_from_monotone_drawing",
        "dependencies": []
      }}
    ],
    "claims": [{{"claim": "verdict", "step_ids": ["policy"]}}]
  }}
}}
```

Do not create `/workspace/{PROGRAM_FILENAME}`. The abstention policy step is
mechanically checked after submission; a source conclusion or witness fails.
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
    adapter_root = str(Path(__file__).resolve().parent)
    python_path = [adapter_root]
    if env.get("PYTHONPATH"):
        python_path.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_path)
    runner = HarborKiraEpisodeRunner(
        kira_dir=kira_dir,
        model=SOUFFLE_ARM_MODELS[model_key],
        environ=env,
        request_gateway=request_gateway,
        agent_import_path=RMSO_CHECKPOINT_AGENT_IMPORT_PATH,
        agent_kwargs={
            "checkpoint_cutoff_sec": max(1.0, budgets.agent_timeout_sec - 60.0),
        },
    )
    return AgenticArm(
        runner=runner,
        budgets=budgets,
        model_name=model_key,
        arm_label=ARM_LABEL,
        task_builder=build_rmso_souffle_harbor_task,
        require_executed_program=requires_executed_program,
        program_validator=validate_faithfulness_program,
        program_faithfulness_gate=_run_preregistered_faithfulness_gate,
        answer_trace_gate=verify_souffle_answer_trace,
    )
