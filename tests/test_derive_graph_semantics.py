from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
E06_GRAPH_FACTS = (
    REPO_ROOT / "fixtures" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)
CHECKED_IN_E06_DERIVED = (
    REPO_ROOT
    / "fixtures"
    / "derived_graph_semantics"
    / "e06-pump-hex"
    / "derived_graph_semantics.dl"
)
CHECKED_IN_E06_GRAPH_FACTS_DATALOG = (
    REPO_ROOT
    / "fixtures"
    / "derived_graph_semantics"
    / "e06-pump-hex"
    / "graph_facts.dl"
)
GRAPH_TOPOLOGY_IDB = (
    REPO_ROOT
    / "pydexpi_datalog"
    / "datalog"
    / "idb"
    / "graph_topology_semantics.dl"
)


class DeriveGraphSemanticsCliTests(unittest.TestCase):
    def run_derive_graph_semantics(
        self, graph_facts_path: Path, output_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "derive-graph-semantics",
                str(graph_facts_path),
                "--output-dir",
                str(output_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_derive_graph_semantics_emits_edge_family_predicates_for_e06_graph_facts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "derived-graph-semantics"
            datalog_path = output_dir / "e06-pump-hex" / "derived_graph_semantics.dl"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_derive_graph_semantics(E06_GRAPH_FACTS, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(datalog_path.exists(), datalog_path)

            datalog = datalog_path.read_text(encoding="utf-8")
            self.assertIn(
                '.decl composition_edge(source:symbol, target:symbol, attr_name:symbol)',
                datalog,
            )
            self.assertIn(
                '.decl reference_edge(source:symbol, target:symbol, attr_name:symbol)',
                datalog,
            )
            self.assertIn(
                '.decl candidate_topology_edge(source:symbol, target:symbol, attr_name:symbol)',
                datalog,
            )
            self.assertIn(
                ".decl downstream_candidate(source:symbol, target:symbol)",
                datalog,
            )
            self.assertIn(
                ".decl downstream_composition(source:symbol, target:symbol)",
                datalog,
            )
            self.assertIn(
                ".decl downstream_reference(source:symbol, target:symbol)",
                datalog,
            )
            self.assertIn(".decl reachable(source:symbol, target:symbol)", datalog)
            self.assertIn(
                'graph_edge_attribute("195e5f6b-5320-43cc-a25b-e4b14f8497dc", "152b44e1-3763-4f6f-bb0e-ef69897c2c61", "0", "attr_name", "pipingNetworkSystems").',
                datalog,
            )
            self.assertIn(
                'graph_edge_attribute("3b212201-f8b6-47ed-9019-d7961f3276c8", "2accb8cf-7c3d-4563-8c22-5d817f464bd5", "0", "attr_name", "targetItem").',
                datalog,
            )
            self.assertIn(
                "candidate_topology_edge(source, target, attr_name) :-",
                datalog,
            )
            self.assertIn(
                "composition_edge(source, target, attr_name) :-",
                datalog,
            )
            self.assertIn(
                "downstream_candidate(source, target) :- candidate_topology_edge(source, target, _).",
                datalog,
            )
            self.assertIn(
                "downstream_composition(source, target) :- composition_edge(source, target, _).",
                datalog,
            )
            self.assertIn(
                "downstream_reference(source, target) :- reference_edge(source, target, _).",
                datalog,
            )
            self.assertIn(
                "reachable(source, target) :- candidate_topology_edge(source, target, _).",
                datalog,
            )
            self.assertIn(
                "reachable(source, target) :- candidate_topology_edge(source, intermediate, _), reachable(intermediate, target).",
                datalog,
            )
            self.assertNotIn(".decl downstream(source:symbol, target:symbol)", datalog)

    def test_derive_graph_semantics_splits_generated_edb_from_reusable_idb(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "derived-graph-semantics"
            fixture_dir = output_dir / "e06-pump-hex"
            graph_facts_datalog_path = fixture_dir / "graph_facts.dl"
            combined_datalog_path = fixture_dir / "derived_graph_semantics.dl"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_derive_graph_semantics(E06_GRAPH_FACTS, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(graph_facts_datalog_path.exists(), graph_facts_datalog_path)
            self.assertTrue(combined_datalog_path.exists(), combined_datalog_path)
            self.assertTrue(GRAPH_TOPOLOGY_IDB.exists(), GRAPH_TOPOLOGY_IDB)

            graph_facts_datalog = graph_facts_datalog_path.read_text(encoding="utf-8")
            idb_datalog = GRAPH_TOPOLOGY_IDB.read_text(encoding="utf-8")
            combined_datalog = combined_datalog_path.read_text(encoding="utf-8")

            self.assertIn(".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)", graph_facts_datalog)
            self.assertIn(
                ".decl graph_edge_attribute(source:symbol, target:symbol, edge_key:symbol, attr_name:symbol, attr_value:symbol)",
                graph_facts_datalog,
            )
            self.assertIn(
                'graph_edge_attribute("3b212201-f8b6-47ed-9019-d7961f3276c8", "2accb8cf-7c3d-4563-8c22-5d817f464bd5", "0", "attr_name", "targetItem").',
                graph_facts_datalog,
            )
            self.assertNotIn(".decl composition_edge", graph_facts_datalog)
            self.assertNotIn("composition_edge(", graph_facts_datalog)

            self.assertIn(
                "composition_edge(source, target, attr_name) :-",
                idb_datalog,
            )
            self.assertIn(
                "candidate_topology_edge(source, target, attr_name) :-",
                idb_datalog,
            )
            self.assertIn(
                'direct_process_connection(source, target) :- reference_edge(source, target, "sourceItem").',
                idb_datalog,
            )

            self.assertIn(graph_facts_datalog.strip(), combined_datalog)
            self.assertIn(idb_datalog.strip(), combined_datalog)

    def test_derive_graph_semantics_emits_experimental_direct_process_connections(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "derived-graph-semantics"
            datalog_path = output_dir / "e06-pump-hex" / "derived_graph_semantics.dl"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_derive_graph_semantics(E06_GRAPH_FACTS, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(datalog_path.exists(), datalog_path)

            datalog = datalog_path.read_text(encoding="utf-8")
            self.assertIn(
                ".decl direct_process_connection(source:symbol, target:symbol)",
                datalog,
            )
            self.assertIn(
                'direct_process_connection(source, target) :- reference_edge(source, target, "sourceItem").',
                datalog,
            )
            self.assertIn(
                'direct_process_connection(source, target) :- reference_edge(source, target, "targetItem").',
                datalog,
            )

    def test_derive_graph_semantics_emits_object_identity_and_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "derived-graph-semantics"
            datalog_path = output_dir / "e06-pump-hex" / "derived_graph_semantics.dl"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_derive_graph_semantics(E06_GRAPH_FACTS, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(datalog_path.exists(), datalog_path)

            datalog = datalog_path.read_text(encoding="utf-8")
            self.assertIn(".decl node(id:symbol)", datalog)
            self.assertIn(".decl node_label(id:symbol, label:symbol)", datalog)
            self.assertIn(
                'node("16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb").',
                datalog,
            )
            self.assertIn(
                'node_attribute("16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb", "label", "CentrifugalPump").',
                datalog,
            )
            self.assertIn(
                'node_label(id, label) :- node_attribute(id, "label", label).',
                datalog,
            )

    def test_derive_graph_semantics_emits_human_readable_node_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "derived-graph-semantics"
            datalog_path = output_dir / "e06-pump-hex" / "derived_graph_semantics.dl"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_derive_graph_semantics(E06_GRAPH_FACTS, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(datalog_path.exists(), datalog_path)

            datalog = datalog_path.read_text(encoding="utf-8")
            self.assertIn(".decl node_tag(id:symbol, tag:symbol)", datalog)
            self.assertIn(
                ".decl node_proteus_id(id:symbol, proteus_id:symbol)",
                datalog,
            )
            self.assertIn(
                'node_attribute("16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb", "tagName", "P-4713").',
                datalog,
            )
            self.assertIn(
                'node_tag(id, tag) :- node_attribute(id, "tagName", tag).',
                datalog,
            )
            self.assertIn(
                'node_attribute("16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb", "proteusId", "CentrifugalPump-1").',
                datalog,
            )
            self.assertIn(
                'node_proteus_id(id, proteus_id) :- node_attribute(id, "proteusId", proteus_id).',
                datalog,
            )

    def test_repo_persists_representative_derived_graph_semantics_fixture(self) -> None:
        self.assertTrue(CHECKED_IN_E06_DERIVED.exists(), CHECKED_IN_E06_DERIVED)
        self.assertTrue(
            CHECKED_IN_E06_GRAPH_FACTS_DATALOG.exists(),
            CHECKED_IN_E06_GRAPH_FACTS_DATALOG,
        )

        datalog = CHECKED_IN_E06_DERIVED.read_text(encoding="utf-8")
        graph_facts_datalog = CHECKED_IN_E06_GRAPH_FACTS_DATALOG.read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '.decl composition_edge(source:symbol, target:symbol, attr_name:symbol)',
            datalog,
        )
        self.assertIn(
            'graph_edge_attribute("3b212201-f8b6-47ed-9019-d7961f3276c8", "57c776dc-fc90-4276-bb53-f0bbdd01bb83", "0", "attr_name", "sourceItem").',
            datalog,
        )
        self.assertIn(
            'node_attribute("16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb", "label", "CentrifugalPump").',
            datalog,
        )
        self.assertIn(
            'node_attribute("16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb", "tagName", "P-4713").',
            datalog,
        )
        self.assertIn(
            'node_attribute("16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb", "proteusId", "CentrifugalPump-1").',
            datalog,
        )
        self.assertIn(
            ".decl direct_process_connection(source:symbol, target:symbol)",
            datalog,
        )
        self.assertIn(
            'direct_process_connection(source, target) :- reference_edge(source, target, "sourceItem").',
            datalog,
        )
        self.assertIn(".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)", graph_facts_datalog)
        self.assertNotIn(".decl reference_edge", graph_facts_datalog)


if __name__ == "__main__":
    unittest.main()
