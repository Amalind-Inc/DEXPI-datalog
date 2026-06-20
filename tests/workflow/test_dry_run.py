from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]


class DryRunCliTests(unittest.TestCase):
    def write_manifest(
        self,
        manifest_path: Path,
        *,
        source_path: Path,
        run_id: str,
        rule_pack_version: int | str = 4,
    ) -> None:
        manifest = {
            "schema_version": 1,
            "input": {"dexpi_xml": str(source_path)},
            "rule_pack": {
                "name": "pump-safety",
                "version": rule_pack_version,
                "lifecycle_state": "active",
            },
            "execution": {"mode": "dry-run"},
            "output": {"run_id": run_id},
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def run_dry_run(self, manifest_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pydexpi_datalog", "dry-run", str(manifest_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def cleanup_run_dir(self, run_id: str) -> Path:
        run_artifact_dir = REPO_ROOT / "artifacts" / run_id
        if run_artifact_dir.exists():
            shutil.rmtree(run_artifact_dir)
        self.addCleanup(lambda: shutil.rmtree(run_artifact_dir, ignore_errors=True))
        return run_artifact_dir

    def run_context_key(self, source_path: Path, run_id: str) -> str:
        import hashlib

        return hashlib.sha256(
            json.dumps(
                {
                    "dexpi_xml": str(source_path.resolve()),
                    "rule_pack_name": "pump-safety",
                    "rule_pack_version": 4,
                    "rule_pack_lifecycle_state": "active",
                    "execution_mode": "dry-run",
                    "run_id": run_id,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def test_dry_run_does_not_build_source_artifacts_when_manifest_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_text = "<PlantModel><Equipment id='P-101' tag='P-101'/></PlantModel>"
            source_path.write_text(source_text, encoding="utf-8")

            invalid_run_id = "invalid-manifest"
            invalid_manifest_path = tmp_path / "invalid-manifest.json"
            self.write_manifest(
                invalid_manifest_path,
                source_path=source_path,
                run_id=invalid_run_id,
                rule_pack_version="four",
            )

            artifact_path = REPO_ROOT / "artifacts" / invalid_run_id / "dry_run_summary.json"
            self.cleanup_run_dir(invalid_run_id)

            result = self.run_dry_run(invalid_manifest_path)

            self.assertEqual(result.returncode, 1, result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertIsNone(artifact["structural_summary"])
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("manifest.invalid_integer", diagnostic_codes)

    def test_dry_run_fails_when_full_run_context_lock_is_already_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101' tag='P-101'/></PlantModel>",
                encoding="utf-8",
            )

            run_id = "locked-run"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(manifest_path, source_path=source_path, run_id=run_id)

            context_key = self.run_context_key(source_path, run_id)
            lock_path = REPO_ROOT / "artifacts" / "locks" / f"{context_key}.lock"
            artifact_path = REPO_ROOT / "artifacts" / run_id / "dry_run_summary.json"
            self.cleanup_run_dir(run_id)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text("held", encoding="utf-8")
            self.addCleanup(lambda: lock_path.unlink(missing_ok=True))

            result = self.run_dry_run(manifest_path)

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("run_context.locked", result.stdout)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("run_context.locked", diagnostic_codes)

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
            self.assertNotIn("legacy_xml_normalization", artifact)
            self.assertNotIn("cache", artifact)
            self.assertNotIn("findings", artifact)
            self.assertNotIn("patch_proposals", artifact)

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

    def test_dry_run_rejects_multiple_source_files_by_oss_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            first_source = tmp_path / "first.xml"
            second_source = tmp_path / "second.xml"
            first_source.write_text("<PlantModel />", encoding="utf-8")
            second_source.write_text("<PlantModel />", encoding="utf-8")

            run_id = "too-many-source-files"
            manifest_path = tmp_path / "manifest.json"
            manifest = {
                "schema_version": 1,
                "input": {"dexpi_xmls": [str(first_source), str(second_source)]},
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

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("workflow_policy.too_many_source_files", result.stdout)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("workflow_policy.too_many_source_files", diagnostic_codes)
            self.assertIsNone(artifact["structural_summary"])

    def test_dry_run_rejects_removed_review_only_execution_mode(self) -> None:
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
            self.assertIn("manifest.invalid_execution_mode", result.stdout)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("manifest.invalid_execution_mode", diagnostic_codes)

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
