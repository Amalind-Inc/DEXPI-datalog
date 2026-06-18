from __future__ import annotations

from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
QUERY_CORPUS_DIR = REPO_ROOT / "queries" / "corpus"


class QueryCorpusTests(unittest.TestCase):
    def load_entry(self, query_id: str) -> dict[str, object]:
        entry_path = QUERY_CORPUS_DIR / f"{query_id}.yaml"
        self.assertTrue(entry_path.exists(), entry_path)
        self.assertNotIn("rules", entry_path.parts)
        return yaml.safe_load(entry_path.read_text(encoding="utf-8"))

    def test_compare_known_object_reachability_entry_records_deterministic_contract(
        self,
    ) -> None:
        entry = self.load_entry("compare_known_object_reachability")

        self.assertEqual(entry["id"], "compare_known_object_reachability")
        self.assertEqual(entry["status"], "supported_deterministic")
        self.assertEqual(
            entry["question"],
            "Compare reachable targets and downstream_reference targets from a known source object.",
        )
        self.assertEqual(entry["determinism"]["source_of_truth"], "deterministic_query_output")
        self.assertEqual(entry["determinism"]["current_engine"], "souffle")
        self.assertIn("ergoai", entry["determinism"]["future_engine_candidates"])
        self.assertIn("node", entry["requires"]["predicates"])
        self.assertIn("node_label", entry["requires"]["predicates"])
        self.assertIn("reachable", entry["requires"]["predicates"])
        self.assertIn("downstream_reference", entry["requires"]["predicates"])
        self.assertIn("classify_question", entry["llm_roles"]["allowed"])
        self.assertIn("produce_compliance_answer", entry["llm_roles"]["disallowed"])

    def test_classify_pump_discharge_path_entry_records_missing_predicates(
        self,
    ) -> None:
        entry = self.load_entry("classify_pump_discharge_path")

        self.assertEqual(entry["id"], "classify_pump_discharge_path")
        self.assertEqual(entry["status"], "unsupported_missing_predicates")
        self.assertEqual(entry["unsupported_reason"], "unsupported_missing_predicates")
        self.assertEqual(entry["determinism"]["source_of_truth"], "deterministic_query_output")
        self.assertEqual(entry["determinism"]["current_engine"], "souffle")
        self.assertIn("ergoai", entry["determinism"]["future_engine_candidates"])
        self.assertIn("node", entry["requires"]["available_predicates"])
        self.assertIn("reachable", entry["requires"]["available_predicates"])
        self.assertIn("discharge_nozzle", entry["requires"]["missing_predicates"])
        self.assertIn("first_unbranched_downstream_segment", entry["requires"]["missing_predicates"])
        self.assertIn("classify_question", entry["llm_roles"]["allowed"])
        self.assertIn("produce_compliance_answer", entry["llm_roles"]["disallowed"])

    def test_manual_valve_before_check_valve_entry_records_future_candidate_scope(
        self,
    ) -> None:
        entry = self.load_entry("manual_valve_before_check_valve_with_exceptions")

        self.assertEqual(entry["id"], "manual_valve_before_check_valve_with_exceptions")
        self.assertEqual(entry["status"], "future_candidate")
        self.assertEqual(entry["determinism"]["source_of_truth"], "deterministic_query_output")
        self.assertEqual(entry["determinism"]["current_engine"], "souffle")
        self.assertIn("ergoai", entry["determinism"]["future_engine_candidates"])
        self.assertIn("ordered_path", entry["requires"]["missing_predicates"])
        self.assertIn("manual_valve", entry["requires"]["missing_predicates"])
        self.assertIn("check_valve", entry["requires"]["missing_predicates"])
        self.assertIn("exception_policy", entry["requires"]["missing_facts_or_policy"])
        self.assertIn("classify_question", entry["llm_roles"]["allowed"])
        self.assertIn("produce_compliance_answer", entry["llm_roles"]["disallowed"])


if __name__ == "__main__":
    unittest.main()
