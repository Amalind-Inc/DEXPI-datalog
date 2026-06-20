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
    / "testdata"
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

    def test_query_command_resolves_source_tag_through_datalog(self) -> None:
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
                    "--source-tag",
                    "P-4713",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "Source ID: 16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb",
                result.stdout,
            )
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                artifact["source_id"],
                "16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb",
            )
            self.assertEqual(
                artifact["source_selection"],
                {
                    "resolved_source_id": "16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb",
                    "selectors": {"source_tag": "P-4713"},
                },
            )

    def test_query_command_resolves_source_proteus_id_through_datalog(self) -> None:
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
                    "--source-proteus-id",
                    "CentrifugalPump-1",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                artifact["source_id"],
                "16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb",
            )

    def test_query_command_accepts_matching_source_selectors(self) -> None:
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
                    "16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb",
                    "--source-tag",
                    "P-4713",
                    "--source-proteus-id",
                    "CentrifugalPump-1",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "success")
            self.assertEqual(artifact["diagnostics"], [])
            self.assertEqual(
                artifact["source_selection"]["resolved_source_id"],
                "16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb",
            )

    def test_query_command_rejects_mismatched_source_selectors(self) -> None:
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
                    "--source-tag",
                    "P-4713",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Source selectors resolve to different graph nodes", result.stdout)
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(artifact["diagnostics"][0]["code"], "source_selector_mismatch")

    def test_query_command_rejects_missing_source_selector(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "query-derived-graph",
                "compare_known_object_reachability",
                str(E06_DERIVED_GRAPH_SEMANTICS),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing source selector", result.stdout)

    def test_query_command_rejects_unresolved_source_selector(self) -> None:
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
                    "--source-tag",
                    "not-a-real-tag",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Source selector did not resolve to a graph node", result.stdout)
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(artifact["diagnostics"][0]["code"], "source_selector_no_match")

    def test_query_command_rejects_ambiguous_source_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            ambiguous_semantics = tmp_path / "ambiguous_derived_graph_semantics.dl"
            ambiguous_semantics.write_text(
                E06_DERIVED_GRAPH_SEMANTICS.read_text(encoding="utf-8")
                + '\nnode("extra-pump-node").\n'
                + 'node_label("extra-pump-node", "Pump").\n'
                + 'node_tag("extra-pump-node", "P-4713").\n',
                encoding="utf-8",
            )
            output_dir = tmp_path / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "compare_known_object_reachability",
                    str(ambiguous_semantics),
                    "--source-tag",
                    "P-4713",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Source selector resolved to multiple graph nodes", result.stdout)
            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(artifact["diagnostics"][0]["code"], "source_selector_ambiguous")

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

    def test_query_command_persists_unsupported_missing_predicates_artifact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "classify_pump_discharge_path",
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
            self.assertIn("Status: unsupported_missing_predicates", result.stdout)
            self.assertFalse((output_dir / "combined_query.dl").exists())
            self.assertFalse((output_dir / "internal" / "souffle-output").exists())

            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "unsupported")
            self.assertEqual(artifact["query"]["id"], "classify_pump_discharge_path")
            self.assertEqual(
                artifact["query"]["status"], "unsupported_missing_predicates"
            )
            self.assertEqual(
                artifact["source_id"],
                "3b212201-f8b6-47ed-9019-d7961f3276c8",
            )
            self.assertEqual(
                artifact["diagnostics"],
                [
                    {
                        "code": "unsupported_missing_predicates",
                        "message": "Query cannot run until required predicates are derived",
                        "missing_predicates": [
                            "discharge_nozzle",
                            "first_unbranched_downstream_segment",
                            "branch_boundary",
                            "inline_continuity_item",
                            "check_valve_on_discharge_segment",
                        ],
                    }
                ],
            )
            self.assertEqual(artifact["result_sets"], {})

    def test_query_command_rejects_source_rooted_unsupported_query_without_source_selector(
        self,
    ) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "query-derived-graph",
                "classify_pump_discharge_path",
                str(E06_DERIVED_GRAPH_SEMANTICS),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing source selector", result.stdout)

    def test_query_command_persists_future_candidate_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "manual_valve_before_check_valve_with_exceptions",
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
            self.assertIn("Status: future_candidate", result.stdout)
            self.assertFalse((output_dir / "combined_query.dl").exists())
            self.assertFalse((output_dir / "internal" / "souffle-output").exists())

            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "future_candidate")
            self.assertEqual(
                artifact["query"]["id"],
                "manual_valve_before_check_valve_with_exceptions",
            )
            self.assertEqual(artifact["query"]["status"], "future_candidate")
            self.assertEqual(
                artifact["diagnostics"],
                [
                    {
                        "code": "future_candidate",
                        "message": "Query is recorded for future deterministic promotion",
                        "missing_predicates": [
                            "ordered_path",
                            "manual_valve",
                            "check_valve",
                            "valve_order_on_discharge_path",
                            "exception_applies",
                        ],
                        "missing_facts_or_policy": [
                            "exception_policy",
                            "valve_classification_policy",
                        ],
                    }
                ],
            )
            self.assertEqual(artifact["candidate_result_sets"], [
                "ordered_discharge_path",
                "valve_order_findings",
                "applied_exceptions",
            ])

    def test_query_command_allows_whole_pid_future_candidate_without_source_selector(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "classify_all_pump_discharge_paths",
                    str(E06_DERIVED_GRAPH_SEMANTICS),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Status: future_candidate", result.stdout)
            self.assertFalse((output_dir / "combined_query.dl").exists())

            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "future_candidate")
            self.assertEqual(artifact["query_scope"], {"kind": "whole_pid"})
            self.assertNotIn("source_id", artifact)
            self.assertNotIn("source_selection", artifact)

    def test_query_command_compares_direct_process_connections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "query-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "query-derived-graph",
                    "compare_direct_process_connections",
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
            self.assertIn("Query ID: compare_direct_process_connections", result.stdout)
            self.assertIn("Direct process connection targets", result.stdout)
            self.assertIn("Experimental predicate: direct_process_connection", result.stdout)
            self.assertIn(
                "direct_process_connection matches downstream_reference", result.stdout
            )
            self.assertIn("narrower than reachable", result.stdout)

            artifact = json.loads(
                (output_dir / "query_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], "success")
            self.assertEqual(artifact["query"]["id"], "compare_direct_process_connections")
            self.assertTrue(
                artifact["result_sets"]["direct_process_connection_targets"]
            )
            self.assertEqual(
                artifact["comparison_summary"],
                {
                    "direct_vs_downstream_reference": "same_targets",
                    "direct_vs_reachable": "narrower_than_reachable",
                    "experimental_note": "direct_process_connection is experimental and not yet trusted process-flow semantics",
                },
            )
            self.assertTrue((output_dir / "combined_query.dl").exists())
            self.assertTrue(
                (
                    output_dir
                    / "internal"
                    / "souffle-output"
                    / "query_direct_process_connection.csv"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
