"""A prepared review session stays findable after the client forgets its id.

Session identity is a UUID the browser mints into localStorage. Clearing that
storage used to orphan the session's artifacts: still on disk, but nothing
could name them. These tests pin the catalog that makes them findable again
(ADR 0016, bead pydexpi-datalog-1-2afe.3).
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from pydexpi_datalog.web.review_api import create_review_api_app
from pydexpi_datalog.workflow.principal import Principal

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "TrainingTestCases" / "dexpi 1.3" / "example pids"
E06_FIXTURE = (
    FIXTURE_DIR
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)



def _client(root: Path, principal: Principal) -> TestClient:
    return TestClient(
        create_review_api_app(artifact_root=root, principal=principal)
    )


def _prepare(
    client: TestClient,
    session_id: str,
    *,
    filename: str = "E06V01-VER.EX01.xml",
    content: str | None = None,
):
    return client.post(
        f"/api/review/sessions/{session_id}/prepare",
        json={
            "filename": filename,
            "content": (
                E06_FIXTURE.read_text(encoding="utf-8")
                if content is None
                else content
            ),
        },
    )


def _listed(client: TestClient) -> list[dict]:
    response = client.get("/api/review/sessions")
    assert response.status_code == 200, response.text
    return response.json()["sessions"]


class SessionCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        """Give every test its own workspace.

        Locally the catalog is a fresh temporary file per test, so an empty
        database was free. The hosted profile shares one long-lived libSQL
        database across the whole run -- which is what a real deployment
        looks like, and a test that assumes an empty table would only ever
        pass on the profile that throws its database away. Scoping by
        workspace is the isolation the catalog actually provides.
        """

        unique = uuid.uuid4().hex[:12]
        self.alice = Principal(user_id=f"alice-{unique}", workspace=f"alice-{unique}")
        self.bob = Principal(user_id=f"bob-{unique}", workspace=f"bob-{unique}")

    def test_prepared_session_is_findable_after_the_client_forgets_its_id(
        self,
    ) -> None:
        """The browser losing its localStorage must not orphan the session."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            self.assertEqual(
                _prepare(_client(root, self.alice), "forgotten-session").status_code,
                200,
            )

            # A brand new client knows no session id at all, exactly like a
            # browser whose storage was cleared.
            sessions = _listed(_client(root, self.alice))

            self.assertEqual(len(sessions), 1)
            entry = sessions[0]
            self.assertEqual(entry["session_id"], "forgotten-session")
            self.assertEqual(entry["source_filename"], "E06V01-VER.EX01.xml")
            self.assertTrue(entry["created_at"])
            self.assertIn("forgotten-session", entry["artifact_prefix"])

    def test_catalog_needs_no_manual_setup(self) -> None:
        """Listing works on a first run against an artifact root that does not exist."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "never-created" / "sessions"
            self.assertEqual(_listed(_client(root, self.alice)), [])

    def test_sessions_are_listed_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            client = _client(root, self.alice)
            self.assertEqual(_prepare(client, "older-session").status_code, 200)
            self.assertEqual(_prepare(client, "newer-session").status_code, 200)

            self.assertEqual(
                [entry["session_id"] for entry in _listed(client)],
                ["newer-session", "older-session"],
            )

    def test_another_workspace_never_sees_these_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            self.assertEqual(
                _prepare(_client(root, self.alice), "alice-session").status_code, 200
            )

            self.assertEqual(_listed(_client(root, self.bob)), [])

    def test_failed_preparation_is_not_offered_as_a_session(self) -> None:
        """A session that never became ready is not reopenable, so not listed."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            client = _client(root, self.alice)
            failed = _prepare(
                client,
                "broken-session",
                filename="not-a-pid.xml",
                content="this is not DEXPI xml",
            )
            self.assertEqual(failed.status_code, 200, failed.text)
            self.assertNotEqual(failed.json()["status"], "ready")

            self.assertEqual(_listed(client), [])

    def test_repreparing_a_session_does_not_duplicate_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            client = _client(root, self.alice)
            self.assertEqual(_prepare(client, "same-session").status_code, 200)
            self.assertEqual(_prepare(client, "same-session").status_code, 200)

            sessions = _listed(client)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_id"], "same-session")

    def test_catalog_survives_a_server_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            self.assertEqual(
                _prepare(_client(root, self.alice), "durable-session").status_code, 200
            )

            restarted = _client(root, self.alice)
            self.assertEqual(
                [entry["session_id"] for entry in _listed(restarted)],
                ["durable-session"],
            )

    def test_listed_session_can_be_reopened(self) -> None:
        """Reopening means the session's topology still resolves."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            self.assertEqual(
                _prepare(_client(root, self.alice), "reopen-session").status_code, 200
            )

            restarted = _client(root, self.alice)
            session_id = _listed(restarted)[0]["session_id"]
            topology = restarted.get(f"/api/review/sessions/{session_id}/topology")
            self.assertEqual(topology.status_code, 200, topology.text)


if __name__ == "__main__":
    unittest.main()
