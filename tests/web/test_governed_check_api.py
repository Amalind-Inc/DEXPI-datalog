from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from hosted_env import fresh_principal

from pydexpi_datalog.web.review_api import (
    TopologyAwareFakeModelProvider,
    create_review_api_app,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class GovernedCheckApiTests(unittest.TestCase):
    def test_public_check_boundary_returns_portlog_owned_result_and_reuses_exact_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(
                principal=fresh_principal(),
                artifact_root=Path(tmp_dir) / "sessions",
                model_provider_factory=TopologyAwareFakeModelProvider,
            )
            client = TestClient(app)
            session_id = "governed-check-api"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": E06_FIXTURE.name,
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(prepared.status_code, 200, prepared.text)
            topology = client.get(f"/api/review/sessions/{session_id}/topology")
            self.assertEqual(topology.status_code, 200, topology.text)
            pump = next(
                node
                for node in topology.json()["topology_view"]["nodes"]
                if node.get("label") == "CentrifugalPump"
            )
            scope_entity_id = pump["source_graph_node_id"]

            first = client.post(
                f"/api/review/sessions/{session_id}/governed-checks",
                json={
                    "check_id": "pump_discharge_check_valve",
                    "scope_entity_id": scope_entity_id,
                },
            )
            self.assertEqual(first.status_code, 200, first.text)
            first_payload = first.json()
            result = first_payload["deterministic_result"]
            self.assertEqual(result["run_status"], "completed")
            self.assertIn(result["outcome"], {"satisfied", "violated", "indeterminate"})
            self.assertEqual(result["check_id"], "pump_discharge_check_valve")
            self.assertEqual(result["coverage"]["requested_entity_id"], scope_entity_id)
            self.assertIn(result["coverage"]["complete"], {True, False})
            self.assertEqual(
                result["source_attestation"]["revision"],
                result["document_preparation_digest"],
            )
            self.assertTrue(result["evidence"]["ordered_topology_ids"])
            self.assertEqual(first_payload["model_interpretation"], None)
            self.assertTrue(first_payload["result_artifact"]["path"])

            second = client.post(
                f"/api/review/sessions/{session_id}/governed-checks",
                json={
                    "check_id": "pump_discharge_check_valve",
                    "scope_entity_id": scope_entity_id,
                },
            )
            self.assertEqual(second.status_code, 200, second.text)
            self.assertTrue(second.json()["deterministic_result"]["cache_provenance"]["hit"])
            self.assertEqual(
                second.json()["deterministic_result"]["document_preparation_digest"],
                result["document_preparation_digest"],
            )

            invalid_scope = client.post(
                f"/api/review/sessions/{session_id}/governed-checks",
                json={
                    "check_id": "pump_discharge_check_valve",
                    "scope_entity_id": "not-a-pump",
                },
            )
            self.assertEqual(invalid_scope.status_code, 400)
            self.assertIn("scope.invalid", invalid_scope.text)

            unknown_check = client.post(
                f"/api/review/sessions/{session_id}/governed-checks",
                json={
                    "check_id": "arbitrary_datalog",
                    "scope_entity_id": scope_entity_id,
                },
            )
            self.assertEqual(unknown_check.status_code, 400)
            self.assertIn("check.invalid", unknown_check.text)
