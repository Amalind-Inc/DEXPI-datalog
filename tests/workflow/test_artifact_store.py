"""Behavioural contract for the artifact store.

Every artifact the review flow reads or writes goes through this interface, so
the hosted object-store implementation can drop in later without touching
workflow, verification, or QA code. These tests pin the contract itself; they
are written against the local filesystem implementation because it is the only
one that exists today, but nothing here reaches for a filesystem detail that a
bucket could not honour -- except the two tests that explicitly pin the
on-disk layout, which is a promise the local implementation alone makes.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from pydexpi_datalog.workflow.artifact_store import (
    ArtifactNotFound,
    ArtifactStore,
    InvalidArtifactKey,
    LocalArtifactStore,
)

S3_ENDPOINT_ENV_VAR = "PYDEXPI_S3_TEST_ENDPOINT"


def _fetch(url: str) -> str:
    """Read a download URL the way a browser would: no application involved."""

    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        return response.read().decode("utf-8")


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def s3_test_store(case: unittest.TestCase, *, workspace: str) -> ArtifactStore:
    """A store on the real object server, in a bucket created for this run.

    Skips when no server is configured. In CI the endpoint is always set, so
    a skip there would mean the service container is broken -- see
    `tests/conftest.py`, which refuses to convert that into a skip.
    """

    endpoint = os.environ.get(S3_ENDPOINT_ENV_VAR, "").strip()
    if not endpoint:
        raise unittest.SkipTest(
            f"no object store: set {S3_ENDPOINT_ENV_VAR} to run this leg"
        )

    from pydexpi_datalog.workflow.s3_artifact_store import (
        S3ArtifactStore,
        S3Settings,
        build_s3_client,
    )

    settings = S3Settings(
        endpoint_url=endpoint,
        bucket=os.environ.get("PYDEXPI_S3_TEST_BUCKET", "pydexpi-test"),
        access_key_id=os.environ.get("PYDEXPI_S3_ACCESS_KEY_ID", "minioadmin"),
        secret_access_key=os.environ.get("PYDEXPI_S3_SECRET_ACCESS_KEY", "minioadmin"),
        region=os.environ.get("PYDEXPI_S3_REGION", "us-east-1"),
    )
    client = build_s3_client(settings)
    try:
        client.create_bucket(Bucket=settings.bucket)
    except Exception:  # noqa: BLE001 - already exists is the common case
        pass
    del case
    return S3ArtifactStore(client=client, bucket=settings.bucket, prefix=workspace)


class ArtifactStoreContractTests(unittest.TestCase):
    """Behaviour every store owes, whatever it writes to.

    Subclassed once per implementation. The hosted object store inherits all
    of it, so a bucket that cannot honour some corner of the contract fails
    here rather than in the profile nobody runs locally.
    """

    def _make_store(self) -> ArtifactStore:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "workspace"
        return LocalArtifactStore(self.root)

    def setUp(self) -> None:
        self.store = self._make_store()

    def test_text_roundtrips(self) -> None:
        self.store.write_text("session-1/graph_facts.dl", "node(\"a\").\n")
        self.assertEqual(self.store.read_text("session-1/graph_facts.dl"), 'node("a").\n')

    def test_json_roundtrips(self) -> None:
        self.store.write_json("session-1/topology_view.json", {"nodes": [1, 2]})
        self.assertEqual(
            self.store.read_json("session-1/topology_view.json"), {"nodes": [1, 2]}
        )

    def test_writing_creates_missing_parents(self) -> None:
        """No caller should have to mkdir before writing."""
        self.store.write_text("a/deeply/nested/key.txt", "value")
        self.assertEqual(self.store.read_text("a/deeply/nested/key.txt"), "value")

    def test_reading_a_missing_key_raises_artifact_not_found(self) -> None:
        with self.assertRaises(ArtifactNotFound):
            self.store.read_text("session-1/nope.json")

    def test_exists_reports_presence(self) -> None:
        self.assertFalse(self.store.exists("session-1/readiness.json"))
        self.store.write_json("session-1/readiness.json", {"state": "ready"})
        self.assertTrue(self.store.exists("session-1/readiness.json"))

    def test_exists_is_false_for_a_directory_key(self) -> None:
        """A prefix that holds artifacts is not itself an artifact."""
        self.store.write_text("session-1/turns/t1.json", "{}")
        self.assertFalse(self.store.exists("session-1/turns"))

    def test_list_returns_sorted_relative_keys_under_a_prefix(self) -> None:
        self.store.write_text("session-1/results/b.json", "{}")
        self.store.write_text("session-1/results/a.json", "{}")
        self.store.write_text("session-2/results/c.json", "{}")
        self.assertEqual(
            self.store.list("session-1/results"),
            ["session-1/results/a.json", "session-1/results/b.json"],
        )

    def test_list_filters_by_suffix(self) -> None:
        self.store.write_text("session-1/results/a.json", "{}")
        self.store.write_text("session-1/results/notes.txt", "x")
        self.assertEqual(
            self.store.list("session-1/results", suffix=".json"),
            ["session-1/results/a.json"],
        )

    def test_list_of_a_missing_prefix_is_empty(self) -> None:
        self.assertEqual(self.store.list("session-1/results"), [])

    def test_list_does_not_recurse_into_subprefixes(self) -> None:
        self.store.write_text("session-1/a.json", "{}")
        self.store.write_text("session-1/nested/b.json", "{}")
        self.assertEqual(self.store.list("session-1", suffix=".json"), ["session-1/a.json"])

    def test_size_reports_bytes(self) -> None:
        self.store.write_text("session-1/graph_facts.dl", "abcde")
        self.assertEqual(self.store.size("session-1/graph_facts.dl"), 5)

    def test_copy_duplicates_an_artifact(self) -> None:
        self.store.write_text("session-1/a.json", "payload")
        self.store.copy("session-1/a.json", "_exports/run/a.json")
        self.assertEqual(self.store.read_text("_exports/run/a.json"), "payload")
        self.assertTrue(self.store.exists("session-1/a.json"))

    def test_writes_are_atomic_and_leave_no_staging_artifact(self) -> None:
        """A reader must never observe a half-written artifact."""
        self.store.write_json("session-1/topology_view.json", {"nodes": []})
        stray = [key for key in self.store.list("session-1") if ".tmp" in key]
        self.assertEqual(stray, [])

    def test_overwrite_replaces_content(self) -> None:
        self.store.write_text("session-1/readiness.json", "first")
        self.store.write_text("session-1/readiness.json", "second")
        self.assertEqual(self.store.read_text("session-1/readiness.json"), "second")

    def test_append_line_accumulates_records_in_order(self) -> None:
        self.store.append_line("s1/datalog_audit.jsonl", '{"n":1}')
        self.store.append_line("s1/datalog_audit.jsonl", '{"n":2}')
        self.assertEqual(
            self.store.read_text("s1/datalog_audit.jsonl"),
            '{"n":1}\n{"n":2}\n',
        )

    def test_append_line_creates_the_artifact_and_parents(self) -> None:
        self.store.append_line("s1/nested/audit.jsonl", "first")
        self.assertEqual(self.store.read_text("s1/nested/audit.jsonl"), "first\n")

    def test_append_line_does_not_double_terminate(self) -> None:
        self.store.append_line("s1/audit.jsonl", "already\n")
        self.assertEqual(self.store.read_text("s1/audit.jsonl"), "already\n")

    def test_local_path_exposes_a_real_readable_file(self) -> None:
        """Third-party tools (pyDEXPI, Souffle) need a genuine filesystem path."""
        self.store.write_text("s1/drawing.xml", "<xml/>")
        with self.store.local_path("s1/drawing.xml") as path:
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "<xml/>")

    def test_open_bytes_streams_without_reading_the_whole_artifact(self) -> None:
        self.store.write_text("s1/graph_facts.dl", "0123456789")
        with self.store.open_bytes("s1/graph_facts.dl") as stream:
            self.assertEqual(stream.read(4), b"0123")

    def test_local_dir_yields_a_real_directory_writers_can_populate(self) -> None:
        """The DEXPI export pipeline writes into a directory it is handed."""
        with self.store.local_dir("s1/export") as directory:
            self.assertTrue(directory.is_dir())
            (directory / "graph_facts.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.store.read_text("s1/export/graph_facts.json"), "{}")

    def test_a_download_url_serves_the_bytes_without_the_application(self) -> None:
        """Artifact bytes must be fetchable without proxying through the app.

        Local answers with a `file://` URL because that is what a local
        artifact honestly is; the hosted store answers with a presigned HTTPS
        URL. Callers get one field that always resolves to the bytes.
        """

        self.store.write_text("s1/report.json", '{"ok": true}')
        url = self.store.download_url("s1/report.json")
        self.assertTrue(url, "every store must offer a download URL")
        self.assertEqual('{"ok": true}', _fetch(url))


class ArtifactKeyContainmentTests(unittest.TestCase):
    """A key is request-supplied data; it must never escape the workspace."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "workspace"
        self.store = LocalArtifactStore(self.root)

    def test_parent_traversal_is_rejected(self) -> None:
        for key in ("../escape.json", "session-1/../../escape.json", "a/../../b"):
            with self.subTest(key=key), self.assertRaises(InvalidArtifactKey):
                self.store.write_text(key, "nope")

    def test_absolute_keys_are_rejected(self) -> None:
        with self.assertRaises(InvalidArtifactKey):
            self.store.read_text("/etc/passwd")

    def test_empty_key_is_rejected(self) -> None:
        with self.assertRaises(InvalidArtifactKey):
            self.store.read_text("")

    def test_traversal_is_rejected_even_when_it_resolves_inside(self) -> None:
        """`a/../b` stays inside, but permitting it invites the ones that don't."""
        with self.assertRaises(InvalidArtifactKey):
            self.store.write_text("session-1/../session-2/x.json", "nope")


class LocalLayoutTests(unittest.TestCase):
    """The local implementation preserves the existing on-disk layout exactly."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "workspace"
        self.store = LocalArtifactStore(self.root)

    def test_a_key_maps_to_the_same_relative_path_under_the_root(self) -> None:
        self.store.write_json("s1/topology_view.json", {"ok": True})
        on_disk = self.root / "s1" / "topology_view.json"
        self.assertTrue(on_disk.is_file())
        self.assertEqual(json.loads(on_disk.read_text(encoding="utf-8")), {"ok": True})


class S3ArtifactStoreContractTests(ArtifactStoreContractTests):
    """The same contract, against a real S3-compatible server.

    Inherited wholesale rather than restated: a bucket that cannot honour
    some corner of the interface -- append, streaming reads, a real directory
    for the DEXPI exporter -- fails on the shared test, not on a hosted-only
    variant written to accommodate it.

    Needs a server; there is no in-process S3:

        docker run -d -p 9100:9000 -e MINIO_ROOT_USER=minioadmin \\
            -e MINIO_ROOT_PASSWORD=minioadmin quay.io/minio/minio:latest \\
            server /data
        export PYDEXPI_S3_TEST_ENDPOINT=http://127.0.0.1:9100
    """

    def _make_store(self) -> ArtifactStore:
        return s3_test_store(self, workspace=f"ws-{uuid.uuid4().hex[:12]}")


class S3WorkspaceIsolationTests(unittest.TestCase):
    """One workspace's prefix is a boundary, not a naming convention."""

    def setUp(self) -> None:
        self.mine = s3_test_store(self, workspace=f"mine-{uuid.uuid4().hex[:8]}")
        self.theirs = s3_test_store(self, workspace=f"theirs-{uuid.uuid4().hex[:8]}")

    def test_an_identical_key_in_two_workspaces_holds_different_bytes(self) -> None:
        self.mine.write_text("s1/secret.json", '{"owner": "mine"}')
        self.theirs.write_text("s1/secret.json", '{"owner": "theirs"}')
        self.assertEqual('{"owner": "mine"}', self.mine.read_text("s1/secret.json"))
        self.assertEqual('{"owner": "theirs"}', self.theirs.read_text("s1/secret.json"))

    def test_a_workspace_cannot_read_a_key_it_does_not_hold(self) -> None:
        self.theirs.write_text("s1/private.json", '{"owner": "theirs"}')
        with self.assertRaises(ArtifactNotFound):
            self.mine.read_text("s1/private.json")

    def test_listing_never_reaches_another_workspace(self) -> None:
        self.theirs.write_text("s1/theirs.json", "{}")
        self.mine.write_text("s1/mine.json", "{}")
        self.assertEqual(["s1/mine.json"], self.mine.list("s1"))

    def test_a_traversing_key_cannot_climb_out_of_the_prefix(self) -> None:
        """The prefix is the whole isolation, so escaping it is escaping the user."""

        for key in ("../other/x.json", "s1/../../other/x.json", "/absolute.json"):
            with self.subTest(key=key), self.assertRaises(InvalidArtifactKey):
                self.mine.write_text(key, "nope")


class S3PresignedDownloadTests(unittest.TestCase):
    """Bytes leave via the object store, not through the application."""

    def setUp(self) -> None:
        self.store = s3_test_store(self, workspace=f"dl-{uuid.uuid4().hex[:8]}")

    def test_the_download_url_points_at_the_object_store(self) -> None:
        self.store.write_text("s1/big-export.json", '{"rows": 1}')
        url = self.store.download_url("s1/big-export.json")
        self.assertTrue(url.startswith("http"), url)
        self.assertIn("X-Amz-Signature", url, "must be presigned, not a bare URL")

    def test_the_url_is_scoped_to_one_key(self) -> None:
        """A presigned URL is a capability; it must not open the workspace."""

        self.store.write_text("s1/allowed.json", '{"ok": true}')
        self.store.write_text("s1/forbidden.json", '{"secret": true}')
        url = self.store.download_url("s1/allowed.json")
        swapped = url.replace("allowed.json", "forbidden.json")
        self.assertNotEqual(200, _status(swapped))

    def test_an_expired_url_stops_working(self) -> None:
        self.store.write_text("s1/ephemeral.json", "{}")
        url = self.store.download_url("s1/ephemeral.json", expires_in=1)
        self.assertEqual(200, _status(url))
        time.sleep(2)
        self.assertNotEqual(200, _status(url))


class ProtocolConformanceTests(unittest.TestCase):
    def test_local_store_satisfies_the_artifact_store_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsInstance(LocalArtifactStore(Path(tmp)), ArtifactStore)

    def test_the_object_store_satisfies_the_same_protocol(self) -> None:
        self.assertIsInstance(
            s3_test_store(self, workspace=f"proto-{uuid.uuid4().hex[:8]}"),
            ArtifactStore,
        )


if __name__ == "__main__":
    unittest.main()
