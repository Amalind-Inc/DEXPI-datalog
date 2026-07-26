from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from hosted_env import path_from_download_url

from pydexpi_datalog.workflow.artifact_store import LocalArtifactStore
from pydexpi_datalog.workflow.review_session import (
    ReviewSessionService,
    build_evidence_highlight_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
E03_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E03 Pump With Nozzles"
    / "E03V01-VER.EX01.xml"
)
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
    ("e03-pump-incomplete-review", E03_FIXTURE),
]


class ReviewSessionServiceTests(unittest.TestCase):
    def test_prepare_review_session_acceptance_documents_all_reach_ready_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ReviewSessionService(store=LocalArtifactStore(Path(tmp_dir) / "sessions"))

            for session_id, dexpi_xml_path in ACCEPTANCE_DOCUMENTS:
                with self.subTest(session_id=session_id):
                    result = service.start_preparation(
                        dexpi_xml_path=dexpi_xml_path,
                        session_id=session_id,
                    )

                    self.assertEqual(result["job"]["status"], "succeeded")
                    self.assertEqual(result["readiness"]["state"], "ready")
                    self.assertTrue(result["topology_view"]["nodes"])
                    for artifact_name in (
                        "graph_facts_json",
                        "graph_facts_datalog",
                        "derived_graph_semantics_datalog",
                    ):
                        self.assertTrue(
                            path_from_download_url(
                                result["artifacts"][artifact_name]
                            ).exists(),
                            artifact_name,
                        )

    def test_prepare_review_session_reports_pipeline_timings_and_payload_counts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ReviewSessionService(store=LocalArtifactStore(Path(tmp_dir) / "sessions"))

            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE,
                session_id="timing-contract",
            )

            metrics = result["metrics"]
            self.assertEqual(metrics["schema_version"], 1)
            self.assertEqual(metrics["counts"]["upload_bytes"], E06_FIXTURE.stat().st_size)
            self.assertEqual(metrics["counts"]["graph_nodes"], 18)
            self.assertEqual(metrics["counts"]["graph_edges"], 21)
            self.assertGreater(metrics["counts"]["topology_bytes"], 0)
            self.assertGreater(metrics["counts"]["artifact_bytes"], 0)
            self.assertEqual(
                set(metrics["phases_ms"]),
                {
                    "xml_parse",
                    "graph_extraction",
                    "graph_artifact_write",
                    "graph_datalog",
                    "derived_semantics",
                    "topology_scene",
                    "topology_artifact_write",
                },
            )
            for elapsed_ms in metrics["phases_ms"].values():
                self.assertGreaterEqual(elapsed_ms, 0)
            self.assertGreaterEqual(
                metrics["total_ms"],
                sum(metrics["phases_ms"].values()),
            )

    def test_topology_view_contract_resolves_all_ids_for_evidence_highlighting(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ReviewSessionService(store=LocalArtifactStore(Path(tmp_dir) / "sessions"))

            for session_id, dexpi_xml_path in ACCEPTANCE_DOCUMENTS:
                with self.subTest(session_id=session_id):
                    result = service.start_preparation(
                        dexpi_xml_path=dexpi_xml_path,
                        session_id=session_id,
                    )

                    topology = result["topology_view"]
                    evidence_map = topology["evidence_map"]
                    topology_ids = {node["id"] for node in topology["nodes"]} | {
                        edge["id"] for edge in topology["edges"]
                    }

                    self.assertTrue(topology_ids)
                    self.assertEqual(topology_ids, set(evidence_map))
                    self.assertEqual(
                        topology["evidence_highlight"],
                        {
                            "source_scope_ids": [],
                            "matched_object_ids": [],
                            "paths": [],
                        },
                    )

                    for node in topology["nodes"]:
                        self.assertEqual(node["id"], node["canonical_fact_id"])
                        self.assertNotEqual(node["id"], node["source_graph_node_id"])

                        evidence_ref = evidence_map[node["id"]]
                        self.assertEqual(evidence_ref["kind"], "node")
                        self.assertEqual(evidence_ref["topology_id"], node["id"])
                        self.assertEqual(
                            evidence_ref["canonical_fact"],
                            {
                                "fact_type": "node",
                                "node_id": node["source_graph_node_id"],
                            },
                        )

                    for edge in topology["edges"]:
                        self.assertEqual(edge["id"], edge["canonical_fact_id"])

                        evidence_ref = evidence_map[edge["id"]]
                        self.assertEqual(evidence_ref["kind"], "edge")
                        self.assertEqual(evidence_ref["topology_id"], edge["id"])
                        self.assertEqual(
                            evidence_ref["canonical_fact"],
                            {
                                "fact_type": "edge",
                                "source_id": edge["source_graph_edge"]["source_id"],
                                "target_id": edge["source_graph_edge"]["target_id"],
                                "edge_key": edge["source_graph_edge"]["edge_key"],
                            },
                        )

    def test_evidence_highlight_payload_represents_scope_matches_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ReviewSessionService(store=LocalArtifactStore(Path(tmp_dir) / "sessions"))
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE,
                session_id="highlight-contract",
            )
            topology = result["topology_view"]
            source_node_id = topology["nodes"][0]["id"]
            matched_node_id = topology["nodes"][1]["id"]
            path_edge_id = topology["edges"][0]["id"]

            highlight = build_evidence_highlight_payload(
                topology_view=topology,
                source_scope_ids=[source_node_id],
                matched_object_ids=[matched_node_id],
                paths=[
                    {
                        "id": "path-1",
                        "node_ids": [source_node_id, matched_node_id],
                        "edge_ids": [path_edge_id],
                    }
                ],
            )

            self.assertEqual(highlight["source_scope_ids"], [source_node_id])
            self.assertEqual(highlight["matched_object_ids"], [matched_node_id])
            self.assertEqual(
                highlight["paths"],
                [
                    {
                        "id": "path-1",
                        "node_ids": [source_node_id, matched_node_id],
                        "edge_ids": [path_edge_id],
                    }
                ],
            )

            with self.assertRaisesRegex(ValueError, "unknown topology id"):
                build_evidence_highlight_payload(
                    topology_view=topology,
                    source_scope_ids=["missing-id"],
                    matched_object_ids=[],
                    paths=[],
                )

    def test_prepare_review_session_persists_artifacts_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir) / "sessions"
            service = ReviewSessionService(store=LocalArtifactStore(artifact_root))

            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE,
                session_id="session-e06",
            )

            self.assertEqual(result["session_id"], "session-e06")
            self.assertEqual(result["job"]["status"], "succeeded")
            self.assertEqual(result["readiness"]["state"], "ready")
            self.assertEqual(result["readiness"]["graph"]["node_count"], 18)
            self.assertEqual(result["readiness"]["graph"]["edge_count"], 21)
            self.assertEqual(result["diagnostics"], [])

            artifact_paths = result["artifacts"]
            for artifact_name in (
                "graph_facts_json",
                "graph_facts_datalog",
                "derived_graph_semantics_datalog",
                "readiness_metadata",
                "topology_view_model",
            ):
                self.assertTrue(
                    path_from_download_url(artifact_paths[artifact_name]).exists(),
                    artifact_name,
                )

            topology = result["topology_view"]
            self.assertEqual(topology["session_id"], "session-e06")
            self.assertTrue(topology["nodes"])
            self.assertTrue(topology["edges"])
            topology_node_ids = {node["id"] for node in topology["nodes"]}
            for edge in topology["edges"]:
                self.assertIn(edge["source_id"], topology_node_ids)
                self.assertIn(edge["target_id"], topology_node_ids)

            persisted_topology = json.loads(
                path_from_download_url(artifact_paths["topology_view_model"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(persisted_topology, topology)

    def test_prepare_review_session_has_stable_artifact_ids_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ReviewSessionService(store=LocalArtifactStore(Path(tmp_dir) / "sessions"))

            first = service.start_preparation(
                dexpi_xml_path=E03_FIXTURE,
                session_id="stable-one",
            )
            second = service.start_preparation(
                dexpi_xml_path=E03_FIXTURE,
                session_id="stable-two",
            )
            third = service.start_preparation(
                dexpi_xml_path=E03_FIXTURE,
                session_id="stable-three",
            )

            first_ids = [node["id"] for node in first["topology_view"]["nodes"]]
            self.assertEqual(first_ids, [node["id"] for node in second["topology_view"]["nodes"]])
            self.assertEqual(first_ids, [node["id"] for node in third["topology_view"]["nodes"]])

            first_edge_ids = [edge["id"] for edge in first["topology_view"]["edges"]]
            self.assertEqual(
                first_edge_ids,
                [edge["id"] for edge in second["topology_view"]["edges"]],
            )
            self.assertEqual(
                first_edge_ids,
                [edge["id"] for edge in third["topology_view"]["edges"]],
            )

    def test_retry_failed_preparation_reuses_session_and_input_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            service = ReviewSessionService(store=LocalArtifactStore(tmp_path / "sessions"))
            missing_xml = tmp_path / "later.xml"

            failed = service.start_preparation(
                dexpi_xml_path=missing_xml,
                session_id="retryable",
            )
            self.assertEqual(failed["job"]["status"], "failed")
            self.assertEqual(failed["diagnostics"][0]["code"], "upload.missing_file")

            shutil.copyfile(E03_FIXTURE, missing_xml)
            retried = service.retry_preparation(session_id="retryable")

            self.assertEqual(retried["session_id"], "retryable")
            self.assertEqual(retried["job"]["status"], "succeeded")
            self.assertEqual(retried["readiness"]["state"], "ready")

    def test_invalid_inputs_return_normalized_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            service = ReviewSessionService(store=LocalArtifactStore(tmp_path / "sessions"))

            non_xml = tmp_path / "not-a-pid.txt"
            non_xml.write_text("not xml", encoding="utf-8")
            non_xml_result = service.start_preparation(
                dexpi_xml_path=non_xml,
                session_id="non-xml",
            )
            self.assertEqual(non_xml_result["job"]["status"], "failed")
            self.assertEqual(non_xml_result["diagnostics"][0]["code"], "upload.non_xml")

            non_dexpi_xml = tmp_path / "not-dexpi.xml"
            non_dexpi_xml.write_text("<root><item /></root>", encoding="utf-8")
            non_dexpi_result = service.start_preparation(
                dexpi_xml_path=non_dexpi_xml,
                session_id="non-dexpi",
            )
            self.assertEqual(non_dexpi_result["job"]["status"], "failed")
            self.assertEqual(
                non_dexpi_result["diagnostics"][0]["code"],
                "upload.non_dexpi_xml",
            )

            malformed_xml = tmp_path / "malformed.xml"
            malformed_xml.write_text("<PlantModel>", encoding="utf-8")
            malformed_result = service.start_preparation(
                dexpi_xml_path=malformed_xml,
                session_id="malformed",
            )
            self.assertEqual(malformed_result["job"]["status"], "failed")
            self.assertEqual(
                malformed_result["diagnostics"][0]["code"],
                "upload.xml_parse_failed",
            )
            self.assertIn("raw_details", malformed_result["diagnostics"][0])


if __name__ == "__main__":
    unittest.main()
