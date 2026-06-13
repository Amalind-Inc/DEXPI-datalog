from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class DryRunCliTests(unittest.TestCase):
    def test_dry_run_accepts_yaml_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101'/></PlantModel>",
                encoding="utf-8",
            )

            run_id = "yaml-run"
            manifest_path = tmp_path / "manifest.yaml"
            manifest_path.write_text(
                "\n".join(
                    [
                        "schema_version: 1",
                        "input:",
                        f"  dexpi_xml: {source_path}",
                        "rule_pack:",
                        "  name: pump-safety",
                        "  version: 4",
                        "  lifecycle_state: active",
                        "execution:",
                        "  mode: dry-run",
                        "output:",
                        f"  run_id: {run_id}",
                    ]
                ),
                encoding="utf-8",
            )

            artifact_path = REPO_ROOT / "artifacts" / run_id / "dry_run_summary.json"
            run_artifact_dir = artifact_path.parent
            if run_artifact_dir.exists():
                shutil.rmtree(run_artifact_dir)
            self.addCleanup(
                lambda: shutil.rmtree(run_artifact_dir, ignore_errors=True)
            )

            result = subprocess.run(
                [sys.executable, "-m", "pydexpi_datalog", "dry-run", str(manifest_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Status: ok", result.stdout)
            self.assertTrue(artifact_path.exists())

    def test_dry_run_persists_summary_and_prints_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                (
                    "<PlantModel>"
                    "<Equipment id='P-101' tag='P-101' tag_variant_1='P101' componentClass='Pump' />"
                    "<Line id='L-1' tag='L-1' />"
                    "</PlantModel>"
                ),
                encoding="utf-8",
            )

            manifest_path = tmp_path / "manifest.json"
            run_id = "run-001"
            manifest = {
                "schema_version": 1,
                "input": {"dexpi_xml": str(source_path)},
                "rule_pack": {
                    "name": "pump-safety",
                    "version": 4,
                    "lifecycle_state": "active",
                },
                "execution": {"mode": "dry-run"},
                "output": {"run_id": run_id},
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            artifact_path = REPO_ROOT / "artifacts" / run_id / "dry_run_summary.json"
            run_artifact_dir = artifact_path.parent
            if run_artifact_dir.exists():
                shutil.rmtree(run_artifact_dir)
            self.addCleanup(
                lambda: shutil.rmtree(run_artifact_dir, ignore_errors=True)
            )

            result = subprocess.run(
                [sys.executable, "-m", "pydexpi_datalog", "dry-run", str(manifest_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Dry-Run Summary", result.stdout)
            self.assertIn("Status: ok", result.stdout)
            self.assertIn("source.loaded", result.stdout)

            self.assertTrue(artifact_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["run"]["status"], "ok")
            self.assertEqual(artifact["structural_summary"]["root_tag"], "PlantModel")
            self.assertEqual(
                artifact["structural_summary"]["elements_with_id_count"],
                2,
            )
            self.assertEqual(
                artifact["structural_summary"]["object_ids"],
                ["L-1", "P-101"],
            )
            self.assertEqual(
                artifact["canonical_engineering_ir"]["canonical_objects"],
                [
                    {
                        "object_id": "L-1",
                        "canonical_tag": "L-1",
                        "source_attributes": {"id": "L-1", "tag": "L-1"},
                        "diagnostics": [],
                    },
                    {
                        "object_id": "P-101",
                        "canonical_tag": "P-101",
                        "source_attributes": {
                            "id": "P-101",
                            "tag": "P-101",
                            "tag_variant_1": "P101",
                            "componentClass": "Pump",
                        },
                        "diagnostics": [
                            {
                                "code": "normalizer.ambiguous_canonical_tag",
                                "severity": "warning",
                                "message": "Canonical tag 'P-101' for object 'P-101' has an ambiguous raw variant 'P101'.",
                                "path": "P-101",
                            }
                        ],
                    },
                ],
            )
            self.assertEqual(artifact["findings"], [])
            self.assertEqual(artifact["patch_proposals"], [])

    def test_dry_run_reports_validation_errors_and_persists_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest_path = tmp_path / "bad_manifest.json"
            run_id = "run-invalid"
            manifest = {
                "schema_version": 99,
                "input": {"dexpi_xml": str(tmp_path / "missing.xml")},
                "rule_pack": {
                    "name": "pump-safety",
                    "version": "four",
                    "lifecycle_state": "active",
                },
                "execution": {"mode": "dry-run"},
                "output": {"run_id": run_id},
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            artifact_path = REPO_ROOT / "artifacts" / run_id / "dry_run_summary.json"
            run_artifact_dir = artifact_path.parent
            if run_artifact_dir.exists():
                shutil.rmtree(run_artifact_dir)
            self.addCleanup(
                lambda: shutil.rmtree(run_artifact_dir, ignore_errors=True)
            )

            result = subprocess.run(
                [sys.executable, "-m", "pydexpi_datalog", "dry-run", str(manifest_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("manifest.invalid_schema_version", result.stdout)
            self.assertIn("manifest.invalid_integer", result.stdout)

            self.assertTrue(artifact_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("manifest.invalid_schema_version", diagnostic_codes)
            self.assertIn("manifest.invalid_integer", diagnostic_codes)
            self.assertIsNone(artifact["structural_summary"])

    def test_dry_run_rejects_non_dry_run_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101'/></PlantModel>",
                encoding="utf-8",
            )

            run_id = "wrong-mode"
            manifest_path = tmp_path / "manifest.json"
            manifest = {
                "schema_version": 1,
                "input": {"dexpi_xml": str(source_path)},
                "rule_pack": {
                    "name": "pump-safety",
                    "version": 4,
                    "lifecycle_state": "active",
                },
                "execution": {"mode": "review-only"},
                "output": {"run_id": run_id},
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            artifact_path = REPO_ROOT / "artifacts" / run_id / "dry_run_summary.json"
            run_artifact_dir = artifact_path.parent
            if run_artifact_dir.exists():
                shutil.rmtree(run_artifact_dir)
            self.addCleanup(
                lambda: shutil.rmtree(run_artifact_dir, ignore_errors=True)
            )

            result = subprocess.run(
                [sys.executable, "-m", "pydexpi_datalog", "dry-run", str(manifest_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("manifest.execution_mode_mismatch", result.stdout)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("manifest.execution_mode_mismatch", diagnostic_codes)

    def test_dry_run_persists_original_manifest_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101'/></PlantModel>",
                encoding="utf-8",
            )

            run_id = "manifest-copy"
            manifest_path = tmp_path / "manifest.yaml"
            manifest_text = "\n".join(
                [
                    "schema_version: 1",
                    "input:",
                    f"  dexpi_xml: {source_path}",
                    "rule_pack:",
                    "  name: pump-safety",
                    "  version: 4",
                    "  lifecycle_state: active",
                    "execution:",
                    "  mode: dry-run",
                    "output:",
                    f"  run_id: {run_id}",
                ]
            )
            manifest_path.write_text(manifest_text, encoding="utf-8")

            run_artifact_dir = REPO_ROOT / "artifacts" / run_id
            if run_artifact_dir.exists():
                shutil.rmtree(run_artifact_dir)
            self.addCleanup(
                lambda: shutil.rmtree(run_artifact_dir, ignore_errors=True)
            )

            result = subprocess.run(
                [sys.executable, "-m", "pydexpi_datalog", "dry-run", str(manifest_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            copied_manifest = run_artifact_dir / "manifest.yaml"
            self.assertTrue(copied_manifest.exists())
            self.assertEqual(
                copied_manifest.read_text(encoding="utf-8"),
                manifest_text,
            )


if __name__ == "__main__":
    unittest.main()
