from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_MANIFEST_PATH = REPO_ROOT / "fixtures" / "verifier_suite" / "manifest.json"
EXPECTED_DIR = REPO_ROOT / "fixtures" / "verifier_suite" / "expected"


class VerifySuiteCliTests(unittest.TestCase):
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

    def test_verify_suite_emits_expected_results_for_all_checked_in_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "suite-results"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_verify_suite(SUITE_MANIFEST_PATH, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            suite_manifest = json.loads(SUITE_MANIFEST_PATH.read_text(encoding="utf-8"))
            self.assertEqual(len(suite_manifest["fixtures"]), 6)

            for fixture in suite_manifest["fixtures"]:
                fixture_id = fixture["fixture_id"]
                actual_path = output_dir / f"{fixture_id}.json"
                expected_path = EXPECTED_DIR / f"{fixture_id}.json"
                with self.subTest(fixture_id=fixture_id):
                    self.assertTrue(actual_path.exists(), actual_path)
                    self.assertTrue(expected_path.exists(), expected_path)
                    actual = json.loads(actual_path.read_text(encoding="utf-8"))
                    expected = json.loads(expected_path.read_text(encoding="utf-8"))
                    self.assertEqual(actual, expected)

    def test_suite_manifest_covers_required_result_mix_and_labels_adapted_fixtures(
        self,
    ) -> None:
        suite_manifest = json.loads(SUITE_MANIFEST_PATH.read_text(encoding="utf-8"))
        counts = {
            "pass": 0,
            "hard_violation": 0,
            "bounded_failure_off_page": 0,
            "evaluation_diagnostic": 0,
        }
        adapted_count = 0

        for fixture in suite_manifest["fixtures"]:
            expected_path = REPO_ROOT / fixture["expected_result_path"]
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            counts[expected["result_type"]] += 1
            if fixture["adapted"]:
                adapted_count += 1
                self.assertTrue(fixture["source_example"])
                self.assertTrue(fixture["adaptation_reason"])
                self.assertTrue(fixture["changes"])

        self.assertEqual(counts["pass"], 2)
        self.assertEqual(counts["hard_violation"], 2)
        self.assertEqual(counts["bounded_failure_off_page"], 1)
        self.assertEqual(counts["evaluation_diagnostic"], 1)
        self.assertGreaterEqual(adapted_count, 1)


if __name__ == "__main__":
    unittest.main()
