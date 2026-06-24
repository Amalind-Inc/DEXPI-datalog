from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
QA_SEAM_DOC = REPO_ROOT / "docs" / "deterministic_pid_qa.md"
CHAINLIT_SPIKE_DOC = REPO_ROOT / "docs" / "chainlit_oss_v1_review_shell_spike.md"
CHAINLIT_ADR_DOC = REPO_ROOT / "docs" / "adr" / "0001-web-review-shell.md"
TOPOLOGY_VIEW_CONTRACT_DOC = REPO_ROOT / "docs" / "contracts" / "topology_view_model.md"


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

    def test_chainlit_spike_records_review_shell_decision(self) -> None:
        self.assertTrue(CHAINLIT_SPIKE_DOC.exists(), CHAINLIT_SPIKE_DOC)

        doc = CHAINLIT_SPIKE_DOC.read_text(encoding="utf-8")
        for required_text in [
            "Use Chainlit as a partial shell",
            "DEXPI upload can start a session-preparation job",
            "Chainlit shows coarse job status and optional stage text",
            "Chainlit can host or embed a custom topology panel",
            "Chainlit actions can support Improve, confirmation, and selected rule-pack execution",
            "Decision is `Chainlit partial shell`",
            "AskFileMessage",
            "TaskList",
            "CustomElement",
            "Action",
            "@chainlit/react-client",
            "not the primary OSS v1 product shell",
        ]:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, doc)

    def test_web_review_shell_adr_records_frontend_strategy(self) -> None:
        self.assertTrue(CHAINLIT_ADR_DOC.exists(), CHAINLIT_ADR_DOC)

        doc = CHAINLIT_ADR_DOC.read_text(encoding="utf-8")
        for required_text in [
            "Status: Accepted",
            "Use a repository-owned Python backend API plus a React/TypeScript frontend as the primary OSS v1 product architecture.",
            "Chainlit is allowed only as a minimal prototype shell",
            "not the primary product frontend",
            "repository-owned deterministic workflow seams",
            "explicit session IDs",
            "review workflow jobs",
            "full-page P&ID acceptance corpus",
            "topology panel",
            "Cytoscape.js",
            "provider-neutral BYOK",
            "zero-secret-leak",
            "Playwright",
            "upload a real DEXPI XML file",
            "migration path",
            "dedicated frontend",
        ]:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, doc)

    def test_topology_view_contract_documents_evidence_ready_model(self) -> None:
        self.assertTrue(TOPOLOGY_VIEW_CONTRACT_DOC.exists(), TOPOLOGY_VIEW_CONTRACT_DOC)

        doc = TOPOLOGY_VIEW_CONTRACT_DOC.read_text(encoding="utf-8")
        for required_text in [
            "schema_version: topology-view.v1",
            "stable topology ID",
            "not raw pyDEXPI graph IDs",
            "evidence_map",
            "source_scope_ids",
            "matched_object_ids",
            "paths",
            "All IDs in a highlight payload must exist in `evidence_map`",
            "not a raw graph dump",
        ]:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, doc)


if __name__ == "__main__":
    unittest.main()
