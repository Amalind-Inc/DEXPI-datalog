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
                'composition_edge("195e5f6b-5320-43cc-a25b-e4b14f8497dc", "152b44e1-3763-4f6f-bb0e-ef69897c2c61", "pipingNetworkSystems").',
                datalog,
            )
            self.assertIn(
                'reference_edge("3b212201-f8b6-47ed-9019-d7961f3276c8", "2accb8cf-7c3d-4563-8c22-5d817f464bd5", "targetItem").',
                datalog,
            )
            self.assertIn(
                'candidate_topology_edge("3b212201-f8b6-47ed-9019-d7961f3276c8", "2accb8cf-7c3d-4563-8c22-5d817f464bd5", "targetItem").',
                datalog,
            )

    def test_repo_persists_representative_derived_graph_semantics_fixture(self) -> None:
        self.assertTrue(CHECKED_IN_E06_DERIVED.exists(), CHECKED_IN_E06_DERIVED)

        datalog = CHECKED_IN_E06_DERIVED.read_text(encoding="utf-8")
        self.assertIn(
            '.decl composition_edge(source:symbol, target:symbol, attr_name:symbol)',
            datalog,
        )
        self.assertIn(
            'reference_edge("3b212201-f8b6-47ed-9019-d7961f3276c8", "57c776dc-fc90-4276-bb53-f0bbdd01bb83", "sourceItem").',
            datalog,
        )


if __name__ == "__main__":
    unittest.main()
