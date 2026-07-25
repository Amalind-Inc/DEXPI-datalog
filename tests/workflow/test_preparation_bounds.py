"""
Behavioral contracts for bounding preparation of a single DEXPI source (37x.22.16).

Boundary: ReviewSessionService public API (start_preparation / retry_preparation)
and the validate_upload_input gate. Tests assert observable diagnostics, the
single-source lock, retryability, and source-id provenance — not internal calls.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hosted_env import path_from_download_url

from pydexpi_datalog.workflow.artifact_store import LocalArtifactStore
from pydexpi_datalog.workflow.review_session import (
    PreparationLimits,
    ReviewSessionService,
    compute_source_id,
    validate_upload_input,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PIDS = REPO_ROOT / "TrainingTestCases" / "dexpi 1.3" / "example pids"
E06_FIXTURE = (
    EXAMPLE_PIDS
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)
E03_FIXTURE = EXAMPLE_PIDS / "E03 Pump With Nozzles" / "E03V01-VER.EX01.xml"
C01_FIXTURE = EXAMPLE_PIDS / "C01 DEXPI Reference P&ID" / "C01V04-VER.EX01.xml"


class StepClock:
    """Deterministic clock returning successive values; repeats the last value."""

    def __init__(self, values: list[float]) -> None:
        self._values = values
        self._index = 0

    def __call__(self) -> float:
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return value


def _service(tmp_dir: str, **limit_overrides: object) -> ReviewSessionService:
    limits = PreparationLimits(**limit_overrides) if limit_overrides else None
    return ReviewSessionService(
        store=LocalArtifactStore(Path(tmp_dir) / "sessions"), limits=limits
    )


def _first_diag_code(result: dict) -> str:
    return result["diagnostics"][0]["code"]


class ConfigurableLimitTests(unittest.TestCase):
    def test_default_limits_accept_largest_bundled_dexpi_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir)
            result = service.start_preparation(
                dexpi_xml_path=C01_FIXTURE, session_id="c01"
            )
            self.assertEqual(result["readiness"]["state"], "ready")

    def test_upload_byte_limit_fails_with_explicit_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir, max_upload_bytes=64)
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="bytes"
            )
            self.assertEqual(result["job"]["status"], "failed")
            self.assertEqual(_first_diag_code(result), "limit.upload_bytes_exceeded")

    def test_xml_element_complexity_limit_fails_with_explicit_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir, max_xml_elements=5)
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="elements"
            )
            self.assertEqual(result["job"]["status"], "failed")
            self.assertEqual(_first_diag_code(result), "limit.xml_elements_exceeded")

    def test_xml_depth_complexity_limit_fails_with_explicit_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir, max_xml_depth=2)
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="depth"
            )
            self.assertEqual(result["job"]["status"], "failed")
            self.assertEqual(_first_diag_code(result), "limit.xml_depth_exceeded")

    def test_processing_time_limit_fails_with_explicit_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ReviewSessionService(
                store=LocalArtifactStore(Path(tmp_dir) / "sessions"),
                limits=PreparationLimits(max_preparation_seconds=1.0),
                clock=StepClock([0.0, 100.0]),
            )
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="time"
            )
            self.assertEqual(result["job"]["status"], "failed")
            self.assertEqual(
                _first_diag_code(result), "limit.preparation_time_exceeded"
            )

    def test_graph_node_limit_fails_with_explicit_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir, max_graph_nodes=1)
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="nodes"
            )
            self.assertEqual(result["job"]["status"], "failed")
            self.assertEqual(_first_diag_code(result), "limit.graph_nodes_exceeded")

    def test_graph_edge_limit_fails_with_explicit_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Node limit generous so the edge limit is what breaches.
            service = _service(tmp_dir, max_graph_nodes=10_000, max_graph_edges=1)
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="edges"
            )
            self.assertEqual(result["job"]["status"], "failed")
            self.assertEqual(_first_diag_code(result), "limit.graph_edges_exceeded")

    def test_artifact_size_limit_fails_with_explicit_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir, max_artifact_bytes=1)
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="artifacts"
            )
            self.assertEqual(result["job"]["status"], "failed")
            self.assertEqual(_first_diag_code(result), "limit.artifact_bytes_exceeded")


class SingleSourcePerChatTests(unittest.TestCase):
    def test_successful_preparation_prevents_a_second_distinct_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir)
            first = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="one-chat"
            )
            self.assertEqual(first["readiness"]["state"], "ready")

            second = service.start_preparation(
                dexpi_xml_path=E03_FIXTURE, session_id="one-chat"
            )
            self.assertEqual(second["job"]["status"], "failed")
            self.assertEqual(_first_diag_code(second), "source.already_prepared")

    def test_re_preparing_identical_source_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir)
            first = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="same-chat"
            )
            second = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="same-chat"
            )
            self.assertEqual(second["readiness"]["state"], "ready")
            self.assertEqual(first["source_id"], second["source_id"])

    def test_failed_preparation_leaves_chat_eligible_for_corrected_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            service = _service(tmp_dir)

            # First upload is too large for the byte limit override... use a real
            # failure: a non-DEXPI file. The chat must remain open for a retry.
            bad_xml = tmp_path / "bad.xml"
            bad_xml.write_text("<root><item /></root>", encoding="utf-8")
            failed = service.start_preparation(
                dexpi_xml_path=bad_xml, session_id="recoverable"
            )
            self.assertEqual(failed["job"]["status"], "failed")
            self.assertEqual(_first_diag_code(failed), "upload.non_dexpi_xml")

            corrected = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="recoverable"
            )
            self.assertEqual(corrected["readiness"]["state"], "ready")

    def test_distinct_chats_each_accept_their_own_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir)
            chat_a = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="chat-a"
            )
            chat_b = service.start_preparation(
                dexpi_xml_path=E03_FIXTURE, session_id="chat-b"
            )
            self.assertEqual(chat_a["readiness"]["state"], "ready")
            self.assertEqual(chat_b["readiness"]["state"], "ready")
            self.assertNotEqual(chat_a["source_id"], chat_b["source_id"])


class DrawingCountIsNotPageCountTests(unittest.TestCase):
    def test_validation_has_no_per_drawing_limit(self) -> None:
        """A DEXPI PlantModel with many Drawing elements is one source, not many
        pages: validate_upload_input enforces XML complexity, never a drawing count."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            many_drawings = Path(tmp_dir) / "many-drawings.xml"
            drawings = "".join(f'<Drawing Name="D{i}" />' for i in range(50))
            many_drawings.write_text(
                '<PlantModel><PlantInformation Application="DEXPI" />'
                f"{drawings}</PlantModel>",
                encoding="utf-8",
            )
            diagnostics = validate_upload_input(many_drawings)
            self.assertEqual(diagnostics, [])

    def test_realistic_source_with_internal_structure_is_one_prepared_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir)
            result = service.start_preparation(
                dexpi_xml_path=C01_FIXTURE, session_id="c01-one-source"
            )
            self.assertEqual(result["readiness"]["state"], "ready")
            # Exactly one source identity for the whole file.
            self.assertEqual(
                result["source_id"], result["readiness"]["source_id"]
            )
            # A second distinct file is rejected — the chat holds one source.
            second = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="c01-one-source"
            )
            self.assertEqual(_first_diag_code(second), "source.already_prepared")


class SourceIdProvenanceTests(unittest.TestCase):
    def test_source_id_is_stable_and_content_derived(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir)
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="provenance"
            )
            self.assertEqual(result["source_id"], compute_source_id(E06_FIXTURE))

    def test_prepared_artifacts_and_evidence_retain_source_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(tmp_dir)
            result = service.start_preparation(
                dexpi_xml_path=E06_FIXTURE, session_id="evidence-source"
            )
            source_id = result["source_id"]
            topology = result["topology_view"]

            self.assertEqual(topology["source_id"], source_id)
            self.assertTrue(topology["evidence_map"])
            for evidence in topology["evidence_map"].values():
                self.assertEqual(evidence["source_id"], source_id)

            # The persisted readiness artifact carries the source id too.
            import json

            readiness_on_disk = json.loads(
                path_from_download_url(result["artifacts"]["readiness_metadata"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(readiness_on_disk["source_id"], source_id)


if __name__ == "__main__":
    unittest.main()
