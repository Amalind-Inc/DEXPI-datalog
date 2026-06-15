from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)
STABLE_COMMAND_DOC_PATH = (
    REPO_ROOT / "docs" / "contracts" / "stable_verifier_command.md"
)


class VerifyRawFixtureCliTests(unittest.TestCase):
    def run_verify_raw_fixture(
        self, fixture_path: Path, output_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "verify-raw-fixture",
                str(fixture_path),
                "--output-dir",
                str(output_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_verify_raw_fixture_persists_result_artifact_from_raw_e06_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "raw-verify"
            artifact_path = output_dir / "E06V01-VER.EX01.result.json"
            derived_path = output_dir / "E06V01-VER.EX01.derived_graph_semantics.dl"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_verify_raw_fixture(E06_FIXTURE, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(artifact_path.exists())
            self.assertTrue(derived_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["result_type"], "hard_violation")
            self.assertEqual(artifact["rule_id"], "pump_discharge_check_valve")
            self.assertEqual(
                artifact["evidence"]["derived_graph_semantics"],
                {
                    "artifact": "E06V01-VER.EX01.derived_graph_semantics.dl",
                    "traversal_predicate": "downstream_reference",
                    "reachability_predicate": "reachable",
                },
            )

    def test_repo_documents_stable_verifier_command_and_example_artifacts(self) -> None:
        self.assertTrue(STABLE_COMMAND_DOC_PATH.exists(), STABLE_COMMAND_DOC_PATH)
        doc = STABLE_COMMAND_DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("verify-raw-fixture", doc)
        self.assertIn("verify-suite", doc)
        self.assertIn("pass_c01_local_segment.json", doc)
        self.assertIn("hard_violation_e06_natural.json", doc)


if __name__ == "__main__":
    unittest.main()
