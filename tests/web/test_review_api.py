from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from pydexpi_datalog.web.review_api import TopologyAwareFakeModelProvider, create_review_api_app
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
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
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
                ("anthropic", "claude-sonnet-4"),
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
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
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
            app = create_review_api_app(
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

            export_status, export = request(
                "POST",
                f"/api/review/sessions/{session_id}/exports",
                {},
            )
            self.assertEqual(export_status, 200)
            self.assertEqual(export["status"], "exported")
            self.assertTrue(Path(str(export["manifest_path"])).exists())
            self.assertEqual(len(export["manifest"]["logic_request_results"]), 1)
            self.assertEqual(len(export["manifest"]["rule_pack_results"]), 1)

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

    def test_chat_accepts_one_source_and_rejects_a_second_distinct_source(self) -> None:
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
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
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

            # A second, different source for the same chat is rejected.
            second = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E03V01-VER.EX01.xml",
                    "content": e03_fixture.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(second.status_code, 200)
            second_body = second.json()
            self.assertEqual(second_body["status"], "failed")
            self.assertEqual(
                second_body["diagnostics"][0]["code"], "source.already_prepared"
            )

            # The originally prepared source still answers topology queries.
            topology = client.get(f"/api/review/sessions/{session_id}/topology")
            self.assertEqual(topology.status_code, 200)
            self.assertTrue(topology.json()["graph_objects"])

    def test_configured_preparation_limit_is_enforced_through_http(self) -> None:
        session_id = "api-limit"
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(
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
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
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
