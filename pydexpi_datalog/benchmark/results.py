"""Results report generator with the locked decision rule (bead 3q1.13).

Aggregates per-run benchmark report artifacts into one results report:
accuracy per arm x model x slice x graph-size bucket with links to each
run's per-episode transcripts, plus the pre-committed decision rule
computed by code so the verdict line is emitted, never written.

The locked rule (parent PRD, 2026-07-09):

- Verdict tier: Sonnet + GPT. DeepSeek v4 is the cost story; it never
  decides. Trap-slice scores are reported, never gate.
- Metric: exact-verdict accuracy with checkable witnesses
  (``verdict_match`` and ``witness_match``), not posture.
- Bars: 98% on compliance/universal questions, 95% on retrieval/local,
  both under ONE shared strongest Arm-A configuration.
- Either verdict model failing either bar => build the engine-mediated
  system; only both passing => stand down.

"Strongest" is deterministic: among Arm-A configurations where both
verdict models ran, maximise the minimum bar margin across the four
gates (model x category), tie-broken by total margin then arm id. A
configuration clearing every gate therefore always outranks one that
fails any gate, regardless of episode volume.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from pydexpi_datalog.benchmark.dataset import (
    CATEGORY_COMPLIANCE_UNIVERSAL,
    CATEGORY_RETRIEVAL_LOCAL,
    QUESTION_CATEGORIES,
    SLICE_TRAP,
    SLICES,
)
from pydexpi_datalog.benchmark.runner import BENCHMARK_REPORT_SCHEMA_VERSION

RESULTS_REPORT_SCHEMA_VERSION = 1
RESULTS_REPORT_FILENAME = "results_report.json"
RUN_INDEX_SCHEMA_VERSION = 1

ARM_FAMILY_A = "arm_a"
ARM_FAMILY_B = "arm_b"
ARM_FAMILY_C = "arm_c"
ARM_FAMILIES = (ARM_FAMILY_A, ARM_FAMILY_B, ARM_FAMILY_C)

VERDICT_TIER_MODELS = ("sonnet", "gpt")
COST_STORY_MODELS = ("deepseek",)

# Bars in permille so boundary comparisons stay in exact integer arithmetic:
# 979/1000 fails 980 permille, 980/1000 meets it.
DECISION_BARS_PERMILLE = {
    CATEGORY_COMPLIANCE_UNIVERSAL: 980,
    CATEGORY_RETRIEVAL_LOCAL: 950,
}

DECISION_BUILD = "build_engine_mediated_system"
DECISION_STAND_DOWN = "stand_down"


class ResultsReportError(ValueError):
    """The supplied runs cannot safely produce a results report."""


@dataclass(frozen=True)
class BenchmarkRun:
    """One benchmark run artifact tagged for aggregation.

    ``configuration`` is the model-independent architecture configuration
    id (e.g. ``a-direct``); live ``arm_id`` values embed the model, so runs
    of different models can only be compared through this key.
    """

    configuration: str
    arm_id: str
    arm_family: str
    model: str
    report: Mapping[str, object]
    report_path: Path


# --------------------------------------------------------------------------
# Run index loading (CLI input)
# --------------------------------------------------------------------------


def load_run_index(path: Path) -> tuple[BenchmarkRun, ...]:
    """Load a runs-index JSON file and every run report it references.

    Fails fast on unknown arm families, missing fields, unreadable or
    schema-incompatible report artifacts, and index/report arm mismatches.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ResultsReportError(f"Cannot read run index {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ResultsReportError(
            f"Run index {path} is not valid JSON: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise ResultsReportError(f"Run index {path} must be a JSON object.")
    if raw.get("schema_version") != RUN_INDEX_SCHEMA_VERSION:
        raise ResultsReportError(
            f"Run index {path} has unsupported schema_version "
            f"{raw.get('schema_version')!r}; expected {RUN_INDEX_SCHEMA_VERSION}."
        )
    raw_runs = raw.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ResultsReportError(
            f"Run index {path} must declare a non-empty 'runs' list."
        )

    runs: list[BenchmarkRun] = []
    for index, raw_run in enumerate(raw_runs):
        if not isinstance(raw_run, dict):
            raise ResultsReportError(
                f"Run index entry at index {index} must be an object."
            )
        context = f"Run index entry at index {index}"
        configuration = _required_index_string(raw_run, "configuration", context)
        arm_id = _required_index_string(raw_run, "arm", context)
        arm_family = _required_index_string(raw_run, "arm_family", context)
        if arm_family not in ARM_FAMILIES:
            raise ResultsReportError(
                f"{context} has invalid arm_family {arm_family!r}; expected "
                f"one of {list(ARM_FAMILIES)!r}."
            )
        model = _required_index_string(raw_run, "model", context)
        report_value = _required_index_string(raw_run, "report", context)
        report_path = (path.parent / Path(report_value).expanduser()).resolve()
        report = _load_run_report(report_path)
        if report.get("arm_id") != arm_id:
            raise ResultsReportError(
                f"{context} declares arm {arm_id!r} but its report "
                f"{report_path} records arm_id {report.get('arm_id')!r}."
            )
        runs.append(
            BenchmarkRun(
                configuration=configuration,
                arm_id=arm_id,
                arm_family=arm_family,
                model=model,
                report=report,
                report_path=report_path,
            )
        )
    return tuple(runs)


def _required_index_string(raw: Mapping[str, object], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResultsReportError(f"{context} requires a non-empty string {field!r}.")
    return value


def _load_run_report(report_path: Path) -> Mapping[str, object]:
    try:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ResultsReportError(
            f"Cannot read run report {report_path}: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise ResultsReportError(
            f"Run report {report_path} is not valid JSON: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise ResultsReportError(f"Run report {report_path} must be a JSON object.")
    if raw.get("schema_version") != BENCHMARK_REPORT_SCHEMA_VERSION:
        raise ResultsReportError(
            f"Run report {report_path} has unsupported schema_version "
            f"{raw.get('schema_version')!r}; expected "
            f"{BENCHMARK_REPORT_SCHEMA_VERSION}."
        )
    return raw


# --------------------------------------------------------------------------
# Report generation
# --------------------------------------------------------------------------


def generate_results_report(
    *, runs: Sequence[BenchmarkRun], output_dir: Path
) -> dict[str, object]:
    """Aggregate run reports and persist ``results_report.json``."""
    validated = _validated_runs(runs)

    report: dict[str, object] = {
        "schema_version": RESULTS_REPORT_SCHEMA_VERSION,
        "runs": [
            {
                "configuration": run.configuration,
                "arm": run.arm_id,
                "arm_family": run.arm_family,
                "model": run.model,
                "report_path": str(run.report_path),
            }
            for run in validated
        ],
        "breakdown": _breakdown(validated),
        "decision": _decision(validated),
        "informational": _informational(validated),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / RESULTS_REPORT_FILENAME
    staging_path = output_dir / f".{RESULTS_REPORT_FILENAME}.tmp"
    staging_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    staging_path.replace(artifact_path)
    return report


def run_results_report(*, run_index_path: Path, output_dir: Path) -> int:
    """CLI entry: runs index -> results report artifact."""
    runs = load_run_index(run_index_path)
    report = generate_results_report(runs=runs, output_dir=output_dir)
    decision = report["decision"]
    print(f"Results report: {output_dir / RESULTS_REPORT_FILENAME}")
    print(decision["verdict_line"])  # type: ignore[index]
    return 0


def _validated_runs(runs: Sequence[BenchmarkRun]) -> tuple[BenchmarkRun, ...]:
    if not runs:
        raise ResultsReportError("At least one benchmark run is required.")
    seen: set[tuple[str, str]] = set()
    for run in runs:
        if run.arm_family not in ARM_FAMILIES:
            raise ResultsReportError(
                f"Run {run.arm_id!r} has invalid arm_family {run.arm_family!r}; "
                f"expected one of {list(ARM_FAMILIES)!r}."
            )
        key = (run.configuration, run.model)
        if key in seen:
            raise ResultsReportError(
                f"duplicate run for configuration {run.configuration!r} and "
                f"model {run.model!r}: each configuration x model pair must "
                "appear once."
            )
        seen.add(key)
        for episode in _episodes(run):
            _validate_episode(run, episode)
    return tuple(runs)


def _episodes(run: BenchmarkRun) -> list[Mapping[str, object]]:
    episodes = run.report.get("episodes")
    if not isinstance(episodes, list):
        raise ResultsReportError(
            f"Run report {run.report_path} has no 'episodes' list."
        )
    return episodes


def _validate_episode(run: BenchmarkRun, episode: object) -> None:
    if not isinstance(episode, Mapping):
        raise ResultsReportError(
            f"Run report {run.report_path} has a non-object episode entry; "
            "the report was tampered with or is malformed."
        )
    question_id = episode.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        raise ResultsReportError(
            f"Run report {run.report_path} has an episode without a question_id."
        )
    grade = episode.get("grade")
    if not isinstance(grade, Mapping):
        raise ResultsReportError(
            f"Run report {run.report_path} episode {question_id!r} has no grade object."
        )
    for field in ("passed", "verdict_match", "witness_match"):
        if not isinstance(grade.get(field), bool):
            raise ResultsReportError(
                f"Run report {run.report_path} episode {question_id!r} grade "
                f"field {field!r} must be a boolean, got "
                f"{grade.get(field)!r}; a malformed grade cannot be scored "
                "as an ordinary failure."
            )
    slice_name = episode.get("slice")
    if slice_name not in SLICES:
        raise ResultsReportError(
            f"Run report {run.report_path} episode {question_id!r} has "
            f"invalid slice {slice_name!r}; expected one of {list(SLICES)!r}."
        )
    # Gating eligibility is derived from the slice, never trusted from the
    # report boolean: trap can never gate, every other slice always does.
    expected_gating = slice_name != SLICE_TRAP
    if bool(episode.get("gating")) != expected_gating:
        raise ResultsReportError(
            f"Run report {run.report_path} episode {question_id!r} declares "
            f"gating={episode.get('gating')!r} but slice {slice_name!r} "
            f"requires gating={expected_gating!r}; the report was tampered "
            "with or produced by an incompatible runner."
        )
    category = episode.get("category")
    if expected_gating and category not in QUESTION_CATEGORIES:
        raise ResultsReportError(
            f"Run report {run.report_path} episode {question_id!r} is gating "
            f"but has no decision category; expected one of "
            f"{list(QUESTION_CATEGORIES)!r}. Regenerate the run from a "
            "category-carrying manifest."
        )
    if not expected_gating and category is not None:
        raise ResultsReportError(
            f"Run report {run.report_path} episode {question_id!r} has slice "
            f"'trap' but carries decision category {category!r}; trap scores "
            "never gate the decision rule."
        )


def _is_gating(episode: Mapping[str, object]) -> bool:
    """Slice-derived gating eligibility (validated against the report)."""
    return episode.get("slice") != SLICE_TRAP


# --------------------------------------------------------------------------
# Breakdown: arm x model x slice x size bucket
# --------------------------------------------------------------------------


def _breakdown(runs: Sequence[BenchmarkRun]) -> list[dict[str, object]]:
    cells: dict[tuple[str, str, str, str | None], dict[str, object]] = {}
    # Cell arm/arm_family attribution is safe because _validated_runs
    # enforces one run per (configuration, model): every episode landing in
    # a cell comes from the same run.
    for run in runs:
        for episode in _episodes(run):
            key = (
                run.configuration,
                run.model,
                str(episode.get("slice")),
                episode.get("size_bucket"),  # type: ignore[arg-type]
            )
            cell = cells.setdefault(
                key,
                {
                    "configuration": run.configuration,
                    "arm": run.arm_id,
                    "arm_family": run.arm_family,
                    "model": run.model,
                    "slice": key[2],
                    "size_bucket": key[3],
                    "questions": 0,
                    "passed": 0,
                    "failed": 0,
                    "exact_verdict_with_witnesses": 0,
                    "episodes": [],
                },
            )
            passed = bool(_grade(episode).get("passed"))
            cell["questions"] += 1  # type: ignore[operator]
            cell["passed"] += int(passed)  # type: ignore[operator]
            cell["failed"] += int(not passed)  # type: ignore[operator]
            cell["exact_verdict_with_witnesses"] += int(  # type: ignore[operator]
                _exact_verdict_with_witnesses(episode)
            )
            cell["episodes"].append(  # type: ignore[union-attr]
                {
                    "question_id": episode["question_id"],
                    "passed": passed,
                    "transcript_ref": {
                        "report_path": str(run.report_path),
                        "question_id": episode["question_id"],
                    },
                }
            )
    for cell in cells.values():
        questions = int(cell["questions"])  # type: ignore[arg-type]
        cell["accuracy"] = int(cell["passed"]) / questions  # type: ignore[arg-type]
        cell["exact_verdict_with_witnesses_accuracy"] = (
            int(cell["exact_verdict_with_witnesses"]) / questions  # type: ignore[arg-type]
        )
    return [
        cells[key]
        for key in sorted(cells, key=lambda key: (key[0], key[1], key[2], key[3] or ""))
    ]


def _grade(episode: Mapping[str, object]) -> Mapping[str, object]:
    grade = episode.get("grade")
    return grade if isinstance(grade, Mapping) else {}


def _exact_verdict_with_witnesses(episode: Mapping[str, object]) -> bool:
    grade = _grade(episode)
    return bool(grade.get("verdict_match")) and bool(grade.get("witness_match"))


def _gating_identity(
    run: BenchmarkRun,
) -> frozenset[tuple[str, str, str, str | None]]:
    """The identity set of a run's gating questions, duplicate IDs rejected."""
    identities: set[tuple[str, str, str, str | None]] = set()
    seen_question_ids: set[str] = set()
    for episode in _episodes(run):
        if not _is_gating(episode):
            continue
        question_id = str(episode.get("question_id"))
        if question_id in seen_question_ids:
            raise ResultsReportError(
                f"Run report {run.report_path} grades gating question "
                f"{question_id!r} more than once; duplicate episodes would "
                "inflate the decision counts."
            )
        seen_question_ids.add(question_id)
        identities.add(
            (
                question_id,
                str(episode.get("slice")),
                str(episode.get("category")),
                episode.get("size_bucket"),  # type: ignore[arg-type]
            )
        )
    return frozenset(identities)


def _require_identical_gating_questions(runs: Sequence[BenchmarkRun]) -> None:
    reference = runs[0]
    reference_identity = _gating_identity(reference)
    for run in runs[1:]:
        identity = _gating_identity(run)
        if identity != reference_identity:
            differing = sorted(
                question_id for question_id, *_ in reference_identity ^ identity
            )
            raise ResultsReportError(
                "Decision runs grade different gating question sets: "
                f"{run.report_path} (model {run.model!r}) disagrees with "
                f"{reference.report_path} (model {reference.model!r}) on "
                f"questions such as {differing[:3]!r}; the verdict is only "
                "comparable over one identical dataset."
            )


# --------------------------------------------------------------------------
# Decision rule
# --------------------------------------------------------------------------


def _decision(runs: Sequence[BenchmarkRun]) -> dict[str, object]:
    decision_runs: dict[str, dict[str, BenchmarkRun]] = {}
    for run in runs:
        if run.arm_family == ARM_FAMILY_A and run.model in VERDICT_TIER_MODELS:
            decision_runs.setdefault(run.configuration, {})[run.model] = run

    for model in VERDICT_TIER_MODELS:
        if not any(model in by_model for by_model in decision_runs.values()):
            raise ResultsReportError(
                f"Verdict-tier model {model!r} has no Arm-A run; the decision "
                "rule cannot be computed."
            )
    shared_configurations = sorted(
        configuration
        for configuration, by_model in decision_runs.items()
        if all(model in by_model for model in VERDICT_TIER_MODELS)
    )
    if not shared_configurations:
        raise ResultsReportError(
            "No Arm-A configuration was run by every verdict-tier model "
            f"{list(VERDICT_TIER_MODELS)!r}; one shared strongest "
            "configuration cannot be selected."
        )

    # The rule compares configurations and models over ONE dataset: every
    # considered decision run must have graded exactly the same gating
    # questions, or a run could shed hard questions and become "strongest".
    _require_identical_gating_questions(
        [
            decision_runs[configuration][model]
            for configuration in shared_configurations
            for model in VERDICT_TIER_MODELS
        ]
    )

    scored = [
        (_configuration_score(decision_runs[configuration]), configuration)
        for configuration in shared_configurations
    ]
    scored.sort(key=lambda item: (item[0][0], item[0][1], item[1]))
    strongest_configuration = scored[-1][1]
    strongest = decision_runs[strongest_configuration]

    models: dict[str, object] = {}
    failures: list[str] = []
    for model in VERDICT_TIER_MODELS:
        evaluation = _model_evaluation(strongest[model])
        models[model] = evaluation
        if not evaluation["passed"]:
            for category in QUESTION_CATEGORIES:
                gate = evaluation[category]
                if not gate["met_bar"]:  # type: ignore[index]
                    passed_count = gate["passed"]  # type: ignore[index]
                    total_count = gate["questions"]  # type: ignore[index]
                    percent = passed_count * 100 / total_count
                    failures.append(
                        f"{model} scored {passed_count}/{total_count} "
                        f"({percent:.6g}%, below the "
                        f"{DECISION_BARS_PERMILLE[category] / 10}% bar) on "
                        f"{category}"
                    )

    verdict = DECISION_BUILD if failures else DECISION_STAND_DOWN
    if failures:
        verdict_line = (
            "BUILD the engine-mediated system: "
            + "; ".join(failures)
            + f" under strongest Arm-A configuration {strongest_configuration!r}."
        )
    else:
        verdict_line = (
            "STAND DOWN: "
            + " and ".join(VERDICT_TIER_MODELS)
            + " both met the 98.0% compliance_universal and 95.0% "
            "retrieval_local exact-verdict-with-witnesses bars under "
            f"strongest Arm-A configuration {strongest_configuration!r}."
        )

    return {
        "rule": {
            "verdict_tier_models": list(VERDICT_TIER_MODELS),
            "metric": "exact_verdict_with_witnesses",
            "bars_permille": dict(DECISION_BARS_PERMILLE),
            "arm_family": ARM_FAMILY_A,
            "selection": (
                "one shared Arm-A configuration maximising the minimum bar "
                "margin across every verdict model and gating category"
            ),
        },
        "strongest_arm_a_configuration": strongest_configuration,
        "considered_arm_a_configurations": shared_configurations,
        "models": models,
        "verdict": verdict,
        "verdict_line": verdict_line,
        "inputs": [
            {
                "configuration": strongest_configuration,
                "arm": strongest[model].arm_id,
                "model": model,
                "report_path": str(strongest[model].report_path),
            }
            for model in VERDICT_TIER_MODELS
        ],
        "excluded": {
            "models": list(COST_STORY_MODELS),
            "slices": ["trap"],
            "reason": (
                "DeepSeek is the cost story and trap scores are "
                "informational; neither can move the verdict."
            ),
        },
    }


def _configuration_score(
    by_model: Mapping[str, BenchmarkRun],
) -> tuple[Fraction, Fraction]:
    """(min margin, total margin) across the four model x category gates."""
    margins: list[Fraction] = []
    for model in VERDICT_TIER_MODELS:
        counts = _gating_counts(by_model[model])
        for category in QUESTION_CATEGORIES:
            passed, total = counts[category]
            bar = Fraction(DECISION_BARS_PERMILLE[category], 1000)
            margins.append(Fraction(passed, total) - bar)
    return min(margins), sum(margins, Fraction(0))


def _gating_counts(run: BenchmarkRun) -> dict[str, tuple[int, int]]:
    counts = {category: [0, 0] for category in QUESTION_CATEGORIES}
    for episode in _episodes(run):
        if not _is_gating(episode):
            continue
        category = str(episode.get("category"))
        counts[category][1] += 1
        counts[category][0] += int(_exact_verdict_with_witnesses(episode))
    for category, (_passed, total) in counts.items():
        if total == 0:
            raise ResultsReportError(
                f"Decision run {run.arm_id!r} for model {run.model!r} has no "
                f"gating episodes in category {category!r}; the "
                f"{DECISION_BARS_PERMILLE[category] / 10}% bar cannot be "
                "assessed."
            )
    return {category: (passed, total) for category, (passed, total) in counts.items()}


def _model_evaluation(run: BenchmarkRun) -> dict[str, object]:
    counts = _gating_counts(run)
    evaluation: dict[str, object] = {
        "configuration": run.configuration,
        "arm": run.arm_id,
        "model": run.model,
    }
    passed_all = True
    for category, (passed, total) in counts.items():
        bar_permille = DECISION_BARS_PERMILLE[category]
        met_bar = passed * 1000 >= bar_permille * total
        passed_all = passed_all and met_bar
        evaluation[category] = {
            "passed": passed,
            "questions": total,
            "accuracy_percent": passed * 100 / total,
            "bar_percent": bar_permille / 10,
            "met_bar": met_bar,
        }
    evaluation["passed"] = passed_all
    return evaluation


# --------------------------------------------------------------------------
# Informational-only sections
# --------------------------------------------------------------------------


def _informational(runs: Sequence[BenchmarkRun]) -> dict[str, object]:
    return {
        "gating": False,
        "note": (
            "Latency and prose quality inform the follow-on spec; they "
            "never overturn correctness."
        ),
        "latency": _latency(runs),
        "prose_quality": _prose_quality(runs),
        "usage_and_cost": _usage_and_cost(runs),
    }


def _usage_and_cost(runs: Sequence[BenchmarkRun]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for run in runs:
        episodes = _episodes(run)
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        token_episodes = 0
        cost_usd = 0.0
        cost_episodes = 0
        for episode in episodes:
            tokens = episode.get("tokens")
            if isinstance(tokens, Mapping):
                values = (
                    tokens.get("input"),
                    tokens.get("output"),
                    tokens.get("total"),
                )
                if all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in values
                ):
                    input_tokens += int(values[0])
                    output_tokens += int(values[1])
                    total_tokens += int(values[2])
                    token_episodes += 1
            cost = episode.get("cost_usd")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                cost_usd += float(cost)
                cost_episodes += 1
        entries.append(
            {
                "configuration": run.configuration,
                "arm": run.arm_id,
                "model": run.model,
                "episodes": len(episodes),
                "episodes_with_token_accounting": token_episodes,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "episodes_with_cost_accounting": cost_episodes,
                "cost_usd": cost_usd,
            }
        )
    return entries


def _latency(runs: Sequence[BenchmarkRun]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for run in runs:
        wall_times = [
            float(episode.get("wall_time_seconds") or 0.0) for episode in _episodes(run)
        ]
        if not wall_times:
            continue
        entries.append(
            {
                "configuration": run.configuration,
                "arm": run.arm_id,
                "model": run.model,
                "episodes": len(wall_times),
                "mean_wall_time_seconds": sum(wall_times) / len(wall_times),
                "max_wall_time_seconds": max(wall_times),
            }
        )
    return entries


def _prose_quality(runs: Sequence[BenchmarkRun]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for run in runs:
        trap_episodes = [
            episode for episode in _episodes(run) if episode.get("slice") == SLICE_TRAP
        ]
        if not trap_episodes:
            continue
        entries.append(
            {
                "configuration": run.configuration,
                "arm": run.arm_id,
                "model": run.model,
                "trap_questions": len(trap_episodes),
                "trap_rubric_passed": _count_true(trap_episodes, "trap_rubric_passed"),
                "grounded_refusal": _count_true(trap_episodes, "grounded_refusal"),
                "graceful_redirect": _count_true(trap_episodes, "graceful_redirect"),
                "human_spot_check_question_ids": [
                    episode["question_id"]
                    for episode in trap_episodes
                    if episode.get("human_spot_check_required")
                ],
            }
        )
    return entries


def _count_true(episodes: Iterable[Mapping[str, object]], field: str) -> int:
    return sum(bool(_grade(episode).get(field)) for episode in episodes)
