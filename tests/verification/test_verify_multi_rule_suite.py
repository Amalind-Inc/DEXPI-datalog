from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
MULTI_RULE_MANIFEST_PATH = (
    REPO_ROOT / "testdata" / "verifier_suite" / "multi_rule_manifest.json"
)
MULTI_RULE_DOC_PATH = REPO_ROOT / "docs" / "contracts" / "multi_rule_detection.md"


class VerifyMultiRuleSuiteCliTests(unittest.TestCase):
    def run_verify_suite(
        self, manifest_path: Path, output_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "verify-suite",
                str(manifest_path),
                "--output-dir",
                str(output_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_verify_suite_reports_two_rule_results_on_overlapping_e06_region(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "suite-results"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_verify_suite(MULTI_RULE_MANIFEST_PATH, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact_path = output_dir / "overlap_e06_natural.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

            self.assertEqual(artifact["fixture_id"], "overlap_e06_natural")
            self.assertEqual(artifact["post_edit_reevaluation"], "deferred")
            self.assertEqual(
                [item["rule_id"] for item in artifact["results"]],
                [
                    "pump_discharge_check_valve",
                    "pump_discharge_not_terminal_nozzle",
                ],
            )
            self.assertEqual(
                [item["result_type"] for item in artifact["results"]],
                ["hard_violation", "hard_violation"],
            )

    def test_repo_documents_multi_rule_detection_and_deferred_reevaluation(self) -> None:
        self.assertTrue(MULTI_RULE_DOC_PATH.exists(), MULTI_RULE_DOC_PATH)
        doc = MULTI_RULE_DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("Multi-Rule Detection", doc)
        self.assertIn("post-edit re-evaluation are explicitly", doc)


if __name__ == "__main__":
    unittest.main()
