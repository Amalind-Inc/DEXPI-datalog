"""Behavior tests for run_benchmark at the package seam.

Scripted arms only: zero live LLM calls. The runner is the spine every
benchmark arm plugs into, so these tests pin the arm adapter contract,
the per-episode report payload, and the persisted artifact.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pydexpi_datalog.benchmark import (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
    ScriptedArm,
    StructuredAnswer,
    run_benchmark,
    run_scripted_benchmark,
)
from pydexpi_datalog.benchmark.contract import TrapJudgment
from pydexpi_datalog.benchmark.trap_rubric import ScriptedTrapJudge

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)


def write_manifest(tmp_path: Path) -> tuple[Path, str]:
    """A two-question manifest over the checked-in E06 base fact layer."""
    node_id = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))["facts"]["nodes"][
        0
    ]["node_id"]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "questions": [
                    {
                        "id": "e06-trap",
                        "question": "When was this drawing approved?",
                        "slice": "trap",
                        "drawing": str(E06_GRAPH_FACTS),
                        "ground_truth": {"verdict": "unanswerable"},
                        "trap_rubric": {
                            "expected_posture": "source_data_unavailable",
                            "refusal_basis": "Approval history is absent from the source.",
                            "redirect_target": "Offer topology or equipment checks.",
                            "human_spot_check": True,
                        },
                    },
                    {
                        "id": "e06-violation",
                        "question": "Is any pump missing a check valve?",
                        "slice": "hand_authored",
                        "category": "compliance_universal",
                        "size_bucket": "small",
                        "drawing": str(E06_GRAPH_FACTS),
                        "ground_truth": {
                            "verdict": "violation_found",
                            "witness_ids": [node_id],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, node_id


def scripted_trap_judge() -> ScriptedTrapJudge:
    return ScriptedTrapJudge(
        {
            question_id: TrapJudgment(
                grounded_refusal=True,
                graceful_redirect=True,
                rationale="Names the missing data and offers source checks.",
            )
            for question_id in ("e06-trap", "e06-bundle-trap")
        }
    )


class RunBenchmarkTests(unittest.TestCase):
    def test_run_benchmark_grades_each_episode_and_writes_report_artifact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path, node_id = write_manifest(tmp_path)
            output_dir = tmp_path / "report"
            arm = ScriptedArm(
                arm_id="scripted-demo",
                answers={
                    "e06-trap": StructuredAnswer(
                        verdict=VERDICT_UNANSWERABLE,
                        posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
                        answer_text=(
                            "Approval history is absent. I can check represented "
                            "topology or equipment attributes instead."
                        ),
                        transcript=(
                            {"role": "assistant", "content": "No approval data."},
                        ),
                        usage={
                            "input_tokens": 120,
                            "output_tokens": 8,
                            "cost_usd": 0.001,
                        },
                    ),
                    "e06-violation": StructuredAnswer(
                        verdict=VERDICT_VIOLATION_FOUND,
                        witness_ids=("bogus-node",),
                        posture=POSTURE_SOURCE_GROUNDED,
                    ),
                },
            )

            trap_judge = scripted_trap_judge()

            report = run_benchmark(
                manifest_path=manifest_path,
                arm=arm,
                output_dir=output_dir,
                trap_judge=trap_judge,
            )

            artifact_path = output_dir / "benchmark_report.json"
            self.assertTrue(artifact_path.exists())
            persisted = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted, report)

            self.assertEqual(report["arm_id"], "scripted-demo")
            self.assertEqual(report["trap_judge_id"], "scripted-trap-judge")
            self.assertEqual(
                report["totals"], {"questions": 1, "passed": 0, "failed": 1}
            )
            self.assertEqual(
                report["informational_totals"],
                {"questions": 1, "passed": 1, "failed": 0},
            )

            episodes = {e["question_id"]: e for e in report["episodes"]}
            self.assertEqual(set(episodes), {"e06-trap", "e06-violation"})

            trap = episodes["e06-trap"]
            self.assertEqual(trap["slice"], "trap")
            self.assertIsNone(trap["category"])
            self.assertIsNone(trap["size_bucket"])
            self.assertTrue(trap["grade"]["passed"])
            self.assertIn("Approval history", trap["answer"]["answer_text"])
            self.assertFalse(trap["gating"])
            self.assertTrue(trap["human_spot_check_required"])
            self.assertTrue(trap["grade"]["trap_rubric_passed"])
            violation = episodes["e06-violation"]
            self.assertEqual(violation["category"], "compliance_universal")
            self.assertEqual(violation["size_bucket"], "small")
            self.assertEqual(
                report["human_spot_check"]["question_ids"],
                ["e06-trap"],
            )
            self.assertEqual(
                trap["transcript"],
                [{"role": "assistant", "content": "No approval data."}],
            )
            self.assertEqual(
                trap["usage"],
                {"input_tokens": 120, "output_tokens": 8, "cost_usd": 0.001},
            )
            self.assertEqual(trap["tokens"], {"input": 120, "output": 8, "total": 128})
            self.assertEqual(trap["cost_usd"], 0.001)
            self.assertIsInstance(trap["wall_time_seconds"], float)
            self.assertGreaterEqual(trap["wall_time_seconds"], 0.0)

            violation = episodes["e06-violation"]
            self.assertFalse(violation["grade"]["passed"])
            self.assertTrue(violation["grade"]["verdict_match"])
            self.assertEqual(
                violation["tokens"], {"input": None, "output": None, "total": None}
            )
            self.assertIsNone(violation["cost_usd"])
            self.assertFalse(violation["grade"]["witness_match"])
            self.assertEqual(violation["grade"]["unknown_witness_ids"], ["bogus-node"])
            self.assertEqual(violation["grade"]["missing_witness_ids"], [node_id])
            self.assertEqual(violation["answer"]["verdict"], VERDICT_VIOLATION_FOUND)
            self.assertEqual(
                violation["expected"],
                {"verdict": VERDICT_VIOLATION_FOUND, "witness_ids": [node_id]},
            )

    def test_run_benchmark_fails_fast_when_scripted_arm_misses_a_question(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path, _ = write_manifest(tmp_path)
            arm = ScriptedArm(arm_id="incomplete", answers={})

            with self.assertRaisesRegex(KeyError, "e06-trap"):
                run_benchmark(
                    manifest_path=manifest_path,
                    arm=arm,
                    output_dir=tmp_path / "report",
                    trap_judge=scripted_trap_judge(),
                )
            self.assertFalse((tmp_path / "report" / "benchmark_report.json").exists())

    def test_arm_adapter_receives_question_and_drawing_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path, node_id = write_manifest(tmp_path)
            received: list[tuple[str, Path]] = []

            class RecordingArm:
                arm_id = "recording"

                def answer(self, *, question, drawing_ref: Path) -> StructuredAnswer:
                    received.append((question.question_id, drawing_ref))
                    return StructuredAnswer(
                        verdict=question.ground_truth.verdict,
                        witness_ids=question.ground_truth.witness_ids,
                        posture=(
                            POSTURE_SOURCE_GROUNDED
                            if question.ground_truth.verdict == VERDICT_VIOLATION_FOUND
                            else POSTURE_SOURCE_DATA_UNAVAILABLE
                        ),
                    )

            report = run_benchmark(
                manifest_path=manifest_path,
                arm=RecordingArm(),
                output_dir=tmp_path / "report",
                trap_judge=scripted_trap_judge(),
            )

            self.assertEqual(
                received,
                [
                    ("e06-trap", E06_GRAPH_FACTS),
                    ("e06-violation", E06_GRAPH_FACTS),
                ],
            )
            self.assertEqual(
                report["totals"], {"questions": 1, "passed": 1, "failed": 0}
            )

    def test_arm_adapter_receives_drawing_bundle_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            bundle_dir = tmp_path / "e06-bundle"
            bundle_dir.mkdir()
            (bundle_dir / "graph_facts.json").write_text(
                E06_GRAPH_FACTS.read_text(encoding="utf-8"), encoding="utf-8"
            )
            manifest_path = tmp_path / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "questions": [
                            {
                                "id": "e06-bundle-trap",
                                "question": "When was this drawing approved?",
                                "slice": "trap",
                                "drawing": str(bundle_dir),
                                "ground_truth": {"verdict": "unanswerable"},
                                "trap_rubric": {
                                    "expected_posture": "source_data_unavailable",
                                    "refusal_basis": "Approval history is absent.",
                                    "redirect_target": "Offer drawing checks.",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            received: list[Path] = []

            class BundleArm:
                arm_id = "bundle-recording"

                def answer(self, *, question, drawing_ref: Path) -> StructuredAnswer:
                    received.append(drawing_ref)
                    return StructuredAnswer(
                        verdict=VERDICT_UNANSWERABLE,
                        posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
                        answer_text=(
                            "Approval history is absent. I can check topology instead."
                        ),
                    )

            report = run_benchmark(
                manifest_path=manifest_path,
                arm=BundleArm(),
                output_dir=tmp_path / "report",
                trap_judge=scripted_trap_judge(),
            )

            self.assertEqual(received, [bundle_dir.resolve()])
            self.assertTrue(received[0].is_dir())
            self.assertEqual(
                report["totals"], {"questions": 0, "passed": 0, "failed": 0}
            )
            self.assertEqual(
                report["informational_totals"],
                {"questions": 1, "passed": 1, "failed": 0},
            )

    def test_scripted_runner_rejects_missing_trap_judgment_before_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path, node_id = write_manifest(tmp_path)
            answers_path = tmp_path / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "e06-trap": {
                            "verdict": "unanswerable",
                            "posture": "source_data_unavailable",
                            "answer_text": (
                                "Approval history is absent. I can check topology."
                            ),
                        },
                        "e06-violation": {
                            "verdict": "violation_found",
                            "witness_ids": [node_id],
                            "posture": "source_grounded",
                        },
                    }
                ),
                encoding="utf-8",
            )
            judgments_path = tmp_path / "judgments.json"
            judgments_path.write_text("{}", encoding="utf-8")
            output_dir = tmp_path / "report"

            with self.assertRaisesRegex(ValueError, "missing question IDs: e06-trap"):
                run_scripted_benchmark(
                    manifest_path=manifest_path,
                    scripted_answers_path=answers_path,
                    arm_id="scripted-preflight",
                    output_dir=output_dir,
                    scripted_trap_judgments_path=judgments_path,
                )

            self.assertFalse(output_dir.exists())


    def test_scripted_runner_validates_supplied_judgments_without_traps(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path, node_id = write_manifest(tmp_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["questions"] = [manifest["questions"][1]]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            answers_path = tmp_path / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "e06-violation": {
                            "verdict": "violation_found",
                            "witness_ids": [node_id],
                            "posture": "source_grounded",
                        }
                    }
                ),
                encoding="utf-8",
            )
            judgments_path = tmp_path / "judgments.json"
            judgments_path.write_text("not-json", encoding="utf-8")
            output_dir = tmp_path / "report"

            with self.assertRaises(json.JSONDecodeError):
                run_scripted_benchmark(
                    manifest_path=manifest_path,
                    scripted_answers_path=answers_path,
                    arm_id="scripted-preflight",
                    output_dir=output_dir,
                    scripted_trap_judgments_path=judgments_path,
                )

            self.assertFalse(output_dir.exists())



class RunBenchmarkCliTests(unittest.TestCase):
    def test_one_command_runs_manifest_through_scripted_arm_and_writes_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path, node_id = write_manifest(tmp_path)
            output_dir = tmp_path / "report"
            answers_path = tmp_path / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "e06-trap": {
                            "verdict": "unanswerable",
                            "posture": "source_data_unavailable",
                            "answer_text": (
                                "Approval history is absent. I can check topology."
                            ),
                        },
                        "e06-violation": {
                            "verdict": "violation_found",
                            "witness_ids": [node_id],
                            "posture": "source_grounded",
                        },
                    }
                ),
                encoding="utf-8",
            )
            judgments_path = tmp_path / "trap-judgments.json"
            judgments_path.write_text(
                json.dumps(
                    {
                        "e06-trap": {
                            "grounded_refusal": True,
                            "graceful_redirect": True,
                            "rationale": "Names the missing data and redirects.",
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "run-benchmark",
                    str(manifest_path),
                    "--scripted-answers",
                    str(answers_path),
                    "--scripted-trap-judgments",
                    str(judgments_path),
                    "--arm-id",
                    "scripted-cli",
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=REPO_ROOT,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(
                (output_dir / "benchmark_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["arm_id"], "scripted-cli")
            self.assertEqual(
                report["totals"], {"questions": 1, "passed": 1, "failed": 0}
            )
            self.assertEqual(
                report["informational_totals"],
                {"questions": 1, "passed": 1, "failed": 0},
            )
            self.assertIn("Benchmark report", result.stdout)

    def test_cli_reports_missing_trap_judgments_without_running_episodes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path, node_id = write_manifest(tmp_path)
            answers_path = tmp_path / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "e06-trap": {
                            "verdict": "unanswerable",
                            "posture": "source_data_unavailable",
                            "answer_text": (
                                "Approval history is absent. I can check topology."
                            ),
                        },
                        "e06-violation": {
                            "verdict": "violation_found",
                            "witness_ids": [node_id],
                            "posture": "source_grounded",
                        },
                    }
                ),
                encoding="utf-8",
            )
            output_dir = tmp_path / "report"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "run-benchmark",
                    str(manifest_path),
                    "--scripted-answers",
                    str(answers_path),
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=REPO_ROOT,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("require --scripted-trap-judgments", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output_dir.exists())

            missing_path = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "run-benchmark",
                    str(manifest_path),
                    "--scripted-answers",
                    str(answers_path),
                    "--scripted-trap-judgments",
                    str(tmp_path / "missing-judgments.json"),
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=REPO_ROOT,
            )
            self.assertEqual(missing_path.returncode, 2)
            self.assertIn("missing-judgments.json", missing_path.stderr)
            self.assertNotIn("Traceback", missing_path.stderr)
            self.assertFalse(output_dir.exists())


    def test_cli_rejects_malformed_scripted_answer_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path, _ = write_manifest(tmp_path)
            answers_path = tmp_path / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "e06-trap": {
                            "verdict": "unanswerable",
                            "witness_ids": "not-a-list",
                            "posture": "source_data_unavailable",
                        }
                    }
                ),
                encoding="utf-8",
            )
            output_dir = tmp_path / "report"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "run-benchmark",
                    str(manifest_path),
                    "--scripted-answers",
                    str(answers_path),
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=REPO_ROOT,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("witness_ids must be a list of strings", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output_dir.exists())



if __name__ == "__main__":
    unittest.main()
