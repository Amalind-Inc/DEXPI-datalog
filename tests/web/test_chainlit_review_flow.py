from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pydexpi_datalog import FakeModelProvider
from pydexpi_datalog.web.chainlit_review_flow import ChainlitReviewFlow


REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)
ACCEPTANCE_DOCUMENTS = [
    (
        "c01-reference-pid",
        REPO_ROOT
        / "TrainingTestCases"
        / "dexpi 1.3"
        / "example pids"
        / "C01 DEXPI Reference P&ID"
        / "C01V04-VER.EX01.xml",
    ),
    (
        "c02-process-column-basf",
        REPO_ROOT
        / "TrainingTestCases"
        / "dexpi 1.3"
        / "example pids"
        / "C02 Process Column (BASF)"
        / "C02V03-VER.EX02.xml",
    ),
    (
        "c03-piping-equinor",
        REPO_ROOT
        / "TrainingTestCases"
        / "dexpi 1.3"
        / "example pids"
        / "C03 Piping (Equinor)"
        / "C03V04-VER.EX02.xml",
    ),
    ("e06-pump-heat-exchanger-pns", E06_FIXTURE),
    (
        "i06-flow-control-valve",
        REPO_ROOT
        / "TrainingTestCases"
        / "dexpi 1.3"
        / "example pids"
        / "I06 CCR flow indication and high alarm, flow control, control valve"
        / "I06V01-VER.EX01.xml",
    ),
    (
        "p04-pipe-intersection",
        REPO_ROOT
        / "TrainingTestCases"
        / "dexpi 1.3"
        / "example pids"
        / "P04 Pipe With Intersection"
        / "P04V01-VER.EX01.xml",
    ),
    (
        "e03-pump-incomplete-review",
        REPO_ROOT
        / "TrainingTestCases"
        / "dexpi 1.3"
        / "example pids"
        / "E03 Pump With Nozzles"
        / "E03V01-VER.EX01.xml",
    ),
]


class FakeClock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        current = self.now
        self.now += 0.25
        return current


class ChainlitReviewFlowTests(unittest.TestCase):
    def test_upload_acceptance_document_reaches_ready_and_enables_query_controls(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )

            initial_state = flow.initial_state()
            self.assertEqual(initial_state["status"], "awaiting_upload")
            self.assertEqual(initial_state["query_controls"]["enabled"], False)

            preparing_state = flow.preparing_state(session_id="chainlit-e06")
            self.assertEqual(preparing_state["status"], "preparing")
            self.assertEqual(preparing_state["query_controls"]["enabled"], False)
            self.assertEqual(preparing_state["prompt_composer"]["enabled"], False)

            state = flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="chainlit-e06",
            )

            self.assertEqual(state["status"], "ready")
            self.assertEqual(state["session_id"], "chainlit-e06")
            self.assertEqual(state["query_controls"], {"enabled": True})
            self.assertEqual(state["prompt_composer"]["enabled"], True)
            self.assertGreater(state["timing"]["upload_to_ready_seconds"], 0)
            self.assertEqual(state["timing"]["document_id"], "chainlit-e06")
            self.assertTrue(state["topology_view"]["nodes"])

    def test_failed_upload_keeps_query_controls_disabled_and_retry_can_reach_ready(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            flow = ChainlitReviewFlow(
                artifact_root=tmp_path / "sessions",
                clock=FakeClock(),
            )
            missing_xml = tmp_path / "later.xml"

            failed = flow.prepare_upload(
                dexpi_xml_path=missing_xml,
                session_id="retryable",
            )

            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["query_controls"]["enabled"], False)
            self.assertEqual(failed["prompt_composer"]["enabled"], False)
            self.assertEqual(failed["diagnostics"][0]["code"], "upload.missing_file")

            shutil.copyfile(E06_FIXTURE, missing_xml)
            retried = flow.retry_upload(session_id="retryable")

            self.assertEqual(retried["status"], "ready")
            self.assertEqual(retried["query_controls"], {"enabled": True})
            self.assertEqual(retried["prompt_composer"]["enabled"], True)
            self.assertEqual(retried["timing"]["document_id"], "retryable")

    def test_upload_to_ready_timing_is_recorded_for_each_acceptance_document(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )

            for session_id, dexpi_xml_path in ACCEPTANCE_DOCUMENTS:
                with self.subTest(session_id=session_id):
                    state = flow.prepare_upload(
                        dexpi_xml_path=dexpi_xml_path,
                        session_id=session_id,
                    )

                    self.assertEqual(state["status"], "ready")
                    self.assertEqual(state["timing"]["document_id"], session_id)
                    self.assertGreater(state["timing"]["upload_to_ready_seconds"], 0)
                    topology_node_ids = {
                        node["id"] for node in state["topology_view"]["nodes"]
                    }
                    panel = flow.topology_panel_state(session_id=session_id)
                    selectable_node_ids = {
                        item["id"]
                        for item in panel["graph_objects"]
                        if item["kind"] == "node" and item["selectable"]
                    }
                    self.assertGreaterEqual(
                        len(selectable_node_ids & topology_node_ids)
                        / len(topology_node_ids),
                        0.95,
                    )

            self.assertEqual(
                {item["document_id"] for item in flow.timing_records()},
                {session_id for session_id, _ in ACCEPTANCE_DOCUMENTS},
            )

    def test_topology_selection_updates_visible_editable_source_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            state = flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="selection-session",
            )
            topology_node_ids = [node["id"] for node in state["topology_view"]["nodes"]]

            panel = flow.topology_panel_state(session_id="selection-session")
            selectable_node_ids = [
                item["id"]
                for item in panel["graph_objects"]
                if item["kind"] == "node" and item["selectable"]
            ]
            self.assertGreaterEqual(
                len(selectable_node_ids) / len(topology_node_ids),
                0.95,
            )

            selected = flow.select_topology_object(
                session_id="selection-session",
                topology_id=topology_node_ids[0],
                latency_target_seconds=0.3,
            )
            self.assertEqual(
                selected["visible_source_scope"]["ids"],
                [topology_node_ids[0]],
            )
            self.assertLessEqual(
                selected["selection_latency_seconds"],
                selected["latency_target_seconds"],
            )

            edited = flow.edit_visible_source_scope(
                session_id="selection-session",
                source_scope_ids=[topology_node_ids[1]],
            )
            self.assertEqual(
                edited["visible_source_scope"]["ids"],
                [topology_node_ids[1]],
            )

            removed = flow.remove_visible_source_scope(
                session_id="selection-session",
                topology_id=topology_node_ids[1],
            )
            self.assertEqual(removed["visible_source_scope"]["ids"], [])

    def test_logic_request_submission_uses_only_explicit_visible_source_scope(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            state = flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="submit-session",
            )
            topology_node_ids = [node["id"] for node in state["topology_view"]["nodes"]]

            flow.select_topology_object(
                session_id="submit-session",
                topology_id=topology_node_ids[0],
                latency_target_seconds=0.3,
            )
            flow.edit_visible_source_scope(
                session_id="submit-session",
                source_scope_ids=[topology_node_ids[1]],
            )

            submission = flow.build_logic_request_submission(
                session_id="submit-session",
                prompt="What is downstream of the visible scope?",
            )

            self.assertEqual(
                submission,
                {
                    "session_id": "submit-session",
                    "prompt": "What is downstream of the visible scope?",
                    "source_scope_ids": [topology_node_ids[1]],
                },
            )
            self.assertNotIn(topology_node_ids[0], submission["source_scope_ids"])

    def test_improve_routes_before_refinement_for_reviewable_and_unsupported_requests(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            state = flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="improve-session",
            )
            topology_id = state["topology_view"]["nodes"][0]["id"]

            whole_file = flow.improve_logic_request(
                session_id="improve-session",
                prompt="What process equipment is connected in this P&ID?",
            )

            self.assertEqual(whole_file["status"], "refinement_ready")
            self.assertEqual(whole_file["route"], {"kind": "topology_logic"})
            self.assertEqual(whole_file["refinement"]["scope"], {"kind": "whole_pid"})
            self.assertEqual(whole_file["refinement"]["source_scope_ids"], [])
            self.assertNotIn("generated_datalog", str(whole_file))

            flow.edit_visible_source_scope(
                session_id="improve-session",
                source_scope_ids=[topology_id],
            )
            selected_scope = flow.improve_logic_request(
                session_id="improve-session",
                prompt="Starting from this selected object, what downstream process objects are reachable?",
            )

            self.assertEqual(selected_scope["status"], "refinement_ready")
            self.assertEqual(selected_scope["route"], {"kind": "topology_logic"})
            self.assertEqual(
                selected_scope["refinement"]["scope"],
                {"kind": "visible_source_scope"},
            )
            self.assertEqual(
                selected_scope["refinement"]["source_scope_ids"],
                [topology_id],
            )
            self.assertNotIn("generated_datalog", str(selected_scope))

            unsupported = flow.improve_logic_request(
                session_id="improve-session",
                prompt="Calculate the pressure drop and required pump head for this line.",
            )

            self.assertEqual(unsupported["status"], "unsupported")
            self.assertEqual(unsupported["route"], {"kind": "missing_capability"})
            self.assertEqual(
                unsupported["missing_capability"]["code"],
                "logic_request.missing_capability",
            )
            self.assertIn(
                "Calculate the pressure drop",
                unsupported["missing_capability"]["copyable_text"],
            )
            self.assertEqual(
                unsupported["missing_capability"]["download"]["filename"],
                "improve-session-missing-capability.txt",
            )
            self.assertNotIn("refinement", unsupported)
            self.assertNotIn("generated_datalog", str(unsupported))

    def test_improve_routed_non_topology_requests_do_not_become_datalog_refinements(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="route-session",
            )

            for prompt, status, route in [
                (
                    "Explain the direct process connection predicate.",
                    "routed",
                    {"kind": "documentation_answer"},
                ),
                (
                    "Show the model and context policy used for this run.",
                    "routed",
                    {"kind": "metadata_lookup"},
                ),
                (
                    "Check this thing.",
                    "needs_clarification",
                    {"kind": "clarification"},
                ),
            ]:
                with self.subTest(route=route["kind"]):
                    result = flow.improve_logic_request(
                        session_id="route-session",
                        prompt=prompt,
                    )

                    self.assertEqual(result["status"], status)
                    self.assertEqual(result["route"], route)
                    self.assertNotIn("refinement", result)
                    self.assertNotIn("generated_datalog", str(result))

    def test_accepted_refinement_produces_restatement_first_confirmation_artifact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            state = flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="confirm-session",
            )
            topology_id = state["topology_view"]["nodes"][0]["id"]
            flow.configure_provider_settings(
                session_id="confirm-session",
                provider="openai",
                model="gpt-4.1",
                credential="sk-sentinel-secret-should-never-leak",
            )
            flow.edit_visible_source_scope(
                session_id="confirm-session",
                source_scope_ids=[topology_id],
            )
            improvement = flow.improve_logic_request(
                session_id="confirm-session",
                prompt="Starting from this selected object, what downstream process objects are reachable?",
            )
            provider = FakeModelProvider(
                response=json.dumps(
                    {
                        "generated_datalog": ".decl reachable(x:symbol)\n.output reachable\nreachable(\"P-4713\").",
                        "formal_restatement": "Return process objects reachable downstream from the selected object.",
                    }
                )
            )

            artifact = flow.accept_logic_request_refinement(
                session_id="confirm-session",
                improvement=improvement,
                provider=provider,
            )

            self.assertEqual(artifact["artifact_type"], "logic_request_confirmation")
            self.assertEqual(artifact["status"], "confirmation_ready")
            self.assertEqual(artifact["primary_confirmation"], "restatement")
            self.assertEqual(
                artifact["restatement"],
                {
                    "kind": "datalog_grounded_restatement",
                    "text": "Return process objects reachable downstream from the selected object.",
                    "grounded_by": "generated_logic",
                },
            )
            self.assertEqual(
                artifact["generated_logic"],
                {
                    "kind": "generated_datalog",
                    "language": "souffle_datalog",
                    "content": ".decl reachable(x:symbol)\n.output reachable\nreachable(\"P-4713\").",
                    "inspectable": True,
                    "editable": False,
                },
            )
            self.assertEqual(
                artifact["request"],
                {
                    "prompt": "Starting from this selected object, what downstream process objects are reachable?",
                    "route": {"kind": "topology_logic"},
                    "provider": {
                        "provider": "openai",
                        "model": "gpt-4.1",
                        "configured": True,
                    },
                    "scope": {"kind": "visible_source_scope"},
                    "source_scope_ids": [topology_id],
                },
            )
            self.assertEqual(
                artifact["direct_datalog_edit"],
                {
                    "available": False,
                    "rejection": {
                        "code": "generated_datalog.direct_edit_unavailable",
                        "message": "Generated Datalog is inspectable but direct editing is unavailable in OSS v1.",
                    },
                },
            )
            self.assertEqual(artifact["diagnostics"], [])
            self.assertNotIn("sk-sentinel-secret-should-never-leak", str(artifact))
            self.assertEqual(len(provider.requests), 1)

    def test_accepting_refinement_without_credentials_stops_before_provider_call(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="missing-credential-session",
            )
            improvement = flow.improve_logic_request(
                session_id="missing-credential-session",
                prompt="What process equipment is connected in this P&ID?",
            )
            provider = FakeModelProvider(response="should not be used")

            artifact = flow.accept_logic_request_refinement(
                session_id="missing-credential-session",
                improvement=improvement,
                provider=provider,
            )

            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(
                artifact["diagnostics"],
                [
                    {
                        "code": "model_access.missing_byok_credentials",
                        "message": "Configure a provider credential before accepting a refinement.",
                    }
                ],
            )
            self.assertEqual(provider.requests, [])

    def test_provider_settings_are_visible_without_exposing_local_credentials(
        self,
    ) -> None:
        sentinel = "sk-sentinel-secret-should-never-leak"
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="byok-session",
            )

            settings = flow.configure_provider_settings(
                session_id="byok-session",
                provider="openai",
                model="gpt-4.1",
                credential=sentinel,
            )

            self.assertEqual(
                settings,
                {
                    "session_id": "byok-session",
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "configured": True,
                },
            )
            self.assertEqual(flow.local_credential_for_test("byok-session"), sentinel)
            self.assertNotIn(sentinel, str(settings))
            self.assertNotIn(sentinel, str(flow.provider_settings_state("byok-session")))

    def test_provider_settings_accept_only_explicit_byok_providers(self) -> None:
        sentinel = "sk-sentinel-secret-should-never-leak"
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="providers-session",
            )

            for provider, model in [
                ("openai", "gpt-4.1"),
                ("anthropic", "claude-sonnet-4"),
                ("gemini", "gemini-2.5-pro"),
                ("openrouter", "anthropic/claude-sonnet-4"),
            ]:
                with self.subTest(provider=provider):
                    settings = flow.configure_provider_settings(
                        session_id="providers-session",
                        provider=provider,
                        model=model,
                        credential=sentinel,
                    )

                    self.assertEqual(settings["provider"], provider)
                    self.assertEqual(settings["model"], model)
                    self.assertEqual(settings["configured"], True)
                    self.assertNotIn(sentinel, str(settings))

            with self.assertRaisesRegex(ValueError, "unsupported model provider"):
                flow.configure_provider_settings(
                    session_id="providers-session",
                    provider="bedrock",
                    model="claude",
                    credential=sentinel,
                )

    def test_logic_request_audit_and_export_do_not_include_sentinel_credentials(
        self,
    ) -> None:
        sentinel = "sk-sentinel-secret-should-never-leak"
        with tempfile.TemporaryDirectory() as tmp_dir:
            flow = ChainlitReviewFlow(
                artifact_root=Path(tmp_dir) / "sessions",
                clock=FakeClock(),
            )
            state = flow.prepare_upload(
                dexpi_xml_path=E06_FIXTURE,
                session_id="audit-session",
            )
            topology_id = state["topology_view"]["nodes"][0]["id"]
            flow.configure_provider_settings(
                session_id="audit-session",
                provider="openai",
                model="gpt-4.1",
                credential=sentinel,
            )
            flow.edit_visible_source_scope(
                session_id="audit-session",
                source_scope_ids=[topology_id],
            )

            submission = flow.build_logic_request_submission(
                session_id="audit-session",
                prompt="What is downstream of this object?",
            )
            audit_record = flow.build_logic_request_audit_record(
                submission=submission,
            )
            export_bundle = flow.export_session_state(session_id="audit-session")

            self.assertEqual(
                audit_record["provider"],
                {"provider": "openai", "model": "gpt-4.1", "configured": True},
            )
            self.assertNotIn("credential", str(audit_record).lower())
            self.assertNotIn(sentinel, str(submission))
            self.assertNotIn(sentinel, str(audit_record))
            self.assertNotIn(sentinel, str(export_bundle))


if __name__ == "__main__":
    unittest.main()
