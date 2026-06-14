from __future__ import annotations

import json
from pathlib import Path
import unittest

from pydexpi_datalog.result_schemas import validate_result_schema


REPO_ROOT = Path(__file__).resolve().parents[1]
PASS_EXAMPLE_PATH = REPO_ROOT / "fixtures" / "report_examples" / "pass.json"
RESULT_SCHEMA_DOC_PATH = REPO_ROOT / "docs" / "contracts" / "rule_result_schemas.md"
HARD_VIOLATION_EXAMPLE_PATH = (
    REPO_ROOT / "fixtures" / "report_examples" / "hard_violation.json"
)
BOUNDED_FAILURE_EXAMPLE_PATH = (
    REPO_ROOT / "fixtures" / "report_examples" / "bounded_failure_off_page.json"
)
EVALUATION_DIAGNOSTIC_EXAMPLE_PATH = (
    REPO_ROOT / "fixtures" / "report_examples" / "evaluation_diagnostic.json"
)


class ResultSchemaTests(unittest.TestCase):
    def test_checked_in_pass_example_validates_against_stable_result_schema(self) -> None:
        example = json.loads(PASS_EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(validate_result_schema(example), [])

    def test_other_checked_in_result_examples_validate_against_stable_result_schema(
        self,
    ) -> None:
        for path in [
            HARD_VIOLATION_EXAMPLE_PATH,
            BOUNDED_FAILURE_EXAMPLE_PATH,
            EVALUATION_DIAGNOSTIC_EXAMPLE_PATH,
        ]:
            with self.subTest(path=path.name):
                example = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(validate_result_schema(example), [])

    def test_repo_persists_rule_result_schema_doc(self) -> None:
        self.assertTrue(RESULT_SCHEMA_DOC_PATH.exists(), RESULT_SCHEMA_DOC_PATH)
        schema_doc = RESULT_SCHEMA_DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("Rule Result Schemas", schema_doc)
        self.assertIn("bounded_failure_off_page", schema_doc)
        self.assertIn("evaluation_diagnostic", schema_doc)


if __name__ == "__main__":
    unittest.main()
