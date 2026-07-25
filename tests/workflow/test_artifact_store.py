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
import tempfile
import unittest
from pathlib import Path

from pydexpi_datalog.workflow.artifact_store import (
    ArtifactStore,
    ArtifactNotFound,
    InvalidArtifactKey,
    LocalArtifactStore,
)


class ArtifactStoreContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "workspace"
        self.store = LocalArtifactStore(self.root)

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


class ProtocolConformanceTests(unittest.TestCase):
    def test_local_store_satisfies_the_artifact_store_protocol(self) -> None:
        """The guard for the hosted implementation bead 2afe.8 adds."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsInstance(LocalArtifactStore(Path(tmp)), ArtifactStore)


if __name__ == "__main__":
    unittest.main()
