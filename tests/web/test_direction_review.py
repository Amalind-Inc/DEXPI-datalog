"""
Integration tests for inferred flow-direction review (37x.22.18).

Boundary: HTTP qa-turns + direction-reviews endpoints with the E06 fixture and
the default scripted provider. Asserts the pause/resume contract, the three
review actions, annotation reuse, and invalidation — observable payloads only.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

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
# A piping-rooted question whose witness runs through structural composition
# edges, so its flow direction is inferred (review required). Nozzle-rooted
# questions traverse explicit sourceItem/targetItem edges (no review).
INFERRED_QUESTION = "What is downstream of the piping?"
EXPLICIT_QUESTION = "What is downstream of the nozzle?"


def _client() -> tuple[TestClient, str, str]:
    tmp = tempfile.mkdtemp()
    app = create_review_api_app(artifact_root=Path(tmp) / "sessions")
    client = TestClient(app)
    session_id = "dir-session"
    prepared = client.post(
        f"/api/review/sessions/{session_id}/prepare",
        json={
            "filename": "E06V01-VER.EX01.xml",
            "content": E06_FIXTURE.read_text(encoding="utf-8"),
        },
    )
    assert prepared.status_code == 200, prepared.text
    return client, session_id, tmp


class DirectionReviewTests(unittest.TestCase):
    def test_inferred_direction_pauses_with_a_review_card(self) -> None:
        client, session_id, _ = _client()
        body = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()
        self.assertEqual(body["status"], "needs_direction_review")
        review = body["direction_review"]
        self.assertEqual(review["proposed_direction"], "downstream")
        self.assertEqual(review["direction_basis"], "inferred")
        self.assertEqual(review["review_status"], "pending")
        self.assertEqual(review["actions"], ["confirm", "reverse", "unknown"])
        # The card carries the complete highlighted witness.
        self.assertTrue(review["witness"]["edge_ids"])
        self.assertTrue(review["evidence_highlight"]["paths"])

    def test_explicit_direction_needs_no_review(self) -> None:
        client, session_id, _ = _client()
        body = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": EXPLICIT_QUESTION},
        ).json()
        self.assertEqual(body["status"], "answered")
        self.assertEqual(body["direction"]["direction_basis"], "explicit")
        self.assertFalse(body["direction"]["review_required"])

    def test_confirm_resumes_with_proposed_direction(self) -> None:
        client, session_id, _ = _client()
        review = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()["direction_review"]
        resumed = client.post(
            f"/api/review/sessions/{session_id}/direction-reviews",
            json={
                "question": INFERRED_QUESTION,
                "decision": "confirm",
                "review_key": review["review_key"],
            },
        ).json()
        self.assertEqual(resumed["status"], "answered")
        self.assertEqual(resumed["direction"]["review_status"], "confirmed")
        self.assertEqual(resumed["direction"]["effective_direction"], "downstream")

    def test_reverse_resumes_with_opposite_direction(self) -> None:
        client, session_id, _ = _client()
        review = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()["direction_review"]
        resumed = client.post(
            f"/api/review/sessions/{session_id}/direction-reviews",
            json={
                "question": INFERRED_QUESTION,
                "decision": "reverse",
                "review_key": review["review_key"],
            },
        ).json()
        self.assertEqual(resumed["direction"]["review_status"], "reversed")
        self.assertEqual(resumed["direction"]["effective_direction"], "upstream")

    def test_unknown_resumes_with_unknown_direction(self) -> None:
        client, session_id, _ = _client()
        review = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()["direction_review"]
        resumed = client.post(
            f"/api/review/sessions/{session_id}/direction-reviews",
            json={
                "question": INFERRED_QUESTION,
                "decision": "unknown",
                "review_key": review["review_key"],
            },
        ).json()
        self.assertEqual(resumed["direction"]["review_status"], "unknown")
        self.assertEqual(resumed["direction"]["effective_direction"], "unknown")

    def test_annotation_is_reused_for_same_source_path_and_boundary(self) -> None:
        client, session_id, _ = _client()
        review = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()["direction_review"]
        client.post(
            f"/api/review/sessions/{session_id}/direction-reviews",
            json={
                "question": INFERRED_QUESTION,
                "decision": "confirm",
                "review_key": review["review_key"],
            },
        )
        # Asking the same question again must NOT pause: the annotation is reused.
        again = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()
        self.assertEqual(again["status"], "answered")
        self.assertEqual(again["direction"]["review_status"], "confirmed")

    def test_annotation_is_invalidated_when_evaluation_boundary_changes(self) -> None:
        client, session_id, _ = _client()
        review = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()["direction_review"]
        client.post(
            f"/api/review/sessions/{session_id}/direction-reviews",
            json={
                "question": INFERRED_QUESTION,
                "decision": "confirm",
                "review_key": review["review_key"],
            },
        )
        # The opposite direction is a different evaluation boundary -> re-review.
        upstream = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": "What is upstream of the piping?"},
        ).json()
        self.assertEqual(upstream["status"], "needs_direction_review")

    def test_review_does_not_mutate_source_evidence(self) -> None:
        """Confirming a direction must not change the topology graph: node and
        edge identities and counts are unchanged after review."""
        client, session_id, _ = _client()
        before = client.get(f"/api/review/sessions/{session_id}/topology").json()
        review = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()["direction_review"]
        client.post(
            f"/api/review/sessions/{session_id}/direction-reviews",
            json={
                "question": INFERRED_QUESTION,
                "decision": "reverse",
                "review_key": review["review_key"],
            },
        )
        after = client.get(f"/api/review/sessions/{session_id}/topology").json()
        before_ids = {obj["id"] for obj in before["graph_objects"]}
        after_ids = {obj["id"] for obj in after["graph_objects"]}
        self.assertEqual(before_ids, after_ids)

    def test_non_directional_question_has_no_direction_metadata(self) -> None:
        client, session_id, _ = _client()
        body = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": "What is connected to the nozzle?"},
        ).json()
        self.assertEqual(body["status"], "answered")
        self.assertNotIn("direction", body)

    def test_direction_annotation_survives_conversation_compaction(self) -> None:
        """A confirmed direction annotation is session state, not conversation
        prose. It survives after the conversation is compacted past its threshold:
        re-asking the same inferred question resumes with the stored decision and
        raises no new review card."""
        tmp = tempfile.mkdtemp()
        app = create_review_api_app(
            artifact_root=Path(tmp) / "sessions",
            max_conversation_turns=2,
        )
        client = TestClient(app)
        session_id = "dir-compaction-session"
        prepared = client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": "E06V01-VER.EX01.xml",
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        assert prepared.status_code == 200, prepared.text

        review = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION},
        ).json()["direction_review"]
        confirmed = client.post(
            f"/api/review/sessions/{session_id}/direction-reviews",
            json={
                "question": INFERRED_QUESTION,
                "decision": "confirm",
                "review_key": review["review_key"],
            },
        ).json()
        self.assertEqual(confirmed["status"], "answered")
        conversation = confirmed["conversation_state"]

        # Drive the conversation past the compaction threshold.
        for question in ("Any valves?", "What about the pump?"):
            body = client.post(
                f"/api/review/sessions/{session_id}/qa-turns",
                json={"question": question, "conversation": conversation},
            ).json()
            conversation = body["conversation_state"]
            self.assertLessEqual(len(conversation), 2)

        # Re-asking the inferred question resumes with the stored annotation and
        # never raises a fresh review card, proving the decision survived.
        again = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": INFERRED_QUESTION, "conversation": conversation},
        ).json()
        self.assertEqual(again["status"], "answered")
        self.assertEqual(again["direction"]["review_status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
