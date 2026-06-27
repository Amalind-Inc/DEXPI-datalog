"""
Integration tests for the POST /api/review/sessions/{id}/qa-turns endpoint.

Boundary: HTTP endpoint with E06 DEXPI 1.3 fixture and scripted QA provider.
Tests assert the answer payload shape and structural witness properties,
not tool call counts or internal message formats.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from pydexpi_datalog.qa.grounded_qa_harness import (
    FinalAnswer,
    ScriptedQATurnProvider,
    ToolCall,
)
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


def _make_client(qa_provider_factory=None) -> tuple[TestClient, str]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        app = create_review_api_app(
            artifact_root=Path(tmp_dir) / "sessions",
            qa_provider_factory=qa_provider_factory,
        )
        client = TestClient(app)
        session_id = "qa-e06-session"
        prepared = client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": "E06V01-VER.EX01.xml",
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        assert prepared.status_code == 200, prepared.text
        return client, session_id


class QATurnsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(
                artifact_root=Path(tmp_dir) / "sessions",
            )
            cls.client = TestClient(app)
            cls.tmp_dir = tmp_dir
            cls.session_id = "qa-e06-class-session"

        # Fresh client with persistent tmp dir
        cls.tmp_path = Path(tempfile.mkdtemp())
        app = create_review_api_app(artifact_root=cls.tmp_path / "sessions")
        cls.client = TestClient(app)
        prepared = cls.client.post(
            f"/api/review/sessions/{cls.session_id}/prepare",
            json={
                "filename": "E06V01-VER.EX01.xml",
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        assert prepared.status_code == 200, prepared.text

    def test_qa_turn_returns_answered_status(self) -> None:
        """
        Behavior: POSTing a question to /qa-turns returns status="answered".
        """
        response = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What equipment is in this PID?"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "answered")
        self.assertEqual(body["session_id"], self.session_id)

    def test_qa_turn_returns_non_empty_answer_text(self) -> None:
        """
        Behavior: answer_text is a non-empty natural language string.
        """
        response = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What is reachable from the pump?"},
        )
        body = response.json()
        self.assertIsInstance(body["answer_text"], str)
        self.assertGreater(len(body["answer_text"]), 0)

    def test_qa_turn_evidence_references_are_valid_topology_ids(self) -> None:
        """
        Behavior: every evidence_reference in the response is a known topology ID.
        This verifies the response is grounded in the actual DEXPI topology.
        """
        topology = self.client.get(
            f"/api/review/sessions/{self.session_id}/topology"
        ).json()
        known_ids = {obj["id"] for obj in topology["graph_objects"]}

        response = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What is connected to the pump?"},
        )
        body = response.json()
        refs = body.get("evidence_references", [])
        for ref in refs:
            self.assertIn(
                ref,
                known_ids,
                f"evidence_reference {ref!r} is not a known topology ID",
            )

    def test_qa_turn_evidence_highlight_contains_matched_object_ids(self) -> None:
        """
        Behavior: evidence_highlight.matched_object_ids is populated and
        all IDs are valid topology IDs.
        """
        topology = self.client.get(
            f"/api/review/sessions/{self.session_id}/topology"
        ).json()
        known_ids = {obj["id"] for obj in topology["graph_objects"]}

        response = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What is reachable from the pump?"},
        )
        body = response.json()
        highlight = body["evidence_highlight"]
        matched = highlight["matched_object_ids"]
        self.assertGreater(len(matched), 0, "Expected at least one highlighted object")
        for mid in matched:
            self.assertIn(mid, known_ids)

    def test_qa_turn_evidence_highlight_paths_include_structural_witnesses(self) -> None:
        """
        Behavior: evidence_highlight.paths contains structural paths with node_ids and edge_ids,
        proving the witness is complete (not just source->target, but full intervening path).

        Targets a nozzle: in E06 the pump/heat-exchanger equipment nodes are isolated
        in the piping topology, so connectivity is observed at the nozzle/piping nodes.
        """
        response = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What is reachable from the nozzle?"},
        )
        body = response.json()
        paths = body["evidence_highlight"]["paths"]
        self.assertGreater(len(paths), 0, "Expected at least one witness path")
        for path in paths:
            self.assertIn("node_ids", path)
            self.assertIn("edge_ids", path)
            # Path must include at least one edge (otherwise it's not a structural witness)
            self.assertGreater(len(path["node_ids"]), 0)

    def test_qa_turn_without_prepared_session_returns_409(self) -> None:
        """
        Behavior: calling /qa-turns without a prepared session returns 409 session.not_ready.
        """
        response = self.client.post(
            "/api/review/sessions/no-such-session/qa-turns",
            json={"question": "What is reachable?"},
        )
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["error"]["code"], "session.not_ready")

    def test_qa_turn_without_question_returns_400(self) -> None:
        """
        Behavior: missing question field returns 400.
        """
        response = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={},
        )
        self.assertEqual(response.status_code, 400)

    def test_qa_turn_updates_session_evidence_highlight(self) -> None:
        """
        Behavior: after a qa-turn, the topology endpoint reflects the updated
        evidence_highlight from the QA answer.
        """
        response = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What is reachable?"},
        )
        qa_highlight = response.json()["evidence_highlight"]

        topology = self.client.get(
            f"/api/review/sessions/{self.session_id}/topology"
        ).json()
        topology_highlight = topology["evidence_highlight"]

        self.assertEqual(
            set(topology_highlight["matched_object_ids"]),
            set(qa_highlight["matched_object_ids"]),
        )

    def test_qa_turn_with_custom_scripted_provider(self) -> None:
        """
        Behavior: accepts a custom qa_provider_factory — used for testing with
        controlled tool call sequences.
        """

        class DirectAnswerProvider:
            """Provider that immediately returns a final answer with no tool calls."""

            def complete_with_tools(self, *, messages, tools):
                return FinalAnswer(
                    answer_text="Direct answer with no tool calls.",
                    evidence_references=[],
                )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_review_api_app(
                artifact_root=Path(tmp) / "sessions",
                qa_provider_factory=DirectAnswerProvider,
            )
            client = TestClient(app)
            session_id = "qa-custom-provider-session"
            client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            response = client.post(
                f"/api/review/sessions/{session_id}/qa-turns",
                json={"question": "Quick check"},
            )
            body = response.json()
            self.assertEqual(body["status"], "answered")
            self.assertEqual(body["answer_text"], "Direct answer with no tool calls.")
            self.assertEqual(body["evidence_references"], [])

    def test_ambiguous_text_returns_multiple_candidate_interpretation(self) -> None:
        """E06 has several nozzles; an ambiguous 'the nozzle' question is answered
        for several plausible candidates with disclosed object interpretation."""
        response = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What is connected to the nozzle?"},
        )
        body = response.json()
        self.assertEqual(body["status"], "answered")
        self.assertGreaterEqual(len(body["interpreted_object_ids"]), 2)
        # Interpretation is grounded: each interpreted object is real evidence.
        for interpreted in body["interpreted_object_ids"]:
            self.assertIn(interpreted, body["evidence_references"])

    def test_follow_up_reuses_prior_evidence_identity(self) -> None:
        """A follow-up using a pronoun resolves against prior-turn evidence IDs
        carried in conversation state."""
        first = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What is reachable from the nozzle?"},
        ).json()
        prior_ids = first["evidence_references"]
        self.assertTrue(prior_ids)

        follow_up = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={
                "question": "What is reachable from those?",
                "conversation": [
                    {
                        "question": "What is reachable from the nozzle?",
                        "answer_text": first["answer_text"],
                        "evidence_references": prior_ids,
                    }
                ],
            },
        ).json()
        self.assertEqual(follow_up["status"], "answered")
        # The follow-up reuses at least one prior evidence identity.
        self.assertTrue(
            set(follow_up["interpreted_object_ids"]) & set(prior_ids),
            "follow-up should reuse a prior evidence identity",
        )

    def test_prior_assistant_prose_is_rejected_as_evidence(self) -> None:
        """A provider that cites prose (not a topology id) has that citation
        rejected; it never reaches evidence references or the highlight."""

        class ProseCitingProvider:
            def complete_with_tools(self, *, messages, tools):
                return FinalAnswer(
                    answer_text="Per my earlier note, things connect.",
                    evidence_references=["per my earlier note, things connect"],
                    interpreted_object_ids=["per my earlier note"],
                )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_review_api_app(
                artifact_root=Path(tmp) / "sessions",
                qa_provider_factory=ProseCitingProvider,
            )
            client = TestClient(app)
            session_id = "qa-prose-reject"
            client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            body = client.post(
                f"/api/review/sessions/{session_id}/qa-turns",
                json={"question": "Does it all connect?"},
            ).json()
            self.assertEqual(body["evidence_references"], [])
            self.assertEqual(body["evidence_highlight"]["matched_object_ids"], [])
            self.assertIn(
                "per my earlier note, things connect", body["rejected_references"]
            )
