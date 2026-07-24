from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pydexpi_datalog.web.review_api import create_review_api_app
from pydexpi_datalog.workflow.principal import InvalidWorkspace, Principal


REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)

AUTHORED_MARKDOWN = textwrap.dedent(
    """\
    ---
    pack_id: alice-isolation-pack
    version: 1
    title: Alice's isolation checks
    authoritative: false
    trust_notice: Advisory guidance only; not an authoritative standard.
    ---

    # Alice's isolation checks

    ## Isolation expectations

    Confirm isolation valves are present around major equipment.
    """
)

ALICE = Principal(user_id="alice", workspace="alice")
BOB = Principal(user_id="bob", workspace="bob")


def _client(root: Path, principal: Principal | None = None) -> TestClient:
    if principal is None:
        return TestClient(create_review_api_app(artifact_root=root))
    return TestClient(
        create_review_api_app(artifact_root=root, principal=principal)
    )


def _prepare(client: TestClient, session_id: str):
    return client.post(
        f"/api/review/sessions/{session_id}/prepare",
        json={
            "filename": "E06V01-VER.EX01.xml",
            "content": E06_FIXTURE.read_text(encoding="utf-8"),
        },
    )


class WorkspaceScopingTests(unittest.TestCase):
    def test_authored_packs_do_not_leak_between_workspaces(self) -> None:
        """An authored pack is the author's alone (author-confirmed rule trust)."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            alice = _client(root, ALICE)
            bob = _client(root, BOB)

            created = alice.post(
                "/api/rule-packs", json={"markdown": AUTHORED_MARKDOWN}
            )
            self.assertEqual(created.status_code, 200, created.text)

            alice_packs = {
                entry["pack_id"]
                for entry in alice.get("/api/rule-packs").json()["packs"]
            }
            bob_packs = {
                entry["pack_id"]
                for entry in bob.get("/api/rule-packs").json()["packs"]
            }

            self.assertIn("alice-isolation-pack", alice_packs)
            self.assertNotIn(
                "alice-isolation-pack",
                bob_packs,
                "an authored pack must not be visible to another workspace",
            )
            # Bundled packs carry bundled rule-pack trust and stay available
            # to every workspace.
            self.assertIn("demo-process-safety", bob_packs)

    def test_session_artifacts_are_written_beneath_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            prepared = _prepare(_client(root, ALICE), "shared-session-id")
            self.assertEqual(prepared.status_code, 200, prepared.text)

            self.assertTrue(
                (root / "alice" / "shared-session-id").is_dir(),
                "artifacts must land under the owning workspace",
            )
            self.assertFalse(
                (root / "shared-session-id").exists(),
                "artifacts must not land beside the workspaces",
            )

    def test_one_workspace_cannot_read_another_session_of_the_same_name(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            session_id = "shared-session-id"
            self.assertEqual(
                _prepare(_client(root, ALICE), session_id).status_code, 200
            )

            bob_topology = _client(root, BOB).get(
                f"/api/review/sessions/{session_id}/topology"
            )
            self.assertNotEqual(
                bob_topology.status_code,
                200,
                "another workspace's session must not resolve",
            )

    def test_default_principal_scopes_to_the_local_workspace(self) -> None:
        """Callers that pass no principal get the single local operator."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            prepared = _prepare(_client(root), "local-session")
            self.assertEqual(prepared.status_code, 200, prepared.text)
            self.assertTrue((root / "local" / "local-session").is_dir())

    def test_two_apps_on_one_workspace_share_state(self) -> None:
        """Restarting the server must not orphan the operator's own packs."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "sessions"
            created = _client(root, ALICE).post(
                "/api/rule-packs", json={"markdown": AUTHORED_MARKDOWN}
            )
            self.assertEqual(created.status_code, 200, created.text)

            reconnected = _client(root, ALICE).get("/api/rule-packs")
            self.assertIn(
                "alice-isolation-pack",
                {entry["pack_id"] for entry in reconnected.json()["packs"]},
            )


class WorkspaceValidationTests(unittest.TestCase):
    def test_workspace_must_be_a_single_safe_storage_segment(self) -> None:
        for workspace in ("", ".", "..", "a/b", "a\\b", " alice", "alice "):
            with self.subTest(workspace=workspace):
                with self.assertRaises(InvalidWorkspace):
                    Principal(user_id="someone", workspace=workspace)

    def test_traversal_workspace_cannot_escape_the_artifact_root(self) -> None:
        with self.assertRaises(InvalidWorkspace):
            Principal(user_id="attacker", workspace="../other")


if __name__ == "__main__":
    unittest.main()
