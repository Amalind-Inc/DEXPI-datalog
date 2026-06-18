from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
E06_DERIVED_GRAPH_SEMANTICS = (
    REPO_ROOT
    / "fixtures"
    / "derived_graph_semantics"
    / "e06-pump-hex"
    / "derived_graph_semantics.dl"
)


class QueryDerivedGraphCliTests(unittest.TestCase):
    def test_query_command_compares_reachable_and_downstream_reference_targets(
        self,
    ) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "query-derived-graph",
                "compare_known_object_reachability",
                str(E06_DERIVED_GRAPH_SEMANTICS),
                "--source-id",
                "3b212201-f8b6-47ed-9019-d7961f3276c8",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("P&ID QA Query", result.stdout)
        self.assertIn("Query ID: compare_known_object_reachability", result.stdout)
        self.assertIn(
            "Source ID: 3b212201-f8b6-47ed-9019-d7961f3276c8", result.stdout
        )
        self.assertIn("Reachable targets", result.stdout)
        self.assertIn("Downstream reference targets", result.stdout)
        self.assertIn(
            "Reachable targets                                 | Downstream reference targets",
            result.stdout,
        )
        self.assertIn(
            "2accb8cf-7c3d-4563-8c22-5d817f464bd5  Nozzle",
            result.stdout,
        )
        self.assertIn(
            "57c776dc-fc90-4276-bb53-f0bbdd01bb83  Nozzle",
            result.stdout,
        )

    def test_query_command_persists_inspectable_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "compare_known_object_reachability",
                    str(E06_DERIVED_GRAPH_SEMANTICS),
                    "--source-id",
                    "3b212201-f8b6-47ed-9019-d7961f3276c8",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            combined_program_path = output_dir / "combined_query.dl"
            result_path = output_dir / "query_result.json"
            raw_output_dir = output_dir / "internal" / "souffle-output"
            self.assertTrue(combined_program_path.exists(), combined_program_path)
            self.assertTrue(result_path.exists(), result_path)
            self.assertTrue(raw_output_dir.exists(), raw_output_dir)
            self.assertTrue((raw_output_dir / "query_reachable.csv").exists())
            self.assertTrue((raw_output_dir / "query_downstream_reference.csv").exists())

            combined_program = combined_program_path.read_text(encoding="utf-8")
            self.assertIn(".output query_reachable", combined_program)
            self.assertIn(".output query_downstream_reference", combined_program)

            artifact = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["status"], "success")
            self.assertEqual(artifact["query"]["id"], "compare_known_object_reachability")
            self.assertEqual(
                artifact["source_id"],
                "3b212201-f8b6-47ed-9019-d7961f3276c8",
            )
            self.assertEqual(artifact["diagnostics"], [])
            self.assertEqual(
                artifact["combined_program_path"],
                str(combined_program_path),
            )
            self.assertEqual(artifact["raw_output_dir"], str(raw_output_dir))
            self.assertIn("generated_query_datalog", artifact)
            self.assertTrue(artifact["result_sets"]["reachable_targets"])
            self.assertTrue(artifact["result_sets"]["downstream_reference_targets"])

    def test_query_command_persists_failed_diagnostic_when_souffle_is_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"
            env = dict(os.environ)
            env["PATH"] = str(Path(tmp_dir) / "empty-path")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "compare_known_object_reachability",
                    str(E06_DERIVED_GRAPH_SEMANTICS),
                    "--source-id",
                    "3b212201-f8b6-47ed-9019-d7961f3276c8",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Missing required deterministic engine: souffle", result.stdout)

            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(
                artifact["diagnostics"],
                [
                    {
                        "code": "missing_souffle",
                        "message": "Missing required deterministic engine: souffle",
                    }
                ],
            )

    def test_query_command_persists_failed_diagnostic_for_invalid_datalog(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            invalid_datalog = tmp_path / "invalid.dl"
            invalid_datalog.write_text("this is not souffle datalog\n", encoding="utf-8")
            output_dir = tmp_path / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "compare_known_object_reachability",
                    str(invalid_datalog),
                    "--source-id",
                    "3b212201-f8b6-47ed-9019-d7961f3276c8",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Souffle query execution failed", result.stdout)

            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(artifact["diagnostics"][0]["code"], "souffle_execution_failed")
            self.assertIn("Souffle query execution failed", artifact["diagnostics"][0]["message"])

    def test_query_command_treats_empty_result_sets_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "compare_known_object_reachability",
                    str(E06_DERIVED_GRAPH_SEMANTICS),
                    "--source-id",
                    "fb0a17bc-9dd4-48fa-a69e-2c10b26648db",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("(none)", result.stdout)
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "success")
            self.assertEqual(artifact["diagnostics"], [])
            self.assertEqual(artifact["result_sets"]["reachable_targets"], [])
            self.assertEqual(artifact["result_sets"]["downstream_reference_targets"], [])

    def test_query_command_warns_when_source_id_is_absent_from_node_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "compare_known_object_reachability",
                    str(E06_DERIVED_GRAPH_SEMANTICS),
                    "--source-id",
                    "not-a-real-node-id",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Warning: source ID is absent from node facts", result.stdout)
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "success")
            self.assertEqual(
                artifact["diagnostics"],
                [
                    {
                        "code": "source_id_absent",
                        "message": "Warning: source ID is absent from node facts",
                    }
                ],
            )
            self.assertEqual(artifact["result_sets"]["reachable_targets"], [])

    def test_query_command_overwrites_learning_artifacts_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"
            command = [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "query-derived-graph",
                "compare_known_object_reachability",
                str(E06_DERIVED_GRAPH_SEMANTICS),
                "--source-id",
                "3b212201-f8b6-47ed-9019-d7961f3276c8",
                "--output-dir",
                str(output_dir),
            ]

            first_result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            (output_dir / "query_result.json").write_text(
                "stale result", encoding="utf-8"
            )
            (output_dir / "combined_query.dl").write_text(
                "stale program", encoding="utf-8"
            )

            second_result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "success")
            self.assertIn(
                ".output query_reachable",
                (output_dir / "combined_query.dl").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
