"""Behavior tests for the results report generator (bead pydexpi-datalog-1-3q1.13).

The generator aggregates per-run benchmark reports into one results report:
accuracy per arm x model x slice x graph-size bucket with transcript links,
plus the locked decision rule computed by code. Sonnet + GPT must clear 98%
exact-verdict-with-witnesses on compliance/universal and 95% on
retrieval/local under one shared strongest Arm-A configuration; either
failing means build. DeepSeek and trap scores are present but never decide.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark import (
    ARM_FAMILY_A,
    ARM_FAMILY_B,
    DECISION_BUILD,
    DECISION_STAND_DOWN,
    RESULTS_REPORT_FILENAME,
    BenchmarkRun,
    ResultsReportError,
    generate_results_report,
    load_run_index,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Fixtures: fabricated run reports in the runner artifact schema
# --------------------------------------------------------------------------


def episode(
    question_id: str,
    *,
    slice_name: str = "hand_authored",
    category: str | None = "compliance_universal",
    size_bucket: str | None = None,
    passed: bool = True,
    verdict_match: bool | None = None,
    witness_match: bool | None = None,
    gating: bool = True,
    wall_time_seconds: float = 1.0,
    trap_rubric_passed: bool | None = None,
) -> dict[str, object]:
    return {
        "question_id": question_id,
        "question": "Does this fixture satisfy the stated condition?",
        "slice": slice_name,
        "category": category,
        "size_bucket": size_bucket,
        "gating": gating,
        "human_spot_check_required": False,
        "grade": {
            "passed": passed,
            "verdict_match": passed if verdict_match is None else verdict_match,
            "witness_match": passed if witness_match is None else witness_match,
            "posture_consistent": True,
            "trap_rubric_passed": trap_rubric_passed,
            "grounded_refusal": trap_rubric_passed,
            "graceful_redirect": trap_rubric_passed,
            "judge_rationale": None,
        },
        "wall_time_seconds": wall_time_seconds,
        "tokens": {"input": 10, "output": 5, "total": 15},
        "cost_usd": 0.001,
        "transcript": [{"role": "assistant", "content": "witnessed answer"}],
    }


def gating_episodes(
    *,
    compliance_passed: int,
    compliance_total: int,
    retrieval_passed: int = 19,
    retrieval_total: int = 20,
) -> list[dict[str, object]]:
    episodes: list[dict[str, object]] = []
    for index in range(compliance_total):
        episodes.append(
            episode(
                f"comp-{index:04d}",
                category="compliance_universal",
                passed=index < compliance_passed,
            )
        )
    for index in range(retrieval_total):
        episodes.append(
            episode(
                f"retr-{index:04d}",
                category="retrieval_local",
                passed=index < retrieval_passed,
            )
        )
    return episodes


def trap_episodes(*, rubric_passed: bool) -> list[dict[str, object]]:
    return [
        episode(
            "trap-0",
            slice_name="trap",
            category=None,
            passed=rubric_passed,
            gating=False,
            trap_rubric_passed=rubric_passed,
        )
    ]


def make_run(
    tmp_path: Path,
    *,
    configuration: str,
    arm: str | None = None,
    arm_family: str = ARM_FAMILY_A,
    model: str,
    episodes: list[dict[str, object]],
) -> BenchmarkRun:
    # Live arm ids embed the model (e.g. "a-direct:openrouter:...", or
    # "a-agentic:claude-sonnet-4"), so tests default to distinct per-model
    # arm ids sharing one model-independent configuration id.
    arm_id = arm if arm is not None else f"{configuration}:{model}"
    report = {
        "schema_version": 3,
        "arm_id": arm_id,
        "manifest_path": str(tmp_path / "manifest.json"),
        "trap_judge_id": "scripted-trap-judge",
        "episodes": episodes,
    }
    report_path = (
        tmp_path
        / f"{configuration}-{model}".replace(":", "_")
        / "benchmark_report.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return BenchmarkRun(
        configuration=configuration,
        arm_id=arm_id,
        arm_family=arm_family,
        model=model,
        report=report,
        report_path=report_path,
    )


def passing_matrix(tmp_path: Path) -> list[BenchmarkRun]:
    """Both verdict models clear both bars under one Arm-A configuration."""
    return [
        make_run(
            tmp_path,
            configuration="a-direct",
            model=model,
            episodes=gating_episodes(compliance_passed=1000, compliance_total=1000)
            + trap_episodes(rubric_passed=True),
        )
        for model in ("sonnet", "gpt")
    ] + [
        make_run(
            tmp_path,
            configuration="a-direct",
            model="deepseek",
            episodes=gating_episodes(compliance_passed=500, compliance_total=1000)
            + trap_episodes(rubric_passed=False),
        )
    ]


# --------------------------------------------------------------------------
# Breakdown: arm x model x slice x size bucket with transcript links
# --------------------------------------------------------------------------


def test_breakdown_cells_cover_arm_model_slice_and_size_bucket(
    tmp_path: Path,
) -> None:
    def arm_episodes() -> list[dict[str, object]]:
        return [
            episode("small-hit", slice_name="synthetic", size_bucket="small"),
            episode(
                "large-miss",
                slice_name="synthetic",
                size_bucket="large",
                passed=False,
            ),
            episode("hand-hit", slice_name="hand_authored"),
        ] + gating_episodes(compliance_passed=98, compliance_total=100)

    runs = [
        make_run(
            tmp_path,
            configuration="a-direct",
            model="sonnet",
            episodes=arm_episodes() + trap_episodes(rubric_passed=True),
        ),
        make_run(
            tmp_path,
            configuration="a-direct",
            model="gpt",
            episodes=arm_episodes(),
        ),
    ]

    report = generate_results_report(runs=runs, output_dir=tmp_path / "results")

    cells = {
        (
            cell["configuration"],
            cell["model"],
            cell["slice"],
            cell["size_bucket"],
        ): cell
        for cell in report["breakdown"]
    }
    small = cells[("a-direct", "sonnet", "synthetic", "small")]
    assert small["questions"] == 1
    assert small["passed"] == 1
    assert small["accuracy"] == 1.0
    large = cells[("a-direct", "sonnet", "synthetic", "large")]
    assert large["failed"] == 1
    assert large["accuracy"] == 0.0
    trap_cell = cells[("a-direct", "sonnet", "trap", None)]
    assert trap_cell["questions"] == 1

    [episode_ref] = small["episodes"]
    assert episode_ref["question_id"] == "small-hit"
    assert episode_ref["transcript_ref"] == {
        "report_path": str(runs[0].report_path),
        "question_id": "small-hit",
    }


def test_results_report_artifact_is_persisted(tmp_path: Path) -> None:
    output_dir = tmp_path / "results"
    report = generate_results_report(
        runs=passing_matrix(tmp_path), output_dir=output_dir
    )

    persisted = json.loads(
        (output_dir / RESULTS_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    assert persisted == report


# --------------------------------------------------------------------------
# Decision rule: locked bars, computed verdict line
# --------------------------------------------------------------------------


def test_both_models_passing_stands_down(tmp_path: Path) -> None:
    report = generate_results_report(
        runs=passing_matrix(tmp_path), output_dir=tmp_path / "results"
    )

    decision = report["decision"]
    assert decision["verdict"] == DECISION_STAND_DOWN
    assert "stand down" in decision["verdict_line"].lower()
    assert decision["strongest_arm_a_configuration"] == "a-direct"


def test_one_model_at_97_9_percent_compliance_triggers_build(
    tmp_path: Path,
) -> None:
    """979/1000 is below the bar; the 0.1pt shortfall must flip the verdict."""
    runs = [
        make_run(
            tmp_path,
            configuration="a-direct",
            model="sonnet",
            episodes=gating_episodes(compliance_passed=1000, compliance_total=1000),
        ),
        make_run(
            tmp_path,
            configuration="a-direct",
            model="gpt",
            episodes=gating_episodes(compliance_passed=979, compliance_total=1000),
        ),
    ]

    decision = generate_results_report(runs=runs, output_dir=tmp_path / "results")[
        "decision"
    ]

    assert decision["verdict"] == DECISION_BUILD
    assert "build" in decision["verdict_line"].lower()
    assert "gpt" in decision["verdict_line"]
    gpt = decision["models"]["gpt"]
    assert gpt["passed"] is False
    assert gpt["compliance_universal"]["passed"] == 979
    assert gpt["compliance_universal"]["met_bar"] is False


def test_exactly_98_percent_compliance_meets_the_bar(tmp_path: Path) -> None:
    runs = [
        make_run(
            tmp_path,
            configuration="a-direct",
            model=model,
            episodes=gating_episodes(compliance_passed=980, compliance_total=1000),
        )
        for model in ("sonnet", "gpt")
    ]

    decision = generate_results_report(runs=runs, output_dir=tmp_path / "results")[
        "decision"
    ]

    assert decision["verdict"] == DECISION_STAND_DOWN
    assert decision["models"]["sonnet"]["compliance_universal"]["met_bar"] is True


def test_just_below_the_bar_never_displays_as_the_bar(tmp_path: Path) -> None:
    """1959/2000 = 97.95% fails; the report must not render it as 98.0%."""
    runs = [
        make_run(
            tmp_path,
            configuration="a-direct",
            model=model,
            episodes=gating_episodes(compliance_passed=1959, compliance_total=2000),
        )
        for model in ("sonnet", "gpt")
    ]

    decision = generate_results_report(runs=runs, output_dir=tmp_path / "results")[
        "decision"
    ]

    assert decision["verdict"] == DECISION_BUILD
    gate = decision["models"]["sonnet"]["compliance_universal"]
    assert gate["met_bar"] is False
    assert gate["passed"] == 1959
    assert gate["questions"] == 2000
    assert gate["accuracy_percent"] == pytest.approx(97.95)
    assert "98.0% (<98.0%)" not in decision["verdict_line"]
    assert "1959/2000" in decision["verdict_line"]


def test_retrieval_bar_is_95_percent(tmp_path: Path) -> None:
    """949/1000 retrieval fails the 95% bar even with perfect compliance."""
    runs = [
        make_run(
            tmp_path,
            configuration="a-direct",
            model="sonnet",
            episodes=gating_episodes(
                compliance_passed=100,
                compliance_total=100,
                retrieval_passed=949,
                retrieval_total=1000,
            ),
        ),
        make_run(
            tmp_path,
            configuration="a-direct",
            model="gpt",
            episodes=gating_episodes(
                compliance_passed=100,
                compliance_total=100,
                retrieval_passed=950,
                retrieval_total=1000,
            ),
        ),
    ]

    decision = generate_results_report(runs=runs, output_dir=tmp_path / "results")[
        "decision"
    ]

    assert decision["verdict"] == DECISION_BUILD
    assert decision["models"]["sonnet"]["retrieval_local"]["met_bar"] is False
    assert decision["models"]["gpt"]["retrieval_local"]["met_bar"] is True


def test_exact_verdict_with_witnesses_not_posture_decides(tmp_path: Path) -> None:
    """The decision metric is verdict+witness exactness; posture-only failures
    that leave verdict_match and witness_match true cannot flip the rule."""
    episodes = gating_episodes(compliance_passed=1000, compliance_total=1000)
    for entry in episodes:
        entry["grade"]["passed"] = False  # e.g. posture inconsistency
    runs = [
        make_run(tmp_path, configuration="a-direct", model=model, episodes=episodes)
        for model in ("sonnet", "gpt")
    ]

    decision = generate_results_report(runs=runs, output_dir=tmp_path / "results")[
        "decision"
    ]

    assert decision["verdict"] == DECISION_STAND_DOWN


# --------------------------------------------------------------------------
# Strongest Arm-A configuration: one shared selection for both models
# --------------------------------------------------------------------------


def test_crossed_winners_across_configurations_still_build(tmp_path: Path) -> None:
    """Sonnet passing only config X and GPT passing only config Y must BUILD:
    no single architecture configuration clears both models' bars."""
    strong = gating_episodes(compliance_passed=1000, compliance_total=1000)
    weak = gating_episodes(compliance_passed=900, compliance_total=1000)
    runs = [
        make_run(tmp_path, configuration="a-direct", model="sonnet", episodes=strong),
        make_run(tmp_path, configuration="a-agentic", model="sonnet", episodes=weak),
        make_run(tmp_path, configuration="a-direct", model="gpt", episodes=weak),
        make_run(tmp_path, configuration="a-agentic", model="gpt", episodes=strong),
    ]

    decision = generate_results_report(runs=runs, output_dir=tmp_path / "results")[
        "decision"
    ]

    assert decision["verdict"] == DECISION_BUILD


def test_qualifying_configuration_outranks_a_lopsided_one(tmp_path: Path) -> None:
    """A config clearing all four gates must be selected over one with
    perfect compliance but failing retrieval, whatever its headline score."""
    qualifying = gating_episodes(
        compliance_passed=98,
        compliance_total=100,
        retrieval_passed=95,
        retrieval_total=100,
    )
    lopsided = gating_episodes(
        compliance_passed=100,
        compliance_total=100,
        retrieval_passed=94,
        retrieval_total=100,
    )
    runs = [
        make_run(
            tmp_path, configuration="a-agentic", model="sonnet", episodes=qualifying
        ),
        make_run(tmp_path, configuration="a-agentic", model="gpt", episodes=qualifying),
        make_run(tmp_path, configuration="a-direct", model="sonnet", episodes=lopsided),
        make_run(tmp_path, configuration="a-direct", model="gpt", episodes=lopsided),
    ]

    decision = generate_results_report(runs=runs, output_dir=tmp_path / "results")[
        "decision"
    ]

    assert decision["strongest_arm_a_configuration"] == "a-agentic"
    assert decision["verdict"] == DECISION_STAND_DOWN


# --------------------------------------------------------------------------
# Provably non-gating: trap and DeepSeek cannot move the verdict
# --------------------------------------------------------------------------


def test_flipping_every_trap_and_deepseek_result_never_moves_the_verdict(
    tmp_path: Path,
) -> None:
    baseline = generate_results_report(
        runs=passing_matrix(tmp_path), output_dir=tmp_path / "baseline"
    )

    flipped_runs = [
        make_run(
            tmp_path,
            configuration="a-direct",
            model=model,
            episodes=gating_episodes(compliance_passed=1000, compliance_total=1000)
            + trap_episodes(rubric_passed=False),
        )
        for model in ("sonnet", "gpt")
    ] + [
        make_run(
            tmp_path,
            configuration="a-direct",
            model="deepseek",
            episodes=gating_episodes(compliance_passed=1000, compliance_total=1000)
            + trap_episodes(rubric_passed=True),
        )
    ]
    flipped = generate_results_report(
        runs=flipped_runs, output_dir=tmp_path / "flipped"
    )

    assert flipped["decision"]["verdict"] == baseline["decision"]["verdict"]
    assert flipped["decision"]["verdict_line"] == baseline["decision"]["verdict_line"]


def test_decision_inputs_enumerate_only_verdict_tier_arm_a_gating_runs(
    tmp_path: Path,
) -> None:
    runs = passing_matrix(tmp_path) + [
        make_run(
            tmp_path,
            configuration="b-incumbent",
            arm_family=ARM_FAMILY_B,
            model="sonnet",
            episodes=gating_episodes(compliance_passed=10, compliance_total=100),
        )
    ]

    decision = generate_results_report(runs=runs, output_dir=tmp_path / "results")[
        "decision"
    ]

    input_keys = {
        (entry["configuration"], entry["model"]) for entry in decision["inputs"]
    }
    assert input_keys == {("a-direct", "sonnet"), ("a-direct", "gpt")}
    excluded = decision["excluded"]
    assert "deepseek" in excluded["models"]
    assert "trap" in excluded["slices"]


def test_deepseek_and_trap_results_are_still_reported(tmp_path: Path) -> None:
    report = generate_results_report(
        runs=passing_matrix(tmp_path), output_dir=tmp_path / "results"
    )

    models = {cell["model"] for cell in report["breakdown"]}
    slices = {cell["slice"] for cell in report["breakdown"]}
    assert "deepseek" in models
    assert "trap" in slices


# --------------------------------------------------------------------------
# Informational-only sections
# --------------------------------------------------------------------------


def test_latency_and_prose_quality_are_informational_only(tmp_path: Path) -> None:
    report = generate_results_report(
        runs=passing_matrix(tmp_path), output_dir=tmp_path / "results"
    )

    informational = report["informational"]
    assert informational["gating"] is False
    latency = {
        (entry["configuration"], entry["model"]): entry
        for entry in informational["latency"]
    }
    sonnet = latency[("a-direct", "sonnet")]
    assert sonnet["episodes"] == 1021
    assert sonnet["mean_wall_time_seconds"] == pytest.approx(1.0)
    assert sonnet["max_wall_time_seconds"] == pytest.approx(1.0)

    prose = {
        (entry["configuration"], entry["model"]): entry
        for entry in informational["prose_quality"]
    }
    assert prose[("a-direct", "sonnet")]["trap_rubric_passed"] == 1
    assert prose[("a-direct", "deepseek")]["trap_rubric_passed"] == 0

    usage = {
        (entry["configuration"], entry["model"]): entry
        for entry in informational["usage_and_cost"]
    }
    assert usage[("a-direct", "sonnet")] == {
        "configuration": "a-direct",
        "arm": "a-direct:sonnet",
        "model": "sonnet",
        "episodes": 1021,
        "episodes_with_token_accounting": 1021,
        "input_tokens": 10210,
        "output_tokens": 5105,
        "total_tokens": 15315,
        "episodes_with_cost_accounting": 1021,
        "cost_usd": pytest.approx(1.021),
    }


# --------------------------------------------------------------------------
# Fail-fast validation
# --------------------------------------------------------------------------


def test_missing_arm_a_run_for_a_verdict_model_fails_fast(tmp_path: Path) -> None:
    runs = [
        make_run(
            tmp_path,
            configuration="a-direct",
            model="sonnet",
            episodes=gating_episodes(compliance_passed=10, compliance_total=10),
        )
    ]

    with pytest.raises(ResultsReportError, match=r"gpt.+Arm-A"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_gating_episode_without_category_fails_fast(tmp_path: Path) -> None:
    episodes = gating_episodes(compliance_passed=10, compliance_total=10)
    episodes[0]["category"] = None
    runs = [
        make_run(tmp_path, configuration="a-direct", model=model, episodes=episodes)
        for model in ("sonnet", "gpt")
    ]

    with pytest.raises(ResultsReportError, match=r"comp-0000.+category"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_a_trap_episode_tampered_to_gating_true_is_rejected(tmp_path: Path) -> None:
    """Gating eligibility derives from the slice; a trap flagged gating
    (with a category) must fail fast, never move the verdict."""
    tampered_trap = episode(
        "trap-smuggled",
        slice_name="trap",
        category="compliance_universal",
        gating=True,
        passed=True,
    )
    episodes = gating_episodes(compliance_passed=10, compliance_total=10) + [
        tampered_trap
    ]
    runs = [
        make_run(tmp_path, configuration="a-direct", model=model, episodes=episodes)
        for model in ("sonnet", "gpt")
    ]

    with pytest.raises(ResultsReportError, match=r"trap-smuggled"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_a_gating_episode_tampered_to_gating_false_is_rejected(
    tmp_path: Path,
) -> None:
    """A failed compliance episode cannot be silently dropped from the rule
    by flipping its gating flag."""
    episodes = gating_episodes(compliance_passed=10, compliance_total=11)
    episodes[10]["gating"] = False
    runs = [
        make_run(tmp_path, configuration="a-direct", model=model, episodes=episodes)
        for model in ("sonnet", "gpt")
    ]

    with pytest.raises(ResultsReportError, match=r"comp-0010.+gating=False.+tampered"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_decision_run_missing_a_gating_category_fails_fast(tmp_path: Path) -> None:
    compliance_only = [
        episode(f"comp-{index}", category="compliance_universal") for index in range(5)
    ]
    runs = [
        make_run(
            tmp_path, configuration="a-direct", model=model, episodes=compliance_only
        )
        for model in ("sonnet", "gpt")
    ]

    with pytest.raises(ResultsReportError, match=r"retrieval_local"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_duplicate_run_for_one_configuration_and_model_fails_fast(
    tmp_path: Path,
) -> None:
    episodes = gating_episodes(compliance_passed=10, compliance_total=10)
    runs = [
        make_run(tmp_path, configuration="a-direct", model="sonnet", episodes=episodes),
        make_run(tmp_path, configuration="a-direct", model="sonnet", episodes=episodes),
        make_run(tmp_path, configuration="a-direct", model="gpt", episodes=episodes),
    ]

    with pytest.raises(ResultsReportError, match=r"duplicate.+a-direct.+sonnet"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_a_run_dropping_a_failed_question_cannot_stand_down(
    tmp_path: Path,
) -> None:
    """The verdict is only comparable over one identical gating dataset: a
    run that sheds its failed questions must fail fast, not pass."""
    full = gating_episodes(compliance_passed=1000, compliance_total=1000)
    shed = [
        entry
        for entry in gating_episodes(compliance_passed=980, compliance_total=1000)
        if entry["grade"]["passed"]  # type: ignore[index]
    ]
    runs = [
        make_run(tmp_path, configuration="a-direct", model="sonnet", episodes=full),
        make_run(tmp_path, configuration="a-direct", model="gpt", episodes=shed),
    ]

    with pytest.raises(ResultsReportError, match=r"different gating question sets"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_a_question_graded_twice_in_one_run_fails_fast(tmp_path: Path) -> None:
    """One logical question cannot be counted toward two gates."""
    episodes = gating_episodes(compliance_passed=10, compliance_total=10)
    episodes.append(episode("comp-0000", category="retrieval_local", passed=True))
    runs = [
        make_run(tmp_path, configuration="a-direct", model=model, episodes=episodes)
        for model in ("sonnet", "gpt")
    ]

    with pytest.raises(ResultsReportError, match=r"'comp-0000' more than once"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_a_non_object_episode_entry_fails_fast(tmp_path: Path) -> None:
    episodes = gating_episodes(compliance_passed=10, compliance_total=10)
    episodes.append("not-an-episode")  # type: ignore[arg-type]
    runs = [
        make_run(tmp_path, configuration="a-direct", model=model, episodes=episodes)
        for model in ("sonnet", "gpt")
    ]

    with pytest.raises(ResultsReportError, match=r"non-object episode"):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


def test_a_malformed_grade_cannot_score_as_an_ordinary_failure(
    tmp_path: Path,
) -> None:
    """A corrupt report must become a clean input error, never a verdict."""
    episodes = gating_episodes(compliance_passed=10, compliance_total=10)
    episodes[0]["grade"]["verdict_match"] = "yes"  # type: ignore[index]
    runs = [
        make_run(tmp_path, configuration="a-direct", model=model, episodes=episodes)
        for model in ("sonnet", "gpt")
    ]

    with pytest.raises(
        ResultsReportError, match=r"comp-0000.+'verdict_match' must be a boolean"
    ):
        generate_results_report(runs=runs, output_dir=tmp_path / "results")


# --------------------------------------------------------------------------
# Run index loading and the CLI vertical
# --------------------------------------------------------------------------


def write_run_index(tmp_path: Path, runs: list[BenchmarkRun]) -> Path:
    index_path = tmp_path / "runs.json"
    index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runs": [
                    {
                        "configuration": run.configuration,
                        "arm": run.arm_id,
                        "arm_family": run.arm_family,
                        "model": run.model,
                        "report": str(run.report_path),
                    }
                    for run in runs
                ],
            }
        ),
        encoding="utf-8",
    )
    return index_path


def test_run_index_loads_declared_runs_and_their_reports(tmp_path: Path) -> None:
    runs = passing_matrix(tmp_path)
    index_path = write_run_index(tmp_path, runs)

    loaded = load_run_index(index_path)

    assert [(run.configuration, run.arm_id, run.model) for run in loaded] == [
        ("a-direct", "a-direct:sonnet", "sonnet"),
        ("a-direct", "a-direct:gpt", "gpt"),
        ("a-direct", "a-direct:deepseek", "deepseek"),
    ]
    assert loaded[0].report["arm_id"] == "a-direct:sonnet"


def test_run_index_rejects_an_arm_mismatch_with_its_report(tmp_path: Path) -> None:
    runs = passing_matrix(tmp_path)
    index_path = tmp_path / "runs.json"
    index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runs": [
                    {
                        "configuration": "a-direct",
                        "arm": "mislabeled-arm",
                        "arm_family": ARM_FAMILY_A,
                        "model": "sonnet",
                        "report": str(runs[0].report_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ResultsReportError,
        match=r"'mislabeled-arm'.+records arm_id 'a-direct:sonnet'",
    ):
        load_run_index(index_path)


def test_run_index_rejects_an_unknown_arm_family(tmp_path: Path) -> None:
    runs = passing_matrix(tmp_path)
    index_path = tmp_path / "runs.json"
    index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runs": [
                    {
                        "configuration": "a-direct",
                        "arm": "a-direct",
                        "arm_family": "arm_z",
                        "model": "sonnet",
                        "report": str(runs[0].report_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResultsReportError, match=r"invalid arm_family 'arm_z'"):
        load_run_index(index_path)


def test_cli_generates_the_results_report_and_prints_the_verdict_line(
    tmp_path: Path,
) -> None:
    runs = passing_matrix(tmp_path)
    index_path = write_run_index(tmp_path, runs)
    output_dir = tmp_path / "results"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pydexpi_datalog",
            "results-report",
            "--runs",
            str(index_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    persisted = json.loads(
        (output_dir / RESULTS_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    assert persisted["decision"]["verdict"] == DECISION_STAND_DOWN
    assert "STAND DOWN" in result.stdout


def test_cli_reports_a_bad_run_index_as_a_clean_error(tmp_path: Path) -> None:
    index_path = tmp_path / "runs.json"
    index_path.write_text(json.dumps({"schema_version": 1, "runs": []}))
    output_dir = tmp_path / "results"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pydexpi_datalog",
            "results-report",
            "--runs",
            str(index_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 2
    assert "non-empty 'runs' list" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output_dir.exists()


def test_cli_reports_a_tampered_run_report_as_a_clean_error(
    tmp_path: Path,
) -> None:
    runs = passing_matrix(tmp_path)
    tampered = json.loads(runs[0].report_path.read_text(encoding="utf-8"))
    tampered["episodes"][0]["grade"] = None
    runs[0].report_path.write_text(json.dumps(tampered), encoding="utf-8")
    index_path = write_run_index(tmp_path, runs)
    output_dir = tmp_path / "results"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pydexpi_datalog",
            "results-report",
            "--runs",
            str(index_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 2
    assert "has no grade object" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output_dir.exists()
