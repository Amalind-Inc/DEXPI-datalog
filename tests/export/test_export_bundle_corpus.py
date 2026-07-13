from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
TRAINING_ROOT = REPO_ROOT / "TrainingTestCases" / "dexpi 1.3" / "example pids"
E03_FIXTURE = (
    TRAINING_ROOT / "E03 Pump With Nozzles" / "E03V01-VER.EX01.xml"
)
E06_FIXTURE = (
    TRAINING_ROOT
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class ExportBundleCorpusCliTests(unittest.TestCase):
    @unittest.skipUnless(
        E03_FIXTURE.is_file() and E06_FIXTURE.is_file(),
        "TrainingTestCases is an external fixture corpus and is not checked in",
    )
    def test_bundle_mode_reports_a_bad_drawing_and_continues_the_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_root = Path(tmp_dir) / "fixtures"
            output_dir = Path(tmp_dir) / "bundles"
            good_source = fixture_root / "01-good" / "e03.xml"
            bad_source = fixture_root / "02-bad" / "broken.xml"
            later_source = fixture_root / "03-later" / "e06.xml"
            for source in (good_source, bad_source, later_source):
                source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(E03_FIXTURE, good_source)
            bad_source.write_text("<not-dexpi>", encoding="utf-8")
            shutil.copyfile(E06_FIXTURE, later_source)
            prior_facts = output_dir / "02-bad-broken" / "graph_facts.json"
            prior_facts.parent.mkdir(parents=True)
            prior_facts.write_text('{"prior": true}', encoding="utf-8")
            stale_good_file = output_dir / "01-good-e03" / "stale.txt"
            stale_good_file.parent.mkdir(parents=True)
            stale_good_file.write_text("remove me", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "export-corpus",
                    str(fixture_root),
                    "--output-dir",
                    str(output_dir),
                    "--bundles",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary_path = output_dir / "bundle_summary.json"
            self.assertTrue(summary_path.is_file())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(
                summary["totals"],
                {"discovered": 3, "bundled": 2, "failed": 1},
            )

            fixtures = {
                fixture["relative_path"]: fixture for fixture in summary["fixtures"]
            }
            self.assertEqual(fixtures["02-bad/broken.xml"]["status"], "failed")
            self.assertTrue(fixtures["02-bad/broken.xml"]["error"])
            self.assertEqual(
                prior_facts.read_text(encoding="utf-8"),
                '{"prior": true}',
            )
            self.assertEqual(
                {path.name for path in prior_facts.parent.iterdir()},
                {"graph_facts.json"},
            )
            self.assertEqual(fixtures["03-later/e06.xml"]["status"], "bundled")

            for fixture_id, relative_path in (
                ("01-good-e03", "01-good/e03.xml"),
                ("03-later-e06", "03-later/e06.xml"),
            ):
                bundle_dir = output_dir / fixture_id
                self.assertEqual(
                    {path.name for path in bundle_dir.iterdir()},
                    {"README.md", "drawing.xml", "graph.json", "graph_facts.json"},
                )
                self.assertIn(
                    relative_path,
                    (bundle_dir / "README.md").read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
