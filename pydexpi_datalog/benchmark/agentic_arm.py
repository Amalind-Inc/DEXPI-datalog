"""Arm A agentic: Harbor/Terminus-KIRA sandbox episodes.

The agent works in a sandboxed Terminus episode with the drawing bundle and a
terminal — python/NetworkX allowed, NO Souffle, NO rule packs, NO bespoke
confirmation machinery.  It executes its own read-only analysis, observes
real output, revises, and submits ``/workspace/structured_answer.json``
through Harbor's independent verification gate.  This module maps that
episode outcome to the benchmark's :class:`StructuredAnswer`.

Seams (per the 3q1.1 spike findings):

- ``build_harbor_task`` generates a Harbor task (instruction, ``task.toml``,
  Docker environment, verifier) from one drawing bundle.  The bundle is
  mounted read-only: root-owned mode-``0555`` ``/input`` with mode-``0444``
  files, and the verifier independently rejects changed input content.
- :class:`EpisodeRunner` is the episode interface.  Tests script it; the
  live :class:`HarborKiraEpisodeRunner` shells out to ``harbor run`` with
  the released Terminus-KIRA agent.
- :class:`EpisodeBudgets` makes tool/round budgets explicit, loadable from
  the run manifest, and identical across agentic arms (Arm C must load the
  same budgets).  Harbor/KIRA has no native per-command budget, so the
  adapter enforces ``max_commands`` by post-run rejection and records the
  accounting in ``usage``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence, Protocol, runtime_checkable

from pydexpi_datalog.benchmark.contract import (
    POSTURES,
    StructuredAnswer,
    VERDICTS,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.direct_arm import (
    DEGRADED_VERDICT,
    parse_structured_answer,
)
from pydexpi_datalog.benchmark.rmso_openrouter_gateway import (
    LockedOpenRouterGateway,
)

# Friendly model keys -> LiteLLM model strings routed through OpenRouter,
# mirroring the direct arm's model matrix: one credential, one gateway.
AGENTIC_ARM_MODELS = {
    "sonnet": "openrouter/anthropic/claude-sonnet-4",
    "gpt": "openrouter/openai/gpt-5.4",
    "deepseek": "openrouter/deepseek/deepseek-v4-flash",
}

# The 3q1.4 bundle layout the task environment mounts read-only.
BUNDLE_FILES = ("drawing.xml", "graph_facts.json", "graph.json", "README.md")
RAW_XML_INPUT_FILES = ("drawing.xml",)

ANSWER_FILENAME = "structured_answer.json"

# The executed Datalog program an engine-mediated arm ships for audit.
PROGRAM_FILENAME = "analysis.dl"
ANALYSIS_SCRIPT_FILENAME = "analysis.py"
ANALYSIS_REPLAY_FILENAME = "analysis_replay.json"
PERMISSION_CONTROL_IDS = frozenset(
    {
        "hq-permission-defeasible-control-small",
        "hq-permission-defeasible-control-large",
    }
)


def requires_analysis_replay(question: BenchmarkQuestion) -> bool:
    """Return whether Arm A must replay a raw-XML analysis for this entry."""
    return question.question_id not in PERMISSION_CONTROL_IDS


# --------------------------------------------------------------------------
# Budgets: explicit, manifest-configurable, shared across agentic arms
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeBudgets:
    """Per-episode tool/round budgets, recorded with every answer.

    ``max_turns`` is enforced natively by the harness (Terminus-2 agent
    argument).  ``max_commands`` is NOT natively enforced — one KIRA
    ``execute_commands`` call may batch several shell commands — so the
    adapter enforces it by post-run rejection, per the spike findings.
    """

    max_turns: int = 20
    max_commands: int = 40
    max_output_tokens: int = 8192
    agent_timeout_sec: float = 1800.0
    verifier_timeout_sec: float = 300.0


_BUDGET_FIELDS = (
    "max_turns",
    "max_commands",
    "max_output_tokens",
    "agent_timeout_sec",
    "verifier_timeout_sec",
)


def load_episode_budgets(manifest_path: Path) -> EpisodeBudgets:
    """Load the optional ``episode_budgets`` object from a run manifest.

    Every agentic arm must be constructed from the same loaded budgets so
    the arms run under genuinely equal limits.  Unknown fields and invalid
    values fail fast before any episode runs.
    """
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"run manifest is not a JSON object: {manifest_path}")
    raw_budgets = raw.get("episode_budgets", {})
    if not isinstance(raw_budgets, dict):
        raise ValueError(f"episode_budgets must be a JSON object: {manifest_path}")
    unknown = sorted(set(raw_budgets) - set(_BUDGET_FIELDS))
    if unknown:
        raise ValueError(f"unknown episode_budgets fields {unknown} in {manifest_path}")
    defaults = EpisodeBudgets()
    values: dict[str, object] = {}
    for name in ("max_turns", "max_commands", "max_output_tokens"):
        value = raw_budgets.get(name, getattr(defaults, name))
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer: {value!r}")
        values[name] = value
    for name in ("agent_timeout_sec", "verifier_timeout_sec"):
        value = raw_budgets.get(name, getattr(defaults, name))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{name} must be a positive number: {value!r}")
        values[name] = float(value)
    return EpisodeBudgets(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Harbor task generation from one drawing bundle
# --------------------------------------------------------------------------


def build_harbor_task(
    *,
    question: BenchmarkQuestion,
    drawing_ref: Path,
    output_dir: Path,
    budgets: EpisodeBudgets,
) -> Path:
    """Generate the Arm A agentic Harbor task for one benchmark question.

    The drawing bundle is copied into the Docker build context and mounted
    read-only inside the sandbox (root-owned ``0555`` ``/input`` with
    ``0444`` files).  The generated verifier independently rejects changed
    input content (by SHA-256) and a missing or non-JSON-object submission.
    The verifier never sees ground truth: correctness is graded by the
    benchmark grader, not inside the episode.
    """
    replay_required = requires_analysis_replay(question)
    raw_xml = _resolve_raw_xml(drawing_ref)
    return build_task(
        question=question,
        drawing_ref=drawing_ref,
        output_dir=output_dir,
        budgets=budgets,
        instruction=_render_instruction(question),
        tags=("arm-a-agentic", "pydexpi-datalog-1-3q1.8"),
        input_bundle_files=RAW_XML_INPUT_FILES,
        input_bundle_sources={"drawing.xml": raw_xml},
        extra_workspace_files=(ANALYSIS_SCRIPT_FILENAME,) if replay_required else (),
        replay_python_analysis=replay_required,
    )


def _resolve_raw_xml(drawing_ref: Path) -> Path:
    """Resolve the original XML without exposing graph provenance to Arm A."""
    direct = drawing_ref / "drawing.xml"
    if direct.is_file():
        return direct.resolve()
    provenance_path = drawing_ref / "graph_facts.json"
    if not provenance_path.is_file():
        raise FileNotFoundError(
            f"drawing bundle {drawing_ref} has neither drawing.xml nor graph provenance"
        )
    artifact = json.loads(provenance_path.read_text(encoding="utf-8"))
    source_path = artifact.get("source_path")
    if not isinstance(source_path, str) or not source_path or Path(source_path).is_absolute():
        raise FileNotFoundError(
            f"graph provenance has no repository-relative source_path: {provenance_path}"
        )
    for ancestor in drawing_ref.resolve().parents:
        candidate = ancestor / source_path
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"raw DEXPI source from {provenance_path} does not exist: {source_path}"
    )


def validate_bundle(
    drawing_ref: Path, *, required_files: Sequence[str] = BUNDLE_FILES
) -> Path:
    """Resolve and validate one 3q1.4 drawing bundle directory."""
    bundle_dir = drawing_ref.resolve()
    if not bundle_dir.is_dir():
        raise FileNotFoundError(
            f"drawing bundle directory does not exist: {bundle_dir}"
        )
    missing = [name for name in required_files if not (bundle_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"drawing bundle {bundle_dir} is missing files: {missing}"
        )
    return bundle_dir


def build_task(
    *,
    question: BenchmarkQuestion,
    drawing_ref: Path,
    output_dir: Path,
    budgets: EpisodeBudgets,
    instruction: str,
    tags: Sequence[str],
    extra_input_files: Mapping[str, str] | None = None,
    engine_setup: str = "",
    extra_workspace_files: Sequence[str] = (),
    input_bundle_files: Sequence[str] = BUNDLE_FILES,
    input_bundle_sources: Mapping[str, Path] | None = None,
    replay_python_analysis: bool = False,
    base_image: str = "python:3.12-slim",
    base_packages: Sequence[str] = ("tmux",),
) -> Path:
    """Shared Harbor task generation every agentic arm composes from.

    The arm delta is declarative: extra read-only input files (name ->
    content) beside the bundle, extra Dockerfile setup (e.g. installing an
    engine), the arm's prompt framing, and extra required workspace
    submissions preserved for post-hoc audit.
    """
    bundle_sources = dict(input_bundle_sources or {})
    required_bundle_files = tuple(
        name for name in input_bundle_files if name not in bundle_sources
    )
    bundle_dir = validate_bundle(drawing_ref, required_files=required_bundle_files)

    task_dir = output_dir / f"benchmark-{question.question_id}"
    environment_dir = task_dir / "environment"
    tests_dir = task_dir / "tests"
    environment_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    extra_files = dict(extra_input_files or {})
    digests: dict[str, str] = {}
    for name in input_bundle_files:
        source = bundle_sources.get(name, bundle_dir / name)
        if not source.is_file():
            raise FileNotFoundError(f"missing task input source for {name}: {source}")
        shutil.copyfile(source, environment_dir / name)
        digests[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    for name, content in extra_files.items():
        (environment_dir / name).write_text(content, encoding="utf-8")
        digests[name] = hashlib.sha256(content.encode("utf-8")).hexdigest()

    input_names = tuple(input_bundle_files) + tuple(extra_files)
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")
    (task_dir / "task.toml").write_text(
        _render_task_toml(question=question, budgets=budgets, tags=tags),
        encoding="utf-8",
    )
    (environment_dir / "Dockerfile").write_text(
        _render_dockerfile(
            input_names,
            engine_setup=engine_setup,
            base_image=base_image,
            base_packages=base_packages,
        ),
        encoding="utf-8",
    )
    preserved = (ANSWER_FILENAME, *extra_workspace_files)
    test_sh_path = tests_dir / "test.sh"
    post_preserved = (ANALYSIS_REPLAY_FILENAME,) if replay_python_analysis else ()
    test_sh_path.write_text(
        _render_test_sh(preserved, post_preserved=post_preserved),
        encoding="utf-8",
    )
    test_sh_path.chmod(0o755)
    (tests_dir / "test_outputs.py").write_text(
        _render_verifier(
            digests,
            required_nonempty=tuple(extra_workspace_files),
            replay_python_analysis=replay_python_analysis,
        ),
        encoding="utf-8",
    )
    return task_dir


def _render_instruction(question: BenchmarkQuestion) -> str:
    if not requires_analysis_replay(question):
        return _render_agentic_permission_instruction(question)
    verdicts = json.dumps(list(VERDICTS))
    postures = json.dumps(list(POSTURES))
    return f"""\
# P&ID review question

Answer one question about the engineering drawing mounted read-only under
`/input`:

- `/input/drawing.xml`: the original DEXPI source drawing.

## Question

{question.question}

## Ground rules

- Analyze with the terminal: read the XML and run standard-library Python.
  Verify your reasoning against real command output before
  submitting.
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
        "kind": "xml_scope",
        "artifact": "drawing.xml",
        "sha256": the SHA-256 of the complete raw XML,
        "dependencies": []
      }},
      {{
        "id": "execution",
        "kind": "python_execution",
        "artifact": "analysis.py",
        "input": "drawing.xml",
        "output": "analysis_replay.json",
        "verdict": the submitted verdict,
        "witness_ids": the submitted witness IDs,
        "dependencies": ["scope"]
      }}
    ],
    "claims": one verdict claim plus one `witness:<ID>` claim per witness,
    each linked to the execution step
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
- Every witness ID must be copied exactly from `/input/drawing.xml`; never
  invent IDs.

Also write `/workspace/{ANALYSIS_SCRIPT_FILENAME}`. It must use only the
Python standard library, accept the raw XML path as its sole argument, and
write exactly one JSON object to stdout containing only `verdict` and
`witness_ids`. The verifier reruns it in the frozen sandbox and requires that
output to match the structured answer. It preserves the replay as
`{ANALYSIS_REPLAY_FILENAME}` for post-hoc audit.

Verify both submitted files exist before marking the task complete.
"""


def _render_agentic_permission_instruction(question: BenchmarkQuestion) -> str:
    return f"""\
# P&ID review question (policy-boundary control)

The complete raw DEXPI XML is mounted read-only at `/input/drawing.xml`.

## Question

{question.question}

This is a permission/defeasible-exception control. The monotone drawing source
cannot soundly establish permission or resolve an exception. You must abstain
and must not author or execute a verdict script.

Write `/workspace/{ANSWER_FILENAME}` with verdict `unanswerable`, no witnesses,
posture `source_data_unavailable`, a concise explanation of the limitation,
and this exact closed support graph:

```json
{{
  "steps": [{{
    "id": "policy",
    "kind": "policy_abstention",
    "operation": "permission_or_defeasible_not_decidable_from_monotone_drawing",
    "dependencies": []
  }}],
  "claims": [{{"claim": "verdict", "step_ids": ["policy"]}}]
}}
```

Do not create `/workspace/{ANALYSIS_SCRIPT_FILENAME}`.
"""


def _render_task_toml(
    *,
    question: BenchmarkQuestion,
    budgets: EpisodeBudgets,
    tags: Sequence[str],
) -> str:
    all_tags = ", ".join(
        json.dumps(tag) for tag in (*tags, question.question_id, question.slice)
    )
    return f"""\
version = "1.0"

[metadata]
author_name = "pyDEXPI Datalog benchmark"
difficulty_explanation = "One reasoning-architecture benchmark question over a drawing bundle."
category = "benchmark-episode"
tags = [{all_tags}]

[verifier]
timeout_sec = {budgets.verifier_timeout_sec}

[agent]
timeout_sec = {budgets.agent_timeout_sec}

[environment]
build_timeout_sec = 600.0
"""


def _render_dockerfile(
    input_names: Sequence[str],
    *,
    engine_setup: str = "",
    base_image: str = "python:3.12-slim",
    base_packages: Sequence[str] = ("tmux",),
) -> str:
    copy_lines = "\n".join(f"COPY {name} /input/{name}" for name in input_names)
    chmod_lines = " \\\n    && ".join(
        f"chown root:root /input/{name} && chmod 0444 /input/{name}"
        for name in input_names
    )
    packages = " ".join(base_packages)
    return f"""\
FROM {base_image}

RUN apt-get update \\
    && apt-get install -y --no-install-recommends {packages} \\
    && useradd --create-home --shell /bin/bash agent \\
    && mkdir /input /workspace \\
    && chown root:root /input \\
    && chmod 0555 /input \\
    && chown agent:agent /workspace \\
    && rm -rf /var/lib/apt/lists/*
{engine_setup}
{copy_lines}
RUN {chmod_lines}

WORKDIR /workspace
USER agent
"""


def _render_test_sh(
    preserved: Sequence[str], *, post_preserved: Sequence[str] = ()
) -> str:
    copy_lines = "\n".join(
        f"cp /workspace/{name} /logs/verifier/{name} 2>/dev/null || true"
        for name in preserved
    )
    post_copy_lines = "\n".join(
        f"cp /workspace/{name} /logs/verifier/{name} 2>/dev/null || true"
        for name in post_preserved
    )
    return f"""\
#!/bin/sh
set -eu

mkdir -p /logs/verifier
{copy_lines}
if python3 /tests/test_outputs.py; then
  {post_copy_lines}
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
"""


def _render_verifier(
    digests: Mapping[str, str],
    *,
    required_nonempty: Sequence[str] = (),
    replay_python_analysis: bool = False,
) -> str:
    """The independent verifier: input integrity + submission shape only.

    ``required_nonempty`` names extra workspace files that must exist with
    non-whitespace content (e.g. the executed Datalog program an
    engine-mediated arm ships for audit).  ``INPUT_DIR``/``WORKSPACE_DIR``
    environment overrides exist so the verifier logic itself is testable
    outside the container.
    """
    return f"""\
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

INPUT_DIR = Path(os.environ.get("INPUT_DIR", "/input"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
EXPECTED_SHA256 = {json.dumps(dict(digests), indent=4, sort_keys=True)}
REQUIRED_NONEMPTY = {json.dumps(list(required_nonempty))}
REPLAY_PYTHON_ANALYSIS = {replay_python_analysis!r}


def main() -> int:
    for name, expected in EXPECTED_SHA256.items():
        actual = hashlib.sha256((INPUT_DIR / name).read_bytes()).hexdigest()
        if actual != expected:
            raise AssertionError(f"read-only input was changed: {{name}}")

    answer_path = WORKSPACE_DIR / {json.dumps(ANSWER_FILENAME)}
    if not answer_path.exists():
        raise AssertionError(f"missing structured answer: {{answer_path}}")
    answer = json.loads(answer_path.read_text(encoding="utf-8"))
    if not isinstance(answer, dict):
        raise AssertionError(f"structured answer is not a JSON object: {{answer!r}}")
    for name in REQUIRED_NONEMPTY:
        path = WORKSPACE_DIR / name
        if not path.exists():
            raise AssertionError(f"missing required submission: {{path}}")
        if not path.read_text(encoding="utf-8").strip():
            raise AssertionError(f"required submission is empty: {{path}}")
    if REPLAY_PYTHON_ANALYSIS:
        script_path = WORKSPACE_DIR / {json.dumps(ANALYSIS_SCRIPT_FILENAME)}
        replay = subprocess.run(
            [sys.executable, str(script_path), str(INPUT_DIR / "drawing.xml")],
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if replay.returncode != 0:
            raise AssertionError(
                f"analysis replay failed ({{replay.returncode}}): {{replay.stderr}}"
            )
        try:
            replayed = json.loads(replay.stdout)
        except json.JSONDecodeError as error:
            raise AssertionError(f"analysis replay did not emit JSON: {{error}}")
        expected = {{
            "verdict": answer.get("verdict"),
            "witness_ids": answer.get("witness_ids"),
        }}
        if replayed != expected:
            raise AssertionError(
                f"analysis replay does not match structured answer: "
                f"{{replayed!r}} != {{expected!r}}"
            )
        (WORKSPACE_DIR / {json.dumps(ANALYSIS_REPLAY_FILENAME)}).write_text(
            json.dumps(replayed, sort_keys=True), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


# --------------------------------------------------------------------------
# The episode interface: scripted in tests, Harbor/KIRA live
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeResult:
    """What one sandbox episode produced, harness-agnostic.

    ``reward`` is Harbor's independent verifier outcome (``1.0`` = the
    submission exists, is a JSON object, and the read-only input is
    unchanged).  ``command_batches`` records the executed terminal analysis:
    one tuple per model command batch, in execution order.
    ``executed_program`` is the Datalog program an engine-mediated arm
    submitted beside its answer for post-hoc audit (``None`` for arms that
    do not execute Datalog).
    """

    structured_answer_text: str | None
    reward: float | None
    command_batches: tuple[tuple[str, ...], ...] = ()
    model_calls: int = 0
    usage: dict[str, object] = field(default_factory=dict)
    executed_program: str | None = None
    analysis_script: str | None = None
    analysis_replay_text: str | None = None


@runtime_checkable
class EpisodeRunner(Protocol):
    """The only contract an episode backend implements."""

    def run(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> EpisodeResult: ...


# --------------------------------------------------------------------------
# The benchmark adapter
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AgenticArm:
    """A sandbox-episode arm over any :class:`EpisodeRunner`.

    Arm A agentic by default; Arm C composes the same machinery with a
    Souffle task builder, its own arm label, and a question-aware executed
    program policy (see :mod:`pydexpi_datalog.benchmark.souffle_arm`).
    """

    runner: EpisodeRunner
    budgets: EpisodeBudgets
    model_name: str = "scripted"
    arm_label: str = "a-agentic"
    task_builder: Callable[..., Path] = build_harbor_task
    require_executed_program: bool | Callable[[BenchmarkQuestion], bool] = False
    program_validator: Callable[[str], None] | None = None
    program_faithfulness_gate: (
        Callable[[str, BenchmarkQuestion], Mapping[str, object] | None] | None
    ) = None
    answer_trace_gate: (
        Callable[
            [StructuredAnswer, Path, str | None, BenchmarkQuestion],
            Mapping[str, object],
        ]
        | None
    ) = None
    require_analysis_replay: bool | Callable[[BenchmarkQuestion], bool] = False
    analysis_trace_gate: (
        Callable[
            [StructuredAnswer, Path, str | None, str | None, BenchmarkQuestion],
            Mapping[str, object],
        ]
        | None
    ) = None
    artifact_root: Path | None = None

    @property
    def arm_id(self) -> str:
        return f"{self.arm_label}:{self.model_name}"

    def answer(
        self, *, question: BenchmarkQuestion, drawing_ref: Path
    ) -> StructuredAnswer:
        if self.artifact_root is None:
            with tempfile.TemporaryDirectory(prefix="pydexpi-agentic-") as temp:
                instruction, result = self._run_episode(
                    question=question,
                    drawing_ref=drawing_ref,
                    episode_dir=Path(temp),
                )
        else:
            episode_dir = self.artifact_root / question.question_id
            if episode_dir.exists():
                shutil.rmtree(episode_dir)
            episode_dir.mkdir(parents=True)
            instruction, result = self._run_episode(
                question=question,
                drawing_ref=drawing_ref,
                episode_dir=episode_dir,
            )

        transcript = self._transcript(instruction=instruction, result=result)
        usage = self._usage(result)

        commands = sum(len(batch) for batch in result.command_batches)
        if commands > self.budgets.max_commands:
            return self._degraded(
                "command_budget_exceeded", transcript=transcript, usage=usage
            )
        if result.reward != 1.0:
            return self._degraded(
                "verification_gate_rejected", transcript=transcript, usage=usage
            )
        program_required = (
            self.require_executed_program(question)
            if callable(self.require_executed_program)
            else self.require_executed_program
        )
        if program_required and not (result.executed_program or "").strip():
            return self._degraded(
                "missing_executed_program", transcript=transcript, usage=usage
            )
        analysis_required = (
            self.require_analysis_replay(question)
            if callable(self.require_analysis_replay)
            else self.require_analysis_replay
        )
        if analysis_required and (
            not (result.analysis_script or "").strip()
            or not (result.analysis_replay_text or "").strip()
        ):
            return self._degraded(
                "missing_analysis_replay", transcript=transcript, usage=usage
            )
        if self.program_validator is not None and result.executed_program is not None:
            try:
                self.program_validator(result.executed_program)
            except ValueError as error:
                return self._degraded(
                    "invalid_executed_program",
                    transcript=transcript,
                    usage={**usage, "program_validation_error": str(error)},
                )
        if (
            self.program_faithfulness_gate is not None
            and result.executed_program is not None
        ):
            try:
                gate = self.program_faithfulness_gate(
                    result.executed_program, question
                )
            except ValueError as error:
                return self._degraded(
                    "faithfulness_gate_error",
                    transcript=transcript,
                    usage={**usage, "faithfulness_gate_error": str(error)},
                )
            if gate is not None:
                usage = {**usage, "faithfulness_gate": dict(gate)}
                if gate.get("passed") is not True:
                    return self._degraded(
                        "faithfulness_gate_failed",
                        transcript=transcript,
                        usage=usage,
                    )
        if result.structured_answer_text is None:
            return self._degraded(
                "missing_submission", transcript=transcript, usage=usage
            )
        parsed = parse_structured_answer(result.structured_answer_text)
        if parsed.verdict == DEGRADED_VERDICT:
            return self._degraded(
                "malformed_submission", transcript=transcript, usage=usage
            )
        if self.answer_trace_gate is not None:
            try:
                trace_report = self.answer_trace_gate(
                    parsed, drawing_ref, result.executed_program, question
                )
            except ValueError as error:
                return self._degraded(
                    "audit_trace_error",
                    transcript=transcript,
                    usage={**usage, "audit_trace_error": str(error)},
                )
            usage = {**usage, "audit_trace": dict(trace_report)}
            if trace_report.get("trace_safe") is not True:
                return self._degraded(
                    "audit_trace_unsafe", transcript=transcript, usage=usage
                )
        if self.analysis_trace_gate is not None:
            try:
                trace_report = self.analysis_trace_gate(
                    parsed,
                    drawing_ref,
                    result.analysis_script,
                    result.analysis_replay_text,
                    question,
                )
            except ValueError as error:
                return self._degraded(
                    "audit_trace_error",
                    transcript=transcript,
                    usage={**usage, "audit_trace_error": str(error)},
                )
            usage = {**usage, "audit_trace": dict(trace_report)}
            if trace_report.get("trace_safe") is not True:
                return self._degraded(
                    "audit_trace_unsafe", transcript=transcript, usage=usage
                )
        return StructuredAnswer(
            verdict=parsed.verdict,
            witness_ids=parsed.witness_ids,
            posture=parsed.posture,
            answer_text=parsed.answer_text,
            support=parsed.support,
            transcript=transcript,
            usage=usage,
        )

    def _run_episode(
        self,
        *,
        question: BenchmarkQuestion,
        drawing_ref: Path,
        episode_dir: Path,
    ) -> tuple[str, EpisodeResult]:
        task_dir = self.task_builder(
            question=question,
            drawing_ref=drawing_ref,
            output_dir=episode_dir / "tasks",
            budgets=self.budgets,
        )
        instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
        result = self.runner.run(
            task_dir=task_dir,
            jobs_dir=episode_dir / "jobs",
            budgets=self.budgets,
        )
        return instruction, result

    def _transcript(
        self, *, instruction: str, result: EpisodeResult
    ) -> tuple[dict[str, object], ...]:
        entries: list[dict[str, object]] = [{"role": "user", "content": instruction}]
        for batch in result.command_batches:
            entries.append(
                {
                    "role": "tool",
                    "tool_name": "execute_commands",
                    "commands": list(batch),
                }
            )
        if result.executed_program is not None:
            entries.append(
                {
                    "role": "tool",
                    "tool_name": "executed_datalog_program",
                    "content": result.executed_program,
                }
            )
        if result.analysis_script is not None:
            entries.append(
                {
                    "role": "tool",
                    "tool_name": "executed_python_analysis",
                    "content": result.analysis_script,
                }
            )
        if result.analysis_replay_text is not None:
            entries.append(
                {
                    "role": "tool",
                    "tool_name": "captured_analysis_replay",
                    "content": result.analysis_replay_text,
                }
            )
        entries.append(
            {
                "role": "assistant",
                "content": result.structured_answer_text
                or "No structured answer was submitted.",
            }
        )
        return tuple(entries)

    def _usage(self, result: EpisodeResult) -> dict[str, object]:
        usage = dict(result.usage)
        usage["budgets"] = asdict(self.budgets)
        usage["command_batches"] = len(result.command_batches)
        usage["commands"] = sum(len(batch) for batch in result.command_batches)
        usage["model_calls"] = result.model_calls
        return usage

    def _degraded(
        self,
        reason: str,
        *,
        transcript: tuple[dict[str, object], ...],
        usage: dict[str, object],
    ) -> StructuredAnswer:
        return StructuredAnswer(
            verdict=DEGRADED_VERDICT,
            witness_ids=(),
            posture="unspecified",
            transcript=transcript,
            usage={**usage, "degraded_reason": reason},
        )


# --------------------------------------------------------------------------
# Live Harbor/Terminus-KIRA episode runner
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HarborKiraEpisodeRunner:
    """Runs one Harbor Docker episode with the released Terminus-KIRA agent.

    Only used for live matrix runs; CI never constructs Docker episodes.
    ``build_command`` is pure so the exact invocation is testable.
    """

    kira_dir: Path
    model: str
    api_base: str | None = None
    request_gateway: LockedOpenRouterGateway | None = None
    agent_import_path: str = "terminus_kira.terminus_kira:TerminusKira"
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))

    def build_command(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> tuple[str, ...]:
        command = [
            "uv",
            "run",
            "--directory",
            str(self.kira_dir),
            "harbor",
            "run",
            "--path",
            str(task_dir.parent),
            "--task-name",
            task_dir.name,
            "--agent-import-path",
            self.agent_import_path,
            "--model",
            self.model,
            "--agent-kwarg",
            f"max_turns={budgets.max_turns}",
            "--agent-kwarg",
            "model_info="
            + json.dumps(
                {"max_output_tokens": budgets.max_output_tokens},
                separators=(",", ":"),
            ),
            "--env",
            "docker",
            "--jobs-dir",
            str(jobs_dir),
        ]
        if self.api_base is not None:
            command[-4:-4] = ["--agent-kwarg", f"api_base={self.api_base}"]
        return tuple(command)

    def run(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> EpisodeResult:
        if self.request_gateway is not None:
            with self.request_gateway as gateway:
                command = replace(
                    self,
                    api_base=gateway.base_url,
                    request_gateway=None,
                ).build_command(
                    task_dir=task_dir,
                    jobs_dir=jobs_dir,
                    budgets=budgets,
                )
                return self._run_command(
                    command=command,
                    jobs_dir=jobs_dir,
                    budgets=budgets,
                )
        command = self.build_command(
            task_dir=task_dir, jobs_dir=jobs_dir, budgets=budgets
        )
        return self._run_command(command=command, jobs_dir=jobs_dir, budgets=budgets)

    def _run_command(
        self,
        *,
        command: tuple[str, ...],
        jobs_dir: Path,
        budgets: EpisodeBudgets,
    ) -> EpisodeResult:
        try:
            subprocess.run(
                command,
                check=False,
                env=dict(self.environ),
                timeout=budgets.agent_timeout_sec,
            )
        except subprocess.TimeoutExpired:
            partial = parse_harbor_artifacts(jobs_dir)
            return EpisodeResult(
                structured_answer_text=partial.structured_answer_text,
                reward=0.0,
                command_batches=partial.command_batches,
                model_calls=partial.model_calls,
                usage={
                    **partial.usage,
                    "timed_out": True,
                    "timeout_sec": budgets.agent_timeout_sec,
                },
                executed_program=partial.executed_program,
                analysis_script=partial.analysis_script,
                analysis_replay_text=partial.analysis_replay_text,
            )
        return parse_harbor_artifacts(jobs_dir)


def parse_harbor_artifacts(jobs_dir: Path) -> EpisodeResult:
    """Map Harbor's persisted episode artifacts into an :class:`EpisodeResult`.

    Reads the verifier reward, the copied structured answer, the executed
    Datalog program (engine-mediated arms), and the agent trajectory
    (terminal command batches and model call count).  Missing artifacts
    degrade to a rejected episode rather than crashing the run.
    """
    reward: float | None = None
    reward_files = sorted(jobs_dir.rglob("reward.txt"))
    if reward_files:
        try:
            reward = float(reward_files[0].read_text().strip())
        except ValueError:
            reward = None

    structured_answer_text: str | None = None
    answer_files = sorted(jobs_dir.rglob(ANSWER_FILENAME))
    if answer_files:
        structured_answer_text = answer_files[0].read_text(encoding="utf-8")

    executed_program: str | None = None
    program_files = sorted(jobs_dir.rglob(PROGRAM_FILENAME))
    if program_files:
        executed_program = program_files[0].read_text(encoding="utf-8")

    analysis_script: str | None = None
    script_files = sorted(jobs_dir.rglob(ANALYSIS_SCRIPT_FILENAME))
    if script_files:
        analysis_script = script_files[0].read_text(encoding="utf-8")

    analysis_replay_text: str | None = None
    replay_files = sorted(jobs_dir.rglob(ANALYSIS_REPLAY_FILENAME))
    if replay_files:
        analysis_replay_text = replay_files[0].read_text(encoding="utf-8")

    command_batches: list[tuple[str, ...]] = []
    model_calls = 0
    usage: dict[str, object] = {}
    for trajectory_path in sorted(jobs_dir.rglob("*trajectory*.json")):
        payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
        batches, calls, tokens = _walk_trajectory(payload)
        command_batches.extend(batches)
        model_calls += calls
        for key, value in tokens.items():
            current = usage.get(key, 0)
            if isinstance(current, (int, float)) and not isinstance(current, bool):
                usage[key] = current + value

    return EpisodeResult(
        structured_answer_text=structured_answer_text,
        reward=reward,
        command_batches=tuple(command_batches),
        model_calls=model_calls,
        usage=usage,
        executed_program=executed_program,
        analysis_script=analysis_script,
        analysis_replay_text=analysis_replay_text,
    )


def _walk_trajectory(
    value: object,
) -> tuple[list[tuple[str, ...]], int, dict[str, int | float]]:
    """Collect command batches, function-call count, and token totals."""
    batches: list[tuple[str, ...]] = []
    calls = 0
    tokens: dict[str, int | float] = {}
    if isinstance(value, dict):
        if "function_name" in value:
            calls += 1
            # The 3q1.1 spike observed Harbor's persisted trajectory naming
            # KIRA's terminal executions ``bash_command``; the model-side
            # tool schema calls it ``execute_commands``.  Accept both.
            if str(value["function_name"]) in ("bash_command", "execute_commands"):
                keystrokes = _keystrokes(value.get("arguments"))
                if keystrokes:
                    batches.append(keystrokes)
        for key in ("prompt_tokens", "completion_tokens"):
            raw = value.get(key)
            if isinstance(raw, int) and not isinstance(raw, bool):
                mapped = "input_tokens" if key == "prompt_tokens" else "output_tokens"
                tokens[mapped] = tokens.get(mapped, 0) + raw
        raw_cost = value.get("cost_usd")
        if isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool):
            tokens["cost_usd"] = tokens.get("cost_usd", 0) + raw_cost
        for child in value.values():
            child_batches, child_calls, child_tokens = _walk_trajectory(child)
            batches.extend(child_batches)
            calls += child_calls
            for key, count in child_tokens.items():
                tokens[key] = tokens.get(key, 0) + count
    elif isinstance(value, list):
        for child in value:
            child_batches, child_calls, child_tokens = _walk_trajectory(child)
            batches.extend(child_batches)
            calls += child_calls
            for key, count in child_tokens.items():
                tokens[key] = tokens.get(key, 0) + count
    return batches, calls, tokens


def _keystrokes(arguments: object) -> tuple[str, ...]:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return (arguments,)
    if isinstance(arguments, dict):
        raw_commands = arguments.get("commands")
        if isinstance(raw_commands, list):
            keystrokes = []
            for command in raw_commands:
                if isinstance(command, dict) and "keystrokes" in command:
                    keystrokes.append(str(command["keystrokes"]))
                elif isinstance(command, str):
                    keystrokes.append(command)
            return tuple(keystrokes)
        if "keystrokes" in arguments:
            return (str(arguments["keystrokes"]),)
    return ()


# --------------------------------------------------------------------------
# Live arm construction (used by the later live-matrix bead, never CI)
# --------------------------------------------------------------------------


def verify_agentic_answer_trace(
    answer: StructuredAnswer,
    drawing_ref: Path,
    analysis_script: str | None,
    analysis_replay_text: str | None,
    question: BenchmarkQuestion,
) -> dict[str, object]:
    """Verify captured Arm A replay artifacts without host-side execution."""
    from dataclasses import asdict

    from pydexpi_datalog.benchmark.audit_trace import verify_audit_trace

    xml_path = _resolve_raw_xml(drawing_ref) if drawing_ref.is_dir() else drawing_ref
    xml_digest = hashlib.sha256(xml_path.read_bytes()).hexdigest()
    if not requires_analysis_replay(question):
        if (analysis_script or "").strip() or (analysis_replay_text or "").strip():
            raise ValueError(
                "permission/defeasible controls must abstain without a verdict script"
            )
        return asdict(
            verify_audit_trace(
                answer=answer,
                graph_facts={},
                allow_policy_abstention=True,
            )
        )
    if not (analysis_script or "").strip() or not (
        analysis_replay_text or ""
    ).strip():
        raise ValueError("Arm A source conclusions require captured analysis replay")
    try:
        replayed = json.loads(analysis_replay_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"captured analysis replay is not JSON: {error}") from error
    if not isinstance(replayed, dict):
        raise ValueError("captured analysis replay must be a JSON object")
    return asdict(
        verify_audit_trace(
            answer=answer,
            graph_facts={},
            xml_sha256=xml_digest,
            replay_python=lambda artifact, output: replayed,
        )
    )


def create_agentic_arm(
    model_key: str,
    *,
    kira_dir: Path,
    budgets: EpisodeBudgets,
    environ: Mapping[str, str] | None = None,
    request_gateway: LockedOpenRouterGateway | None = None,
) -> AgenticArm:
    """Build the live Arm A agentic adapter for one friendly model key."""
    env = dict(os.environ if environ is None else environ)
    if model_key not in AGENTIC_ARM_MODELS:
        raise ValueError(
            f"unknown agentic arm model {model_key!r}; "
            f"expected one of {sorted(AGENTIC_ARM_MODELS)}"
        )
    if not env.get("OPENROUTER_API_KEY"):
        raise ValueError("OPENROUTER_API_KEY is required for live agentic episodes")
    runner = HarborKiraEpisodeRunner(
        kira_dir=kira_dir,
        model=AGENTIC_ARM_MODELS[model_key],
        environ=env,
        request_gateway=request_gateway,
    )
    return AgenticArm(
        runner=runner,
        budgets=budgets,
        model_name=model_key,
        require_analysis_replay=requires_analysis_replay,
        analysis_trace_gate=verify_agentic_answer_trace,
    )
