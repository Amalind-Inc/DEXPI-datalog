"""Behavior tests for the resumable live benchmark matrix entry point."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from pydexpi_datalog.benchmark.agentic_arm import BUNDLE_FILES, EpisodeBudgets
from pydexpi_datalog.benchmark.answer_quality import (
    AnswerQualityJudgment,
    ScriptedAnswerQualityJudge,
)
from pydexpi_datalog.benchmark.contract import (
    POSTURE_SOURCE_GROUNDED,
    StructuredAnswer,
)
from pydexpi_datalog.benchmark.live_matrix import (
    LIVE_MATRIX_MODELS,
    LiveArmSpec,
    build_combined_manifest,
    create_live_answer_quality_judge,
    create_live_trap_judge,
    materialize_live_bundles,
    run_live_matrix,
)
from pydexpi_datalog.benchmark.runner import ScriptedArm


def test_live_judges_use_deepseek_v4_flash() -> None:
    judge = create_live_answer_quality_judge(environ={"OPENROUTER_API_KEY": "test-key"})

    assert judge.provider.provider == "openrouter"
    assert judge.provider.model == "deepseek/deepseek-v4-flash"

    trap_judge = create_live_trap_judge(environ={"OPENROUTER_API_KEY": "test-key"})
    assert trap_judge.provider.provider == "openrouter"
    assert trap_judge.provider.model == "deepseek/deepseek-v4-flash"


def _write_manifest(path: Path, *, question_id: str, category: str) -> None:
    bundle = path.parent / f"{question_id}-bundle"
    bundle.mkdir()
    (bundle / "drawing.xml").write_text("<PlantModel/>", encoding="utf-8")
    (bundle / "graph_facts.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_id": question_id,
                "fixture_id": question_id,
                "source_path": str((bundle / "drawing.xml").resolve()),
                "graph": {"node_count": 1, "edge_count": 0},
                "provenance": {"extractor": "test", "extractor_version": "1"},
                "facts": {
                    "nodes": [
                        {
                            "node_id": "witness-1",
                            "label": "Pump",
                            "attributes": {},
                        }
                    ],
                    "edges": [],
                },
            }
        ),
        encoding="utf-8",
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "questions": [
                    {
                        "id": question_id,
                        "question": f"Question {question_id}?",
                        "slice": "hand_authored",
                        "category": category,
                        "drawing": bundle.name,
                        "ground_truth": {
                            "verdict": "violation_found",
                            "witness_ids": ["witness-1"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_combined_manifest_rebases_drawings_and_records_shared_budgets(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first" / "manifest.json"
    second = tmp_path / "second" / "manifest.json"
    first.parent.mkdir()
    second.parent.mkdir()
    _write_manifest(first, question_id="compliance", category="compliance_universal")
    _write_manifest(second, question_id="retrieval", category="retrieval_local")
    raw_second = json.loads(second.read_text(encoding="utf-8"))
    raw_second["fidelity"] = {
        "mode": "xml_graph_wrapper",
        "limit": "Synthetic XML mirrors graph facts, not a full DEXPI export.",
    }
    second.write_text(json.dumps(raw_second), encoding="utf-8")
    budgets = EpisodeBudgets(max_turns=7, max_commands=9)

    combined = build_combined_manifest(
        manifest_paths=(first, second),
        output_path=tmp_path / "combined" / "manifest.json",
        budgets=budgets,
    )

    payload = json.loads(combined.read_text(encoding="utf-8"))
    assert [question["id"] for question in payload["questions"]] == [
        "compliance",
        "retrieval",
    ]
    assert all(
        Path(question["drawing"]).is_absolute() for question in payload["questions"]
    )
    assert payload["episode_budgets"] == asdict(budgets)
    assert payload["fidelity"]["mode"] == "xml_graph_wrapper"

    materialize_live_bundles(
        manifest_path=combined,
        output_dir=tmp_path / "combined" / "bundles",
    )
    materialized = json.loads(combined.read_text(encoding="utf-8"))
    for question in materialized["questions"]:
        bundle = Path(question["drawing"])
        assert all((bundle / name).is_file() for name in BUNDLE_FILES)


def test_live_matrix_runs_every_configuration_and_model_then_computes_verdict(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        question_id="compliance",
        category="compliance_universal",
    )
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    retrieval = dict(raw["questions"][0])
    retrieval["id"] = "retrieval"
    retrieval["category"] = "retrieval_local"
    raw["questions"].append(retrieval)
    manifest.write_text(json.dumps(raw), encoding="utf-8")

    created: list[tuple[str, str, EpisodeBudgets]] = []

    def spec(configuration: str, family: str) -> LiveArmSpec:
        def factory(model: str, budgets: EpisodeBudgets, artifact_root: Path):
            created.append((configuration, model, budgets))
            answers = {
                question_id: StructuredAnswer(
                    verdict="violation_found",
                    witness_ids=("witness-1",),
                    posture=POSTURE_SOURCE_GROUNDED,
                    usage={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cost_usd": 0.001,
                        "budgets": asdict(budgets),
                    },
                )
                for question_id in ("compliance", "retrieval")
            }
            return ScriptedArm(
                arm_id=f"{configuration}:{model}",
                answers=answers,
            )

        return LiveArmSpec(configuration, family, factory)

    specs = (
        spec("a-direct", "arm_a"),
        spec("a-agentic", "arm_a"),
        spec("b-incumbent", "arm_b"),
        spec("c-souffle", "arm_c"),
    )
    quality_judgment = AnswerQualityJudgment(
        answered_question=True,
        faithful_to_evidence=True,
        engineering_language=True,
        scope_honest=True,
        provenance_clear=True,
        grounding_expectation="required",
        grounding_fit=True,
        useful_next_step=False,
        overall_score=4,
        rationale="Clear source-grounded answer.",
    )
    output_dir = tmp_path / "live"

    report = run_live_matrix(
        manifest_paths=(manifest,),
        output_dir=output_dir,
        arm_specs=specs,
        models=LIVE_MATRIX_MODELS,
        budgets=EpisodeBudgets(max_turns=5, max_commands=6),
        answer_quality_judge=ScriptedAnswerQualityJudge(
            {
                question_id: quality_judgment
                for question_id in ("compliance", "retrieval")
            }
        ),
    )

    assert len(created) == 12
    assert {(configuration, model) for configuration, model, _ in created} == {
        (configuration, model)
        for configuration in ("a-direct", "a-agentic", "b-incumbent", "c-souffle")
        for model in LIVE_MATRIX_MODELS
    }
    quality_entries = report["informational"]["answer_quality"]
    assert len(quality_entries) == 12
    assert all(entry["mean_overall_score"] == 4.0 for entry in quality_entries)
    assert all(entry["criteria_passes"]["grounding_fit"] == 2 for entry in quality_entries)
    run_index = json.loads((output_dir / "runs.json").read_text(encoding="utf-8"))
    assert len(run_index["runs"]) == 12
    assert report["decision"]["verdict"] == "stand_down"
    assert (output_dir / "results_report.json").is_file()
    assert report["execution"]["episode_budgets"] == {
        "max_turns": 5,
        "max_commands": 6,
        "max_output_tokens": 8192,
        "agent_timeout_sec": 1800.0,
        "verifier_timeout_sec": 300.0,
    }
    assert report["execution"]["agentic_budget_evidence"] == {
        "a-agentic": report["execution"]["episode_budgets"],
        "c-souffle": report["execution"]["episode_budgets"],
    }
