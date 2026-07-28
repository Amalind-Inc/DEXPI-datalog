from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydexpi_datalog.workflow.artifact_store import LocalArtifactStore
from pydexpi_datalog.workflow.source_preparation_cache import SourcePreparationCache


class SourcePreparationCacheTests(unittest.TestCase):
    def test_materializes_execution_artifacts_with_fresh_session_overlays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = LocalArtifactStore(Path(tmp_dir))
            cache = SourcePreparationCache(store=store, source_digest="a" * 64)
            cache.store(
                graph_facts={"graph": {"node_count": 1, "edge_count": 0}},
                graph_facts_datalog=".decl node(id:symbol)\n",
                derived_semantics_datalog=".decl derived(id:symbol)\n",
                topology={
                    "session_id": "first",
                    "source_id": "source-old",
                    "source_path": "/old.xml",
                    "nodes": [{"id": "P-101"}],
                    "edges": [],
                    "evidence_highlight": {"matched_object_ids": ["P-101"]},
                },
            )

            restored = cache.materialize(
                session_id="second", source_id="source-new", source_path="/new.xml"
            )

            topology = restored["topology"]
            self.assertEqual(topology["session_id"], "second")
            self.assertEqual(topology["source_id"], "source-new")
            self.assertEqual(topology["source_path"], "/new.xml")
            self.assertEqual(topology["nodes"], [{"id": "P-101"}])
            self.assertEqual(
                topology["evidence_highlight"],
                {"source_scope_ids": [], "matched_object_ids": [], "paths": []},
            )
            self.assertEqual(store.read_json("second/second/graph_facts.json"), restored["graph_facts"])
            self.assertEqual(store.read_text("second/graph_facts.dl"), ".decl node(id:symbol)\n")
            self.assertEqual(store.read_text("second/derived_graph_semantics.dl"), ".decl derived(id:symbol)\n")
            self.assertEqual(store.read_json("second/topology_view.json"), topology)


if __name__ == "__main__":
    unittest.main()
