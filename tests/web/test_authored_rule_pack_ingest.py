from __future__ import annotations

import textwrap
from pathlib import Path
import tempfile
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

ADVISORY_MARKDOWN = textwrap.dedent(
    """\
    ---
    pack_id: epa-highlights
    version: 1
    title: EPA review highlights
    authoritative: false
    trust_notice: Advisory guidance only; not an authoritative standard.
    ---

    # EPA review highlights

    ## Isolation expectations

    Confirm isolation valves are present around major equipment.
    """
)

AUTHORITATIVE_PRETENDER = textwrap.dedent(
    """\
    ---
    pack_id: fake-standard
    version: 1
    title: Fake standard
    authoritative: true
    trust_notice: Pretends to be maintainer-bundled trust.
    ---

    ## Guidance

    Should be rejected on ingest.
    """
)


class AuthoredRulePackIngestTests(unittest.TestCase):
    def test_ingest_advisory_markdown_lists_and_loads_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)

            created = client.post(
                "/api/rule-packs",
                json={"markdown": ADVISORY_MARKDOWN},
            )
            self.assertEqual(created.status_code, 200, created.text)
            body = created.json()
            pack = body["pack"]
            self.assertEqual(pack["pack_id"], "epa-highlights")
            self.assertEqual(pack["source"], "user")
            self.assertFalse(pack["authoritative"])
            self.assertEqual(pack["rules"], [])
            self.assertGreaterEqual(len(pack["advisory_guidance"]), 1)

            listed = client.get("/api/rule-packs")
            self.assertEqual(listed.status_code, 200)
            by_id = {entry["pack_id"]: entry for entry in listed.json()["packs"]}
            self.assertIn("epa-highlights", by_id)
            self.assertEqual(by_id["epa-highlights"]["source"], "user")
            self.assertIn("demo-process-safety", by_id)
            self.assertEqual(by_id["demo-process-safety"]["source"], "system")

            session_id = "authored-ingest-session"
            prepare = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(prepare.status_code, 200, prepare.text)

            session_list = client.get(
                f"/api/review/sessions/{session_id}/rule-packs"
            )
            self.assertEqual(session_list.status_code, 200)
            session_ids = {
                entry["pack_id"] for entry in session_list.json()["packs"]
            }
            self.assertIn("epa-highlights", session_ids)
            loaded = client.post(
                f"/api/review/sessions/{session_id}/rule-packs/epa-highlights/load"
            )
            self.assertEqual(loaded.status_code, 200, loaded.text)
            self.assertTrue(loaded.json()["loaded"])

    def test_reject_authoritative_pretender_on_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)

            response = client.post(
                "/api/rule-packs",
                json={"markdown": AUTHORITATIVE_PRETENDER},
            )
            self.assertEqual(response.status_code, 400)
            detail = response.json()
            self.assertIn("error", detail)
            self.assertNotIn(
                "fake-standard",
                {pack["pack_id"] for pack in client.get("/api/rule-packs").json()["packs"]},
            )

    def test_reject_pack_id_collision_with_bundled_pack(self) -> None:
        collision = textwrap.dedent(
            """\
            ---
            pack_id: demo-process-safety
            version: 99
            title: Collision
            authoritative: false
            trust_notice: Must not overwrite bundled pack.
            ---

            ## Guidance

            Nope.
            """
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            response = client.post("/api/rule-packs", json={"markdown": collision})
            self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
