from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from hosted_env import fetch_download_url, fresh_principal

from pydexpi_datalog.web.review_api import (
    TopologyAwareFakeModelProvider,
    create_review_api_app,
)
from pydexpi_datalog.workflow.review_session import PreparationLimits

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class ReviewApiTests(unittest.TestCase):
    def test_provider_settings_endpoint_accepts_explicit_byok_providers(self) -> None:
        sentinel = "sk-sentinel-secret-should-never-leak"
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(principal=fresh_principal(), artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            session_id = "api-provider-session"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(prepared.status_code, 200)

            for provider, model in [
                ("openai", "gpt-4.1"),
                ("anthropic", "claude-sonnet-4-5"),
                ("gemini", "gemini-2.5-pro"),
                ("openrouter", "anthropic/claude-sonnet-4"),
            ]:
                with self.subTest(provider=provider):
                    response = client.put(
                        f"/api/review/sessions/{session_id}/provider-settings",
                        json={
                            "provider": provider,
                            "model": model,
                            "credential": sentinel,
                        },
                    )

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        response.json(),
                        {
                            "session_id": session_id,
                            "provider": provider,
                            "model": model,
                            "configured": True,
                        },
                    )
                    self.assertNotIn(sentinel, response.text)

    def test_provider_settings_endpoint_rejects_non_tool_capable_model(self) -> None:
        sentinel = "sk-sentinel-secret-should-never-leak"
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(principal=fresh_principal(), artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            session_id = "api-provider-tool-gate"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(prepared.status_code, 200)

            response = client.put(
                f"/api/review/sessions/{session_id}/provider-settings",
                json={
                    "provider": "openai",
                    "model": "gpt-3.5-turbo-instruct",
                    "credential": sentinel,
                },
            )

            self.assertEqual(response.status_code, 400)
            detail = response.json()["error"]
            self.assertEqual(detail["code"], "request.invalid")
            self.assertIn("native tool", detail["message"])
            self.assertNotIn(sentinel, response.text)

    def test_http_api_runs_review_workflow_without_exposing_credentials(self) -> None:
        sentinel = "sk-sentinel-secret-should-never-leak"
        session_id = "api-e06-session"
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(principal=fresh_principal(), 
                artifact_root=Path(tmp_dir) / "sessions",
                model_provider_factory=TopologyAwareFakeModelProvider,
            )
            client = TestClient(app)

            def request(
                method: str, path: str, body: dict[str, object] | None = None
            ) -> tuple[int, dict[str, object]]:
                response = client.request(method, path, json=body or {})
                return response.status_code, response.json()

            not_ready_status, not_ready = request(
                "POST",
                f"/api/review/sessions/{session_id}/logic-requests/improve",
                {"prompt": "What process equipment is connected in this P&ID?"},
            )

            self.assertEqual(not_ready_status, 409)
            self.assertEqual(not_ready["error"]["code"], "session.not_ready")

            list_before_status, packs_before = request(
                "GET", f"/api/review/sessions/{session_id}/rule-packs"
            )
            self.assertEqual(list_before_status, 200)
            self.assertFalse(packs_before["packs"][0]["loaded"])

            all_packs_status, all_packs = request("GET", "/api/rule-packs")
            self.assertEqual(all_packs_status, 200)
            self.assertNotIn("session_id", all_packs)
            self.assertEqual(
                all_packs["packs"][0]["pack_id"], packs_before["packs"][0]["pack_id"]
            )
            self.assertNotIn("loaded", all_packs["packs"][0])
            self.assertIn("advisory_guidance", all_packs["packs"][0])
            self.assertIsInstance(all_packs["packs"][0]["advisory_guidance"], list)
            # The pack's canonical markdown source travels with the
            # session-independent payload (document-style detail page).
            self.assertIn("```souffle-datalog", all_packs["packs"][0]["markdown"])

            prepare_status, prepared = request(
                "POST",
                f"/api/review/sessions/{session_id}/prepare",
                {
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )

            self.assertEqual(prepare_status, 200)
            self.assertEqual(prepared["status"], "ready")
            self.assertEqual(prepared["session_id"], session_id)
            self.assertEqual(prepared["query_controls"], {"enabled": True})
            self.assertTrue(prepared["topology_view"]["nodes"])
            topology_id = prepared["topology_view"]["nodes"][0]["id"]

            scope_status, scope = request(
                "PUT",
                f"/api/review/sessions/{session_id}/source-scope",
                {"source_scope_ids": [topology_id]},
            )
            self.assertEqual(scope_status, 200)
            self.assertEqual(scope["visible_source_scope"]["ids"], [topology_id])

            provider_status, provider = request(
                "PUT",
                f"/api/review/sessions/{session_id}/provider-settings",
                {
                    "provider": "openrouter",
                    "model": "anthropic/claude-sonnet-4",
                    "credential": sentinel,
                },
            )
            self.assertEqual(provider_status, 200)
            self.assertEqual(
                provider,
                {
                    "session_id": session_id,
                    "provider": "openrouter",
                    "model": "anthropic/claude-sonnet-4",
                    "configured": True,
                },
            )

            improve_status, improvement = request(
                "POST",
                f"/api/review/sessions/{session_id}/logic-requests/improve",
                {
                    "prompt": "Starting from this selected object, what downstream process objects are reachable?",
                },
            )
            self.assertEqual(improve_status, 200)
            self.assertEqual(improvement["status"], "refinement_ready")

            confirm_status, confirmation = request(
                "POST",
                f"/api/review/sessions/{session_id}/logic-requests/confirm",
                {"improvement": improvement},
            )
            self.assertEqual(confirm_status, 200)
            self.assertEqual(confirmation["status"], "confirmation_ready")
            self.assertEqual(confirmation["primary_confirmation"], "restatement")

            execute_status, answer = request(
                "POST",
                f"/api/review/sessions/{session_id}/logic-requests/execute",
                {"confirmation": confirmation},
            )
            self.assertEqual(execute_status, 200)
            self.assertEqual(answer["status"], "answered")
            self.assertTrue(answer["evidence"]["items"])
            self.assertTrue(answer["evidence_highlight"]["matched_object_ids"])

            rule_status, rule_result = request(
                "POST",
                f"/api/review/sessions/{session_id}/rule-pack-results",
                {"rule_id": "pump_discharge_check_valve"},
            )
            self.assertEqual(rule_status, 200)
            self.assertEqual(rule_result["status"], "answered")
            self.assertEqual(rule_result["confirmation"], {"required": False})

            load_unknown_status, load_unknown = request(
                "POST",
                f"/api/review/sessions/{session_id}/rule-packs/not-a-real-pack/load",
            )
            self.assertEqual(load_unknown_status, 400)
            self.assertEqual(load_unknown["error"]["code"], "request.invalid")

            load_status, load_result = request(
                "POST",
                f"/api/review/sessions/{session_id}/rule-packs/demo-process-safety/load",
            )
            self.assertEqual(load_status, 200)
            self.assertEqual(load_result["loaded"], True)

            list_after_status, packs_after = request(
                "GET", f"/api/review/sessions/{session_id}/rule-packs"
            )
            self.assertEqual(list_after_status, 200)
            self.assertTrue(packs_after["packs"][0]["loaded"])

            run_status, run_result = request(
                "POST",
                f"/api/review/sessions/{session_id}/rule-packs/demo-process-safety/run",
            )
            self.assertEqual(run_status, 200)
            self.assertEqual(run_result["status"], "answered")
            self.assertEqual(run_result["confirmation"], {"required": False})
            self.assertEqual(len(run_result["results"]), 2)
            self.assertEqual(
                [item["rule_id"] for item in run_result["results"]],
                ["pump_discharge_check_valve", "discharge_line_min_diameter"],
            )
            run_item = run_result["results"][0]
            self.assertIn(
                run_item["outcome"], {"satisfied", "violated", "indeterminate"}
            )
            self.assertTrue(run_item["evidence"]["items"])

            export_status, export = request(
                "POST",
                f"/api/review/sessions/{session_id}/exports",
                {},
            )
            self.assertEqual(export_status, 200)
            self.assertEqual(export["status"], "exported")
            # Fetched through the advertised URL, which is a `file://` URL
            # locally and a presigned object-store URL when hosted -- in
            # neither case do the bytes pass through the API (bead 2afe.8).
            manifest = json.loads(fetch_download_url(str(export["manifest_path"])))
            self.assertTrue(manifest)
            self.assertEqual(len(export["manifest"]["logic_request_results"]), 1)
            self.assertEqual(len(export["manifest"]["rule_pack_results"]), 3)

            response_text = json.dumps(
                [
                    not_ready,
                    prepared,
                    scope,
                    provider,
                    improvement,
                    confirmation,
                    answer,
                    rule_result,
                    export,
                ],
                sort_keys=True,
            )
            self.assertEqual(response_text.count(sentinel), 0)

    def test_chat_accepts_multiple_distinct_sources(self) -> None:
        session_id = "api-single-source"
        e03_fixture = (
            REPO_ROOT
            / "TrainingTestCases"
            / "dexpi 1.3"
            / "example pids"
            / "E03 Pump With Nozzles"
            / "E03V01-VER.EX01.xml"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(principal=fresh_principal(), artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)

            first = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(first.status_code, 200)
            first_body = first.json()
            self.assertEqual(first_body["status"], "ready")
            self.assertTrue(first_body["source_id"].startswith("source-"))
            pipeline_metrics = first_body["timing"]["pipeline"]
            self.assertEqual(
                pipeline_metrics["counts"]["request_content_bytes"],
                len(E06_FIXTURE.read_text(encoding="utf-8").encode("utf-8")),
            )
            self.assertGreaterEqual(
                pipeline_metrics["phases_ms"]["upload_store"],
                0,
            )
            self.assertGreaterEqual(
                pipeline_metrics["total_ms"],
                sum(pipeline_metrics["phases_ms"].values()),
            )

            # A second, different source becomes the active source for the chat.
            second = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E03V01-VER.EX01.xml",
                    "content": e03_fixture.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(second.status_code, 200)
            second_body = second.json()
            self.assertEqual(second_body["status"], "ready")
            self.assertNotEqual(second_body["source_id"], first_body["source_id"])

            # Topology queries now resolve against the most recently prepared source.
            topology = client.get(f"/api/review/sessions/{session_id}/topology")
            self.assertEqual(topology.status_code, 200)
            self.assertTrue(topology.json()["graph_objects"])

    def test_configured_preparation_limit_is_enforced_through_http(self) -> None:
        session_id = "api-limit"
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(principal=fresh_principal(), 
                artifact_root=Path(tmp_dir) / "sessions",
                preparation_limits=PreparationLimits(max_upload_bytes=64),
            )
            client = TestClient(app)
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            ).json()
            self.assertEqual(prepared["status"], "failed")
            self.assertEqual(
                prepared["diagnostics"][0]["code"], "limit.upload_bytes_exceeded"
            )

    def test_prepare_response_exposes_source_id_for_provenance(self) -> None:
        session_id = "api-source-id"
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(principal=fresh_principal(), artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            ).json()
            self.assertEqual(prepared["status"], "ready")
            self.assertEqual(
                prepared["source_id"], prepared["topology_view"]["source_id"]
            )


if __name__ == "__main__":
    unittest.main()
