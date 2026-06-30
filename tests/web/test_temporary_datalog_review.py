from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from pydexpi_datalog.qa.grounded_qa_harness import FinalAnswer, ToolCall
from pydexpi_datalog.web.review_api import create_review_api_app


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
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every connected object satisfy the temporary topology rule?",
                    "generated_datalog": f'.decl answer(x:symbol)\n.output answer\nanswer("{self._answer_id}").',
                    "formal_restatement": "Return objects matching the temporary topology rule.",
                    "resolved_identity_ids": [self._answer_id],
                },
                tool_call_id="proposal-1",
            )
        return FinalAnswer(answer_text="Proposal ready for confirmation.")


class TemporaryDatalogReviewTests(unittest.TestCase):
    def test_qa_turn_pauses_for_temporary_datalog_confirmation_then_executes(self) -> None:
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
            answer_id_holder["answer_id"] = prepared.json()["topology_view"]["nodes"][0]["id"]

            proposed = client.post(
                f"/api/review/sessions/{session_id}/qa-turns",
                json={"question": "Must every connected object satisfy the temporary topology rule?"},
            )
            self.assertEqual(proposed.status_code, 200, proposed.text)
            proposal_body = proposed.json()
            self.assertEqual(proposal_body["status"], "needs_datalog_confirmation")
            confirmation = proposal_body["datalog_confirmation"]
            self.assertEqual(confirmation["validation"]["status"], "safe_to_confirm")
            self.assertFalse(confirmation["proposal_result"]["executed"])

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
            self.assertEqual(answer["evidence"]["items"][0]["id"], answer_id_holder["answer_id"])
            self.assertEqual(answer["evidence_highlight"]["matched_object_ids"], [answer_id_holder["answer_id"]])

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


if __name__ == "__main__":
    unittest.main()
