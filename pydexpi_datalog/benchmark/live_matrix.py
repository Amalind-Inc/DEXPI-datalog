"""Resumable single-entry-point execution of the full live benchmark matrix.

This module is execution tooling, not a test harness: it constructs all four
architectures for Sonnet, GPT, and DeepSeek, runs the same combined 75-question
manifest through each, archives every run report, and invokes the locked results
report decision rule.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from pydexpi_datalog.benchmark.agentic_arm import (
    BUNDLE_FILES,
    EpisodeBudgets,
    create_agentic_arm,
)
from pydexpi_datalog.benchmark.answer_quality import (
    AnswerQualityJudge,
    ModelAnswerQualityJudge,
)
from pydexpi_datalog.benchmark.direct_arm import create_direct_arm
from pydexpi_datalog.benchmark.incumbent_arm import create_incumbent_arm
from pydexpi_datalog.benchmark.results import (
    RESULTS_REPORT_FILENAME,
    RUN_INDEX_SCHEMA_VERSION,
    generate_results_report,
    load_run_index,
)
from pydexpi_datalog.benchmark.runner import (
    BENCHMARK_REPORT_FILENAME,
    BENCHMARK_REPORT_SCHEMA_VERSION,
    ArmAdapter,
    run_benchmark,
)
from pydexpi_datalog.benchmark.souffle_arm import create_souffle_arm
from pydexpi_datalog.benchmark.synthetic import generate_synthetic_slice
from pydexpi_datalog.benchmark.trap_rubric import ModelTrapJudge, TrapJudge
from pydexpi_datalog.export.pipeline import write_bundle_derivatives

LIVE_MATRIX_MODELS = ("sonnet", "gpt", "deepseek")
DEFAULT_HAND_AUTHORED_MANIFEST = Path("testdata/benchmark/hand_authored_manifest.json")
DEFAULT_TRAP_MANIFEST = Path("testdata/benchmark/trap_manifest.json")
RUN_INDEX_FILENAME = "runs.json"
COMBINED_MANIFEST_FILENAME = "combined_manifest.json"

ArmFactory = Callable[[str, EpisodeBudgets, Path], ArmAdapter]


@dataclass(frozen=True)
class LiveArmSpec:
    """One model-independent architecture configuration in the matrix."""

    configuration: str
    arm_family: str
    factory: ArmFactory


def build_combined_manifest(
    *,
    manifest_paths: Sequence[Path],
    output_path: Path,
    budgets: EpisodeBudgets,
) -> Path:
    """Merge slice manifests and rebase every drawing reference absolutely."""
    if not manifest_paths:
        raise ValueError("At least one slice manifest is required.")

    questions: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    fidelity: dict[str, object] | None = None
    for manifest_path in manifest_paths:
        source_path = manifest_path.resolve()
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("questions"), list):
            raise ValueError(f"Benchmark manifest has no questions list: {source_path}")
        source_fidelity = raw.get("fidelity")
        if source_fidelity is not None:
            if not isinstance(source_fidelity, dict):
                raise ValueError(f"Manifest fidelity must be an object: {source_path}")
            if fidelity is not None and fidelity != source_fidelity:
                raise ValueError(
                    "Combined manifests declare conflicting fidelity limits."
                )
            fidelity = dict(source_fidelity)
        for raw_question in raw["questions"]:
            if not isinstance(raw_question, dict):
                raise ValueError(f"Manifest question must be an object: {source_path}")
            question = dict(raw_question)
            question_id = question.get("id")
            drawing = question.get("drawing")
            if not isinstance(question_id, str) or not question_id:
                raise ValueError(
                    f"Manifest question requires a non-empty id: {source_path}"
                )
            if question_id in seen_ids:
                raise ValueError(
                    f"Duplicate question id across manifests: {question_id}"
                )
            if not isinstance(drawing, str) or not drawing:
                raise ValueError(f"Question {question_id!r} requires a drawing path.")
            drawing_path = Path(drawing).expanduser()
            if not drawing_path.is_absolute():
                drawing_path = source_path.parent / drawing_path
            question["drawing"] = str(drawing_path.resolve())
            seen_ids.add(question_id)
            questions.append(question)

    payload: dict[str, object] = {
        "schema_version": 2,
        "episode_budgets": asdict(budgets),
        "questions": questions,
    }
    if fidelity is not None:
        payload["fidelity"] = fidelity
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output_path, payload)
    return output_path


def default_live_arm_specs(
    *, kira_dir: Path, environ: Mapping[str, str] | None = None
) -> tuple[LiveArmSpec, ...]:
    """Construct the four pre-committed architecture configurations."""
    env = dict(os.environ if environ is None else environ)

    def direct(model: str, budgets: EpisodeBudgets, artifact_root: Path) -> ArmAdapter:
        del budgets, artifact_root
        return create_direct_arm(model, environ=env)

    def agentic(model: str, budgets: EpisodeBudgets, artifact_root: Path) -> ArmAdapter:
        arm = create_agentic_arm(model, kira_dir=kira_dir, budgets=budgets, environ=env)
        return replace(arm, artifact_root=artifact_root)

    def incumbent(
        model: str, budgets: EpisodeBudgets, artifact_root: Path
    ) -> ArmAdapter:
        del budgets, artifact_root
        return create_incumbent_arm(model, environ=env)

    def souffle(model: str, budgets: EpisodeBudgets, artifact_root: Path) -> ArmAdapter:
        arm = create_souffle_arm(model, kira_dir=kira_dir, budgets=budgets, environ=env)
        return replace(arm, artifact_root=artifact_root)

    return (
        LiveArmSpec("a-direct", "arm_a", direct),
        LiveArmSpec("a-agentic", "arm_a", agentic),
        LiveArmSpec("b-incumbent", "arm_b", incumbent),
        LiveArmSpec("c-souffle", "arm_c", souffle),
    )


def create_live_trap_judge(
    *, environ: Mapping[str, str] | None = None
) -> ModelTrapJudge:
    """Use the fixed DeepSeek Flash route for informational trap judging."""
    direct = create_direct_arm("deepseek_flash", environ=dict(environ or os.environ))
    return ModelTrapJudge(provider=direct.provider)


def create_live_answer_quality_judge(
    *, environ: Mapping[str, str] | None = None
) -> ModelAnswerQualityJudge:
    """Use the cheap fixed DeepSeek Flash route for qualitative judging."""
    direct = create_direct_arm("deepseek_flash", environ=dict(environ or os.environ))
    return ModelAnswerQualityJudge(provider=direct.provider)


def materialize_live_bundles(*, manifest_path: Path, output_dir: Path) -> Path:
    """Expand facts-only real fixtures into self-contained live-arm bundles."""
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError(f"Combined manifest has no questions list: {manifest_path}")
    materialized: dict[Path, Path] = {}
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError(
                f"Combined manifest question must be an object: {manifest_path}"
            )
        drawing = Path(str(question.get("drawing", ""))).resolve()
        if drawing.is_dir() and all(
            (drawing / name).is_file() for name in BUNDLE_FILES
        ):
            continue
        graph_path = drawing / "graph_facts.json" if drawing.is_dir() else drawing
        if graph_path in materialized:
            question["drawing"] = str(materialized[graph_path])
            continue
        artifact = json.loads(graph_path.read_text(encoding="utf-8"))
        source_value = artifact.get("source_path")
        if not isinstance(source_value, str) or not source_value:
            raise ValueError(
                f"Graph artifact has no source_path for live bundle: {graph_path}"
            )
        source_path = Path(source_value).expanduser()
        if not source_path.is_absolute():
            source_path = Path.cwd() / source_path
        if not source_path.is_file():
            raise FileNotFoundError(
                f"DEXPI source for live bundle does not exist: {source_path}"
            )
        fixture_id = str(artifact.get("fixture_id") or graph_path.parent.name)
        bundle_dir = output_dir / fixture_id
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        bundle_dir.mkdir(parents=True)
        shutil.copyfile(source_path, bundle_dir / "drawing.xml")
        shutil.copyfile(graph_path, bundle_dir / "graph_facts.json")
        write_bundle_derivatives(
            bundle_dir=bundle_dir,
            artifact=artifact,
            source_reference=str(source_path),
        )
        resolved_bundle = bundle_dir.resolve()
        materialized[graph_path] = resolved_bundle
        question["drawing"] = str(resolved_bundle)
    _write_json_atomic(manifest_path, payload)
    return manifest_path


def run_live_matrix(
    *,
    manifest_paths: Sequence[Path],
    output_dir: Path,
    arm_specs: Sequence[LiveArmSpec],
    models: Sequence[str] = LIVE_MATRIX_MODELS,
    budgets: EpisodeBudgets = EpisodeBudgets(),
    trap_judge: TrapJudge | None = None,
    answer_quality_judge: AnswerQualityJudge | None = None,
    materialize_bundles: bool = False,
    max_workers: int = 3,
) -> dict[str, object]:
    """Execute or resume every configuration x model run and compute verdict."""
    if not arm_specs:
        raise ValueError("At least one live arm configuration is required.")
    unknown_models = sorted(set(models) - set(LIVE_MATRIX_MODELS))
    if unknown_models:
        raise ValueError(f"Unknown live matrix models: {unknown_models}")

    output_dir = output_dir.resolve()
    combined_manifest = build_combined_manifest(
        manifest_paths=manifest_paths,
        output_path=output_dir / "inputs" / COMBINED_MANIFEST_FILENAME,
        budgets=budgets,
    )
    if materialize_bundles:
        materialize_live_bundles(
            manifest_path=combined_manifest,
            output_dir=output_dir / "inputs" / "real_bundles",
        )
    question_ids = _manifest_question_ids(combined_manifest)
    run_index_path = output_dir / RUN_INDEX_FILENAME
    matrix = [(spec, model) for spec in arm_specs for model in models]

    def execute_run(item: tuple[LiveArmSpec, str]) -> dict[str, str]:
        spec, model = item
        run_dir = output_dir / "runs" / spec.configuration / model
        arm = spec.factory(model, budgets, run_dir / "harbor")
        report_path = run_dir / BENCHMARK_REPORT_FILENAME
        if not _completed_report(
            report_path=report_path,
            arm_id=arm.arm_id,
            question_ids=question_ids,
        ):
            print(f"Starting live run: {spec.configuration} x {model}", flush=True)
            run_benchmark(
                manifest_path=combined_manifest,
                arm=arm,
                output_dir=run_dir,
                trap_judge=trap_judge,
                answer_quality_judge=answer_quality_judge,
                episode_workers=(
                    2 if spec.configuration in {"a-agentic", "c-souffle"} else 1
                ),
            )
            print(f"Completed live run: {spec.configuration} x {model}", flush=True)
        return {
            "configuration": spec.configuration,
            "arm": arm.arm_id,
            "arm_family": spec.arm_family,
            "model": model,
            "report": str(report_path.relative_to(output_dir)),
        }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        entries = list(executor.map(execute_run, matrix))
    _write_json_atomic(
        run_index_path,
        {"schema_version": RUN_INDEX_SCHEMA_VERSION, "runs": entries},
    )

    runs = load_run_index(run_index_path)
    report = generate_results_report(runs=runs, output_dir=output_dir)
    combined_payload = json.loads(combined_manifest.read_text(encoding="utf-8"))
    report["execution"] = {
        "completed_at": datetime.now(UTC).isoformat(),
        "combined_manifest": str(combined_manifest.relative_to(output_dir)),
        "episode_budgets": asdict(budgets),
        "agentic_budget_evidence": {
            spec.configuration: asdict(budgets)
            for spec in arm_specs
            if spec.configuration in {"a-agentic", "c-souffle"}
        },
        "fidelity": combined_payload.get("fidelity"),
        "models": list(models),
        "configurations": [spec.configuration for spec in arm_specs],
        "run_index": RUN_INDEX_FILENAME,
    }
    _write_json_atomic(output_dir / RESULTS_REPORT_FILENAME, report)
    return report


def run_default_live_matrix(
    *,
    output_dir: Path,
    kira_dir: Path,
    hand_authored_manifest: Path = DEFAULT_HAND_AUTHORED_MANIFEST,
    trap_manifest: Path = DEFAULT_TRAP_MANIFEST,
    models: Sequence[str] = LIVE_MATRIX_MODELS,
    environ: Mapping[str, str] | None = None,
) -> int:
    """CLI entry: generate synthetic data, run/resume matrix, print verdict."""
    output_dir = output_dir.resolve()
    synthetic_dir = output_dir / "inputs" / "synthetic"
    synthetic = generate_synthetic_slice(output_dir=synthetic_dir)
    budgets = EpisodeBudgets()
    env = dict(os.environ if environ is None else environ)
    report = run_live_matrix(
        manifest_paths=(
            hand_authored_manifest,
            Path(synthetic["manifest_path"]),
            trap_manifest,
        ),
        output_dir=output_dir,
        arm_specs=default_live_arm_specs(kira_dir=kira_dir, environ=env),
        models=models,
        budgets=budgets,
        answer_quality_judge=create_live_answer_quality_judge(environ=env),
        trap_judge=create_live_trap_judge(environ=env),
        materialize_bundles=True,
    )
    print(f"Results report: {output_dir / RESULTS_REPORT_FILENAME}")
    print(report["decision"]["verdict_line"])  # type: ignore[index]
    return 0


def _manifest_question_ids(path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(question["id"]) for question in raw["questions"]}


def _completed_report(
    *, report_path: Path, arm_id: str, question_ids: set[str]
) -> bool:
    if not report_path.is_file():
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(report, dict):
        return False
    episodes = report.get("episodes")
    if (
        report.get("schema_version") != BENCHMARK_REPORT_SCHEMA_VERSION
        or report.get("arm_id") != arm_id
        or not isinstance(episodes, list)
    ):
        return False
    return {
        str(episode.get("question_id"))
        for episode in episodes
        if isinstance(episode, dict)
    } == question_ids


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.tmp")
    staging.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    staging.replace(path)
