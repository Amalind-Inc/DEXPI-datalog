from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_RULE_PATH = REPO_ROOT / "rules" / "pump_discharge_check_valve.yaml"
INVALID_RULE_PATH = REPO_ROOT / "rules" / "invalid_pump_discharge_rule.yaml"
CHECKED_IN_DATALOG_PATH = (
    REPO_ROOT / "rules" / "compiled" / "pump_discharge_check_valve" / "rule.dl"
)
SCHEMA_DOC_PATH = REPO_ROOT / "docs" / "contracts" / "minimal_pump_discharge_rule_schema.md"


class CompileRuleCliTests(unittest.TestCase):
    def run_compile_rule(
        self, rule_path: Path, output_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "compile-rule",
                str(rule_path),
                "--output-dir",
                str(output_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_compile_rule_emits_visible_datalog_for_checked_in_discharge_rule(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "compiled-rule"
            compiled_datalog_path = (
                output_dir / "pump_discharge_check_valve" / "rule.dl"
            )
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_compile_rule(VALID_RULE_PATH, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(compiled_datalog_path.exists())

            datalog = compiled_datalog_path.read_text(encoding="utf-8")
            self.assertIn(
                'rule_subject_class("pump_discharge_check_valve", "CentrifugalPump").',
                datalog,
            )
            self.assertIn(
                'rule_required_component_class("pump_discharge_check_valve", "CheckValve").',
                datalog,
            )

    def test_compile_rule_persists_deterministic_validation_output_for_invalid_yaml(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "compiled-rule"
            artifact_path = (
                output_dir / "invalid_pump_discharge_rule" / "rule_compilation.json"
            )
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_compile_rule(INVALID_RULE_PATH, output_dir)

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(artifact_path.exists())

            compilation = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(compilation["rule_id"], "invalid_pump_discharge_rule")
            self.assertEqual(compilation["status"], "invalid")
            self.assertEqual(
                compilation["diagnostics"],
                [
                    {
                        "code": "rule.missing_required_field",
                        "message": "Missing required field: require.component_class",
                        "path": "require.component_class",
                        "severity": "error",
                    }
                ],
            )

    def test_repo_persists_checked_in_datalog_output_for_valid_rule(self) -> None:
        self.assertTrue(CHECKED_IN_DATALOG_PATH.exists(), CHECKED_IN_DATALOG_PATH)
        datalog = CHECKED_IN_DATALOG_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '.decl rule_subject_class(rule:symbol, class:symbol)',
            datalog,
        )
        self.assertIn(
            'rule_subject_class("pump_discharge_check_valve", "CentrifugalPump").',
            datalog,
        )

    def test_repo_persists_minimal_rule_schema_doc(self) -> None:
        self.assertTrue(SCHEMA_DOC_PATH.exists(), SCHEMA_DOC_PATH)
        schema_doc = SCHEMA_DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("Minimal Pump Discharge Rule Schema", schema_doc)
        self.assertIn("rule_family: pump_discharge_path", schema_doc)


if __name__ == "__main__":
    unittest.main()
