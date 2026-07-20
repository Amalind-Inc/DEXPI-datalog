"""Arm T task builder and in-container routing helper (bead lx6p, slice 2).

The episode lifecycle mirrors Arm C exactly - same engine image, same
``run_query.py`` checkpoint machinery, same wrap-proof receipt - but the
model's primary authored surface is one routing JSON instead of a Datalog
program:

1. the model writes ``/workspace/routing.json`` (category + typed parameters),
2. ``route_query.py`` validates it closed-world against the drawing's
   inspection vocabulary, printing corrective feedback on failure
   (``VALIDATION_RETRY_BUDGET`` retries before the fallback ladder is named),
3. on success it renders the frozen template, records a ``route_trace.json``
   tagging the path taken, and delegates execution + checkpointing to the
   unchanged ``run_query.py`` lifecycle,
4. ``policy_abstention`` routings checkpoint the exact closed abstention
   answer mechanically - no model-authored JSON anywhere on the primary path.

Fallback ladder (production behavior, recorded not forbidden): template ->
free-form authoring via ``run_query.py`` -> policy abstention.  Fallback
episodes are distinguishable mechanically: a template-path episode leaves a
``route_trace.json`` whose ``program_sha256`` matches the executed
``analysis.dl``.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydexpi_datalog.benchmark.agentic_arm import (
    PROGRAM_FILENAME,
    build_task,
    validate_bundle,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.graph_inspection import build_graph_inspection_index
from pydexpi_datalog.benchmark.rmso_kira import (
    CHECKPOINT_FIELD,
    CHECKPOINT_VALUE,
)
from pydexpi_datalog.benchmark.souffle_arm import (
    RMSO_ANALYSIS_TEMPLATE,
    RMSO_RUN_QUERY_HELPER,
    SOUFFLE_ENGINE_SETUP,
    requires_executed_program,
)
from pydexpi_datalog.benchmark import template_arm as _template_arm
from pydexpi_datalog.benchmark.template_arm import TEMPLATE_PACK
from pydexpi_datalog.semantics.derive_graph_semantics import (
    build_graph_facts_datalog,
    load_graph_topology_idb,
)

ARM_LABEL = "t-template"
ROUTING_FILENAME = "routing.json"
ROUTE_TRACE_FILENAME = "route_trace.json"
VALIDATION_RETRY_BUDGET = 2

ROUTING_TEMPLATE = (
    json.dumps({"category": "", "parameters": {}}, indent=2) + "\n"
)

# The reviewed template module ships verbatim into the container so the
# helper validates and renders with exactly the code the tests exercise.
TEMPLATE_ARM_SOURCE = Path(_template_arm.__file__).read_text(encoding="utf-8")

_ROUTE_QUERY_HELPER_TEMPLATE = '''\
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

INPUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(INPUT_DIR))

import template_arm

VALIDATION_RETRY_BUDGET = __RMSO_VALIDATION_RETRY_BUDGET__

ABSTENTION_ANSWER = {
    "verdict": "unanswerable",
    "witness_ids": [],
    "posture": "source_data_unavailable",
    "answer_text": (
        "Permission is not soundly decidable from monotone drawing facts."
    ),
    "support": {
        "steps": [
            {
                "id": "policy",
                "kind": "policy_abstention",
                "operation": (
                    "permission_or_defeasible_not_decidable_from_monotone_drawing"
                ),
                "dependencies": [],
            }
        ],
        "claims": [{"claim": "verdict", "step_ids": ["policy"]}],
    },
}


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8"
    )
    temporary.replace(path)


def _print_receipt() -> None:
    # Wrap-proof mechanical receipt: short, compact, own line (rmso.10).
    print(json.dumps(
        {"ok": True, "__RMSO_CHECKPOINT_FIELD__": "__RMSO_CHECKPOINT_VALUE__"},
        separators=(",", ":"),
    ))


def _record_failure(workspace: Path) -> int:
    attempts_path = workspace / ".route_attempts"
    try:
        attempts = int(attempts_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        attempts = 0
    attempts += 1
    attempts_path.write_text(str(attempts), encoding="utf-8")
    if attempts > VALIDATION_RETRY_BUDGET:
        print(
            f"validation retry budget ({VALIDATION_RETRY_BUDGET}) exhausted; "
            "fall back in order: (1) author /workspace/analysis.dl directly "
            "and execute python3 /input/run_query.py /workspace/analysis.dl; "
            '(2) for a permission/defeasible-policy question route '
            '{"category": "policy_abstention", "parameters": {}}.',
            file=sys.stderr,
        )
    return attempts


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: route_query.py ROUTING", file=sys.stderr)
        return 2
    routing_path = Path(sys.argv[1]).resolve()
    if routing_path.name != "routing.json":
        print("ROUTING must be named routing.json", file=sys.stderr)
        return 2
    workspace = routing_path.parent
    try:
        routing = json.loads(routing_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"routing.json is not readable JSON: {error}", file=sys.stderr)
        _record_failure(workspace)
        return 1
    vocabulary = template_arm.routing_vocabulary(
        (INPUT_DIR / "graph_inspection.json").read_text(encoding="utf-8")
    )
    errors = template_arm.validate_routing(routing, vocabulary)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        _record_failure(workspace)
        return 1
    if routing["category"] == "policy_abstention":
        _write_json(workspace / "structured_answer.json", ABSTENTION_ANSWER)
        _write_json(
            workspace / "route_trace.json",
            {
                "schema_version": 1,
                "path": "abstention",
                "category": "policy_abstention",
                "parameters": {},
                "program_sha256": None,
            },
        )
        _print_receipt()
        return 0
    program = template_arm.render_program(routing, include_dir=str(INPUT_DIR))
    program_path = workspace / "analysis.dl"
    program_path.write_text(program, encoding="utf-8")
    _write_json(
        workspace / "route_trace.json",
        {
            "schema_version": 1,
            "path": "template",
            "category": routing["category"],
            "parameters": routing.get("parameters") or {},
            "program_sha256": hashlib.sha256(
                program.encode("utf-8")
            ).hexdigest(),
        },
    )
    # Delegate execution, diagnostics bounding, checkpoint write, and the
    # receipt to the unchanged run_query.py lifecycle.
    completed = subprocess.run(
        [sys.executable, str(INPUT_DIR / "run_query.py"), str(program_path)],
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
'''

RMSO_ROUTE_QUERY_HELPER = (
    _ROUTE_QUERY_HELPER_TEMPLATE.replace(
        "__RMSO_CHECKPOINT_FIELD__", CHECKPOINT_FIELD
    )
    .replace("__RMSO_CHECKPOINT_VALUE__", CHECKPOINT_VALUE)
    .replace(
        "__RMSO_VALIDATION_RETRY_BUDGET__", str(VALIDATION_RETRY_BUDGET)
    )
)


def build_rmso_template_harbor_task(
    *,
    question: BenchmarkQuestion,
    drawing_ref: Path,
    output_dir: Path,
    budgets,
) -> Path:
    """Generate the Arm T (template-routed) Harbor task for one question."""
    bundle_dir = validate_bundle(
        drawing_ref, required_files=("graph_facts.json",)
    )
    program_required = requires_executed_program(question)
    workspace_seed_files = {ROUTING_FILENAME: "routing_template.json"}
    if program_required:
        workspace_seed_files[PROGRAM_FILENAME] = "analysis_template.dl"
    return build_task(
        question=question,
        drawing_ref=drawing_ref,
        output_dir=output_dir,
        budgets=budgets,
        instruction=_render_template_instruction(question),
        tags=("arm-t-template", "pydexpi-datalog-1-lx6p"),
        input_bundle_files=("graph_facts.json",),
        extra_input_files=_template_input_files(bundle_dir),
        engine_setup=SOUFFLE_ENGINE_SETUP,
        extra_workspace_files=(
            (ROUTING_FILENAME, PROGRAM_FILENAME)
            if program_required
            else (ROUTING_FILENAME,)
        ),
        workspace_seed_files=workspace_seed_files,
        base_image="--platform=linux/amd64 ubuntu:22.04",
        base_packages=("python3", "tmux"),
    )


def _template_input_files(bundle_dir: Path) -> dict[str, str]:
    artifact = json.loads(
        (bundle_dir / "graph_facts.json").read_text(encoding="utf-8")
    )
    return {
        "analysis_template.dl": RMSO_ANALYSIS_TEMPLATE,
        "routing_template.json": ROUTING_TEMPLATE,
        "graph_facts.dl": build_graph_facts_datalog(artifact),
        "graph_topology_semantics.dl": load_graph_topology_idb(),
        "graph_inspection.json": build_graph_inspection_index(artifact),
        "run_query.py": RMSO_RUN_QUERY_HELPER,
        "route_query.py": RMSO_ROUTE_QUERY_HELPER,
        "template_arm.py": TEMPLATE_ARM_SOURCE,
    }


def _render_category_lines() -> str:
    lines = []
    for template in TEMPLATE_PACK.values():
        if template.slots:
            slot_parts = ", ".join(
                f"{name}: {spec.kind}" + ("" if spec.required else " (optional)")
                for name, spec in template.slots.items()
            )
        else:
            slot_parts = "no parameters"
        lines.append(f"- `{template.id}` - {template.description}")
        lines.append(f"  Parameters: {slot_parts}.")
    return "\n".join(lines)


def _render_template_instruction(question: BenchmarkQuestion) -> str:
    if not requires_executed_program(question):
        return _render_template_abstention_instruction(question)
    return f"""\
# P&ID review question (template-routed)

Answer one question about the engineering drawing mounted read-only under
`/input`, using the prebuilt, reviewed Datalog template pack. On the primary
path you author no Datalog and no answer JSON - only one routing JSON.

- `/input/graph_facts.json`: the canonical graph-mirrored base fact layer.
- `/input/graph_inspection.json`: a compact answer-neutral node/edge index
  containing every graph UUID, label, tag, edge label, and `attr_name`.
- `/input/graph_facts.dl` and `/input/graph_topology_semantics.dl`: the
  frozen EDB/IDB layers the templates execute over.
- `/input/route_query.py`: the routing helper (validate, render, execute).
- `/input/run_query.py`: the bounded execution helper (fallback path only).

## Question

{question.question}

## Method: route, validate, execute, observe

1. Read `/input/graph_inspection.json` with bounded inspection (`grep`,
   `head`, standard-library Python) to learn the exact labels and tag names
   present in this drawing.
2. Edit the preloaded `/workspace/{ROUTING_FILENAME}` to exactly one routing
   object: `{{"category": "<template id>", "parameters": {{...}}}}`.

   Categories:

{_render_category_lines()}

   Label and tag parameters must copy values exactly from the inspection
   index; validation is closed-world over this drawing's vocabulary.
3. Execute the routing:

   `python3 /input/route_query.py /workspace/{ROUTING_FILENAME}`

   On validation failure the helper prints every error together with the
   valid vocabulary; correct the routing and rerun. You have
   {VALIDATION_RETRY_BUDGET} corrective retries after the first failed
   attempt.
4. On success the helper renders the reviewed template into
   `/workspace/analysis.dl`, records the routing trace, executes it with the
   bounded engine lifecycle, prints the exact witness IDs, and checkpoints a
   valid structured answer automatically. Observe the executed output; if it
   does not answer the question, revise the routing and run it again. Base
   your conclusion on the final executed output only.

## Fallback ladder (only after the retry budget is exhausted)

If no template fits after {VALIDATION_RETRY_BUDGET} corrective retries,
fall back in order:

1. Author `/workspace/analysis.dl` directly (portable IDB rules only; never
   hard-code drawing UUIDs) and execute
   `python3 /input/run_query.py /workspace/analysis.dl`. The fallback is
   recorded mechanically; leave your final `{ROUTING_FILENAME}` in place.
2. For a permission/defeasible-policy question, route
   `{{"category": "policy_abstention", "parameters": {{}}}}` instead - the
   helper checkpoints the closed abstention answer.

- The input is read-only. Do not attempt to modify it.
- Base your answer only on the drawing data under `/input`.

## Submission

The helpers write `/workspace/structured_answer.json` for you; never author
it by hand. Verify it exists and reflects your final executed run, and leave
`/workspace/{ROUTING_FILENAME}` (your final routing) plus
`/workspace/analysis.dl` in place - they ship with your answer for post-hoc
audit and the task is rejected without them.
"""


def _render_template_abstention_instruction(
    question: BenchmarkQuestion,
) -> str:
    return f"""\
# P&ID review question (policy-boundary control)

Answer one question about the engineering drawing mounted read-only under
`/input`.

## Question

{question.question}

## Required policy behavior

This is a permission/defeasible-exception control. The monotone drawing facts
cannot soundly establish permission or resolve an exception. You must abstain,
and the abstention is packaged mechanically:

1. Edit `/workspace/{ROUTING_FILENAME}` to exactly:

   ```json
   {{"category": "policy_abstention", "parameters": {{}}}}
   ```

2. Execute: `python3 /input/route_query.py /workspace/{ROUTING_FILENAME}`

The helper writes the exact closed abstention answer to
`/workspace/structured_answer.json` and prints an accepted checkpoint
receipt. Do not author or execute any Datalog program for this question, and
do not hand-author the structured answer; the abstention policy step is
mechanically checked after submission - a source conclusion or witness fails.
"""
