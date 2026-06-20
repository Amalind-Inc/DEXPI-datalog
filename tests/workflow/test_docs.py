from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
QA_SEAM_DOC = REPO_ROOT / "docs" / "deterministic_pid_qa.md"


class DeterministicPidQaDocsTests(unittest.TestCase):
    def test_public_docs_explain_the_deterministic_qa_seam(self) -> None:
        self.assertTrue(QA_SEAM_DOC.exists(), QA_SEAM_DOC)

        doc = QA_SEAM_DOC.read_text(encoding="utf-8")
        for required_text in [
            "graph_facts.json",
            "canonical base fact layer",
            "derived_graph_semantics.dl",
            "graph_facts.dl",
            "executable Datalog",
            "EDB",
            "IDB",
            "graph_topology_semantics.dl",
            "Python is the orchestration adapter",
            "Souffle",
            "ErgoAI",
            "future engine candidate",
            "LLM-assisted logic requests are in scope",
            "may not produce compliance answers",
            "Logic-Request Lifecycle",
            "Generated Datalog is not a trusted answer",
            "missing-capability diagnostics",
            "direct_process_connection",
            "experimental",
            "not yet trusted process-flow semantics",
        ]:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, doc)


if __name__ == "__main__":
    unittest.main()
