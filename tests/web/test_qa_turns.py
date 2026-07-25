"""
Integration tests for the POST /api/review/sessions/{id}/qa-turns endpoint.

Boundary: HTTP endpoint with E06 DEXPI 1.3 fixture and scripted QA provider.
Tests assert the answer payload shape and structural witness properties,
not tool call counts or internal message formats.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pydexpi_datalog.qa.grounded_qa_harness import (
    FinalAnswer,
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

    def test_template_backed_answer_payload_discloses_logic_program(self) -> None:
        """When a bundled template executed, the answered payload carries the
        route artifact including the exact logic the engine ran, so a client
        can show the user the answer is provably derived -- and a turn without
        a template execution carries no route artifact at all."""
        if shutil.which("souffle") is None:
            self.skipTest("souffle engine not on PATH")

        class TemplateProvider:
            def __init__(self) -> None:
                self.calls = 0

            def complete_with_tools(self, *, messages, tools):
                self.calls += 1
                if self.calls == 1:
                    return ToolCall(
                        tool_name="execute_bundled_query_template",
                        tool_input={
                            "request": (
                                "Find every major process equipment item with no "
                                "piping path to any pump"
                            ),
                            "template_id": "equipment_without_pump_path",
                            "bindings": {
                                "pump_classes": ["CentrifugalPump"],
                                "equipment_classes": ["PlateHeatExchanger"],
                                "scope": "piping",
                                "direction": "undirected",
                                "quantifier": "every",
                                "negated": True,
                            },
                        },
                        tool_call_id="template-call-1",
                    )
                return FinalAnswer(answer_text="All equipment reaches a pump.")

        with tempfile.TemporaryDirectory() as tmp:
            app = create_review_api_app(
                artifact_root=Path(tmp) / "sessions",
                qa_provider_factory=TemplateProvider,
            )
            client = TestClient(app)
            session_id = "qa-template-logic-session"
            client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            body = client.post(
                f"/api/review/sessions/{session_id}/qa-turns",
                json={"question": "Which equipment has no piping path to a pump?"},
            ).json()

            self.assertEqual(body["status"], "answered")
            route_artifact = body["route_artifact"]
            self.assertEqual(route_artifact["route"], "bundled_template")
            logic_program = route_artifact["logic_program"]
            self.assertIn(
                'template_pump(N) :- node_label(N, "CentrifugalPump").',
                logic_program,
            )
            self.assertIn(
                "result_witness(T) :- template_equipment(T), !template_hit(T).",
                logic_program,
            )

    def test_answer_without_template_execution_has_no_route_artifact(self) -> None:
        """No deterministic route ran: the payload must not fabricate one."""
        body = self.client.post(
            f"/api/review/sessions/{self.session_id}/qa-turns",
            json={"question": "What equipment is in this PID?"},
        ).json()
        self.assertEqual(body["status"], "answered")
        self.assertNotIn("route_artifact", body)

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


class QAConversationCompactionTests(unittest.TestCase):
    """Long conversations are compacted server-side without losing grounding, and
    a follow-up asked after the compaction threshold stays grounded."""

    def _prepare(self, max_conversation_turns: int) -> tuple[TestClient, str]:
        tmp_path = Path(tempfile.mkdtemp())
        app = create_review_api_app(
            artifact_root=tmp_path / "sessions",
            max_conversation_turns=max_conversation_turns,
        )
        client = TestClient(app)
        session_id = "qa-compaction-session"
        prepared = client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": "E06V01-VER.EX01.xml",
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        assert prepared.status_code == 200, prepared.text
        return client, session_id

    def test_conversation_state_is_bounded_and_follow_up_stays_grounded(self) -> None:
        client, session_id = self._prepare(max_conversation_turns=2)

        # Turn 1 establishes grounded evidence identities.
        first = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": "What is reachable from the nozzle?"},
        ).json()
        prior_ids = first["evidence_references"]
        self.assertTrue(prior_ids)
        conversation = first["conversation_state"]

        # Several more turns push the history past the compaction threshold.
        for question in ("Any valves?", "What about the pump?"):
            body = client.post(
                f"/api/review/sessions/{session_id}/qa-turns",
                json={"question": question, "conversation": conversation},
            ).json()
            conversation = body["conversation_state"]
            # The backend keeps the carried conversation bounded to the threshold.
            self.assertLessEqual(len(conversation), 2)

        # A follow-up after compaction still resolves against a prior identity.
        follow_up = client.post(
            f"/api/review/sessions/{session_id}/qa-turns",
            json={"question": "What is reachable from those?", "conversation": conversation},
        ).json()
        self.assertEqual(follow_up["status"], "answered")
        self.assertTrue(
            set(follow_up["interpreted_object_ids"]) & set(prior_ids),
            "post-compaction follow-up should reuse a prior evidence identity",
        )


class ForceScriptedProviderTests(unittest.TestCase):
    """PYDEXPI_QA_PROVIDER=scripted forces the deterministic provider even when a
    session has ollama provider-settings configured, so the e2e stack never makes
    a real LLM call. Regression for turns timing out on a live model."""

    def test_scripted_flag_overrides_configured_ollama_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, mock.patch.dict(
            os.environ, {"PYDEXPI_QA_PROVIDER": "scripted"}
        ), mock.patch(
            "pydexpi_datalog.web.review_api.OllamaQATurnProvider",
            side_effect=AssertionError("ollama provider must not be constructed"),
        ):
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            session_id = "force-scripted-session"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            assert prepared.status_code == 200, prepared.text

            # Configure a real ollama provider on the session.
            configured = client.put(
                f"/api/review/sessions/{session_id}/provider-settings",
                json={
                    "provider": "ollama",
                    "model": "ornith:35b",
                    "credential": "",
                    "base_url": "http://localhost:11434/v1",
                },
            )
            assert configured.status_code == 200, configured.text

            # Turn resolves via the scripted provider (patched Ollama would raise).
            turn = client.post(
                f"/api/review/sessions/{session_id}/turns",
                json={
                    "question": "What downstream process objects are reachable from the pump?",
                    "request_id": "force-1",
                },
            )
            self.assertEqual(turn.status_code, 200, turn.text)
            body = turn.json()
            self.assertEqual(body["status"], "completed")
            event_types = [e["type"] for e in body["events"]]
            self.assertIn("completion", event_types)


class OpenRouterProviderRoutingTests(unittest.TestCase):
    """Regression for a session configured with an OpenAI-compatible BYOK
    provider (e.g. openrouter) silently answering via the deterministic
    ScriptedQATurnProvider instead of actually calling the model. Only the
    ollama branch used to be wired into turn resolution; any other BYOK
    provider fell through to the stub even though provider-settings accepted
    it."""

    def test_configured_openrouter_provider_is_actually_called(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, mock.patch(
            "httpx.post"
        ) as mock_post:
            mock_post.return_value.raise_for_status = mock.Mock()
            mock_post.return_value.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "provide_answer",
                                        "arguments": '{"answer_text": "From OpenRouter."}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }

            # Routing is this test's subject, so it opts out of the scripted
            # hermeticity switch. httpx.post is mocked above: no real call.
            app = create_review_api_app(
                artifact_root=Path(tmp_dir) / "sessions",
                force_scripted_provider=False,
            )
            client = TestClient(app)
            session_id = "openrouter-session"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            assert prepared.status_code == 200, prepared.text

            configured = client.put(
                f"/api/review/sessions/{session_id}/provider-settings",
                json={
                    "provider": "openrouter",
                    "model": "anthropic/claude-sonnet-4",
                    "credential": "sk-or-test-key",
                },
            )
            assert configured.status_code == 200, configured.text

            turn = client.post(
                f"/api/review/sessions/{session_id}/turns",
                json={"question": "What equipment is here?", "request_id": "or-1"},
            )
            self.assertEqual(turn.status_code, 200, turn.text)
            body = turn.json()
            self.assertEqual(body["result"]["answer_text"], "From OpenRouter.")

            mock_post.assert_called()
            call_url = mock_post.call_args[0][0]
            self.assertIn("openrouter.ai", call_url)
            call_headers = mock_post.call_args[1]["headers"]
            self.assertEqual(call_headers["Authorization"], "Bearer sk-or-test-key")

class ScriptedHermeticitySwitchTests(unittest.TestCase):
    """Test hermeticity guard: PYDEXPI_QA_PROVIDER=scripted forces the
    deterministic zero-LLM provider so an e2e stack exercises the real turn
    transport without a real model call.

    Provider routing is the one subject that switch overrides, so
    OpenRouterProviderRoutingTests opts out with force_scripted_provider=False.
    This guard pins the other side: the opt-out must not weaken the default for
    anything else (bead pydexpi-datalog-1-hzgb)."""

    def _configured_session(self, app: object) -> TestClient:
        client = TestClient(app)
        prepared = client.post(
            "/api/review/sessions/hermeticity-session/prepare",
            json={
                "filename": "E06V01-VER.EX01.xml",
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        self.assertEqual(prepared.status_code, 200, prepared.text)
        configured = client.put(
            "/api/review/sessions/hermeticity-session/provider-settings",
            json={
                "provider": "openrouter",
                "model": "anthropic/claude-sonnet-4",
                "credential": "sk-or-test-key",
            },
        )
        self.assertEqual(configured.status_code, 200, configured.text)
        return client

    def test_switch_overrides_a_configured_provider_by_default(self) -> None:
        """Hermeticity holds: a configured BYOK session still reaches no model."""
        with tempfile.TemporaryDirectory() as tmp_dir, mock.patch(
            "httpx.post"
        ) as mock_post, mock.patch.dict(
            os.environ, {"PYDEXPI_QA_PROVIDER": "scripted"}
        ):
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = self._configured_session(app)
            turn = client.post(
                "/api/review/sessions/hermeticity-session/turns",
                json={"question": "What equipment is here?", "request_id": "h-1"},
            )
            self.assertEqual(turn.status_code, 200, turn.text)
            mock_post.assert_not_called()
