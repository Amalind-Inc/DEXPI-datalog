from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from pydexpi_datalog.qa.grounded_qa_harness import FinalAnswer, ToolCall
from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.web.review_api import create_review_api_app


STRUCTURED_INTENT = {
    "source_classes": ["TopologyObject"],
    "target_classes": ["TopologyObject"],
    "source_role": "connected_object",
    "target_role": "answer_object",
    "graph_scope": "all_topology",
    "direction": "undirected",
    "quantifier": "all",
    "negated": False,
    "output_obligations": ["answer_ids"],
}


REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class TemporaryDatalogProposalProvider:
    def __init__(self, answer_id: str) -> None:
        self._step = 0
        self._answer_id = answer_id

    def complete_with_tools(self, *, messages, tools):
        if self._step == 0:
            self._step += 1
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template covers this rule.",
                    "structured_intent": STRUCTURED_INTENT,
                },
                tool_call_id="no-fit-1",
            )
        if self._step == 1:
            self._step += 1
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every connected object satisfy the temporary topology rule?",
                    "generated_datalog": encode_structured_intent_program(
                        (
                            ".decl answer(x:symbol)\n.output answer\n"
                            f'answer("{self._answer_id}").'
                        ),
                        STRUCTURED_INTENT,
                    ),
                    "formal_restatement": "Return objects matching the temporary topology rule.",
                    "faithfulness_review": {
                        "status": "faithful",
                        "back_translated_intent": STRUCTURED_INTENT,
                        "diagnostics": [],
                    },
                    "resolved_identity_ids": [self._answer_id],
                },
                tool_call_id="proposal-1",
            )
        return FinalAnswer(answer_text="Proposal ready for confirmation.")


class TemporaryDatalogReviewTests(unittest.TestCase):
    def test_qa_turn_pauses_for_temporary_datalog_confirmation_then_executes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            answer_id_holder: dict[str, str] = {}

            def provider_factory():
                return TemporaryDatalogProposalProvider(answer_id_holder["answer_id"])

            app = create_review_api_app(
                artifact_root=Path(tmp_dir) / "sessions",
                qa_provider_factory=provider_factory,
            )
            client = TestClient(app)
            session_id = "temp-datalog-session"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={"filename": E06_FIXTURE.name, "content": E06_FIXTURE.read_text()},
            )
            self.assertEqual(prepared.status_code, 200, prepared.text)
            answer_id_holder["answer_id"] = prepared.json()["topology_view"]["nodes"][
                0
            ]["id"]

            proposed = client.post(
                f"/api/review/sessions/{session_id}/qa-turns",
                json={
                    "question": "Must every connected object satisfy the temporary topology rule?"
                },
            )
            self.assertEqual(proposed.status_code, 200, proposed.text)
            proposal_body = proposed.json()
            self.assertEqual(proposal_body["status"], "needs_datalog_confirmation")
            confirmation = proposal_body["datalog_confirmation"]
            self.assertEqual(confirmation["validation"]["status"], "safe_to_confirm")
            self.assertFalse(confirmation["proposal_result"]["executed"])
            self.assertEqual(
                confirmation["allowed_actions"],
                ["run", "revise_interpretation", "revise_query", "cancel"],
            )
            self.assertEqual(
                confirmation["interpretation"],
                "Return objects matching the temporary topology rule.",
            )
            self.assertEqual(
                confirmation["effect"],
                "Read-only analysis. Does not modify the P&ID, graph, annotations, or rule pack.",
            )
            self.assertIn("starting_object_ids", confirmation["scope"])
            self.assertIn("included_edge_types", confirmation["assumptions"])
            self.assertEqual(
                confirmation["exact_datalog"], confirmation["generated_datalog"]
            )

            executed = client.post(
                f"/api/review/sessions/{session_id}/temporary-datalog-reviews",
                json={
                    "question": "Must every connected object satisfy the temporary topology rule?",
                    "decision": "confirm",
                    "proposal_result": confirmation["proposal_result"],
                },
            )
            self.assertEqual(executed.status_code, 200, executed.text)
            answer = executed.json()
            self.assertEqual(answer["status"], "answered")
            self.assertEqual(
                answer["evidence"]["items"][0]["id"], answer_id_holder["answer_id"]
            )
            self.assertEqual(
                answer["evidence_highlight"]["matched_object_ids"],
                [answer_id_holder["answer_id"]],
            )

    def test_cancel_temporary_datalog_confirmation_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            session_id = "cancel-temp-datalog"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={"filename": E06_FIXTURE.name, "content": E06_FIXTURE.read_text()},
            )
            self.assertEqual(prepared.status_code, 200, prepared.text)

            canceled = client.post(
                f"/api/review/sessions/{session_id}/temporary-datalog-reviews",
                json={"question": "q", "decision": "cancel", "proposal_result": {}},
            )
            self.assertEqual(canceled.status_code, 200, canceled.text)
            self.assertEqual(canceled.json()["status"], "canceled")
            self.assertFalse(canceled.json()["executed"])

    def test_confirm_with_unproposed_payload_is_refused(self) -> None:
        """Approval must execute only proposals the server actually raised for
        review.  A client-fabricated proposal_result — even one whose hash is
        self-consistent and whose pair passes validation — must be refused."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            session_id = "forged-temp-datalog"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={"filename": E06_FIXTURE.name, "content": E06_FIXTURE.read_text()},
            )
            self.assertEqual(prepared.status_code, 200, prepared.text)
            target_id = prepared.json()["topology_view"]["nodes"][0]["id"]

            request = "Forged request the reviewer never saw"
            generated_datalog = (
                f'.decl answer(x:symbol)\n.output answer\nanswer("{target_id}").'
            )
            formal_restatement = "Forged restatement the reviewer never saw."
            forged_id = hashlib.sha256(
                (request + "\n" + generated_datalog + "\n" + formal_restatement).encode(
                    "utf-8"
                )
            ).hexdigest()[:16]
            forged_proposal_result = {
                "status": "confirmation_required",
                "code": "tool.confirmation_required",
                "tool_name": "propose_temporary_datalog",
                "executed": False,
                "proposal": {
                    "proposal_id": forged_id,
                    "request": request,
                    "generated_datalog": generated_datalog,
                    "formal_restatement": formal_restatement,
                    "resolved_identity_ids": [target_id],
                },
                "validation": {"status": "safe_to_confirm", "diagnostics": []},
                "confirmation": {
                    "required": True,
                    "grant": "execute_temporary_datalog_pair",
                    "proposal_id": forged_id,
                },
            }

            response = client.post(
                f"/api/review/sessions/{session_id}/temporary-datalog-reviews",
                json={
                    "question": request,
                    "decision": "confirm",
                    "proposal_result": forged_proposal_result,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["status"], "execution_failed")
            self.assertFalse(body["executed"])
            codes = [diag.get("code") for diag in body["diagnostics"]]
            self.assertIn("temporary_datalog.proposal_unknown", codes)

    def test_confirm_and_cancel_decisions_append_audit_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir) / "sessions"
            answer_id_holder: dict[str, str] = {}

            def provider_factory():
                return TemporaryDatalogProposalProvider(answer_id_holder["answer_id"])

            app = create_review_api_app(
                artifact_root=artifact_root,
                qa_provider_factory=provider_factory,
            )
            client = TestClient(app)
            session_id = "audit-temp-datalog"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={"filename": E06_FIXTURE.name, "content": E06_FIXTURE.read_text()},
            )
            self.assertEqual(prepared.status_code, 200, prepared.text)
            answer_id_holder["answer_id"] = prepared.json()["topology_view"]["nodes"][
                0
            ]["id"]

            question = (
                "Must every connected object satisfy the temporary topology rule?"
            )
            proposed = client.post(
                f"/api/review/sessions/{session_id}/qa-turns",
                json={"question": question},
            )
            self.assertEqual(proposed.status_code, 200, proposed.text)
            confirmation = proposed.json()["datalog_confirmation"]
            proposal_result = confirmation["proposal_result"]

            executed = client.post(
                f"/api/review/sessions/{session_id}/temporary-datalog-reviews",
                json={
                    "question": question,
                    "decision": "confirm",
                    "proposal_result": proposal_result,
                },
            )
            self.assertEqual(executed.status_code, 200, executed.text)
            self.assertEqual(executed.json()["status"], "answered")

            canceled = client.post(
                f"/api/review/sessions/{session_id}/temporary-datalog-reviews",
                json={
                    "question": question,
                    "decision": "cancel",
                    "proposal_result": proposal_result,
                },
            )
            self.assertEqual(canceled.status_code, 200, canceled.text)

            audit_path = artifact_root / session_id / "datalog_audit.jsonl"
            self.assertTrue(audit_path.exists(), "audit log must exist after decisions")
            records = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(records), 2)

            confirm_record, cancel_record = records
            proposal = proposal_result["proposal"]
            self.assertEqual(confirm_record["proposal_id"], proposal["proposal_id"])
            self.assertEqual(confirm_record["session_id"], session_id)
            self.assertEqual(confirm_record["question"], question)
            self.assertEqual(
                confirm_record["formal_restatement"], proposal["formal_restatement"]
            )
            self.assertEqual(
                confirm_record["generated_datalog"], proposal["generated_datalog"]
            )
            self.assertEqual(
                confirm_record["faithfulness_probes"],
                proposal["faithfulness_probes"],
            )
            self.assertEqual(
                confirm_record["faithfulness_probe_attempts"],
                proposal["faithfulness_probe_attempts"],
            )
            self.assertEqual(
                confirm_record["faithfulness_review"],
                proposal["faithfulness_review"],
            )
            self.assertEqual(
                confirm_record["faithfulness_gate"],
                proposal["faithfulness_gate"],
            )
            self.assertEqual(
                confirm_record["faithfulness_gate_attempts"],
                proposal["faithfulness_gate_attempts"],
            )
            self.assertEqual(confirm_record["decision"], "approved")
            self.assertIn("T", confirm_record["decided_at"])
            self.assertTrue(confirm_record["executed"])
            self.assertEqual(confirm_record["execution_status"], "answered")

            self.assertEqual(cancel_record["decision"], "canceled")
            self.assertFalse(cancel_record["executed"])
            self.assertEqual(cancel_record["proposal_id"], proposal["proposal_id"])
            self.assertEqual(cancel_record["session_id"], session_id)


if __name__ == "__main__":
    unittest.main()
