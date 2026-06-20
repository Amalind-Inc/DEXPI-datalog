from __future__ import annotations

import hashlib
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

    def cleanup_cache_path(self, cache_path: Path) -> None:
        if cache_path.exists():
            cache_path.unlink()
        self.addCleanup(lambda: cache_path.unlink(missing_ok=True))

    def source_hash(self, source_text: str) -> str:
        return hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    def run_context_key(self, source_path: Path, run_id: str) -> str:
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

    def test_dry_run_builds_and_persists_legacy_normalization_cache_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_text = "<PlantModel><Equipment id='P-101' tag='P-101'/></PlantModel>"
            source_path.write_text(source_text, encoding="utf-8")

            run_id = "cache-miss-run"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(manifest_path, source_path=source_path, run_id=run_id)

            source_hash = self.source_hash(source_text)
            artifact_path = REPO_ROOT / "artifacts" / run_id / "dry_run_summary.json"
            cache_path = REPO_ROOT / "artifacts" / "cache" / f"{source_hash}.json"
            self.cleanup_run_dir(run_id)
            self.cleanup_cache_path(cache_path)

            result = self.run_dry_run(manifest_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(
                artifact["cache"],
                {
                    "status": "miss",
                    "cache_key": source_hash,
                    "cache_path": str(cache_path.resolve()),
                },
            )
            self.assertTrue(cache_path.exists())

    def test_dry_run_reuses_cached_legacy_normalization_for_unchanged_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_text = "<PlantModel><Equipment id='P-101' tag='P-101'/></PlantModel>"
            source_path.write_text(source_text, encoding="utf-8")

            run_id = "cache-hit-run"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(manifest_path, source_path=source_path, run_id=run_id)

            source_hash = self.source_hash(source_text)
            artifact_path = REPO_ROOT / "artifacts" / run_id / "dry_run_summary.json"
            cache_path = REPO_ROOT / "artifacts" / "cache" / f"{source_hash}.json"
            self.cleanup_run_dir(run_id)
            self.cleanup_cache_path(cache_path)

            first_result = self.run_dry_run(manifest_path)
            self.assertEqual(first_result.returncode, 0, first_result.stderr)

            second_result = self.run_dry_run(manifest_path)

            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(
                artifact["cache"],
                {
                    "status": "hit",
                    "cache_key": source_hash,
                    "cache_path": str(cache_path.resolve()),
                },
            )

    def test_dry_run_does_not_reuse_cache_when_manifest_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_text = "<PlantModel><Equipment id='P-101' tag='P-101'/></PlantModel>"
            source_path.write_text(source_text, encoding="utf-8")

            source_hash = self.source_hash(source_text)
            cache_path = REPO_ROOT / "artifacts" / "cache" / f"{source_hash}.json"
            self.cleanup_cache_path(cache_path)

            valid_manifest_path = tmp_path / "valid-manifest.json"
            seed_run_id = "cache-seed-run"
            self.write_manifest(
                valid_manifest_path, source_path=source_path, run_id=seed_run_id
            )
            self.cleanup_run_dir(seed_run_id)

            seed_result = self.run_dry_run(valid_manifest_path)
            self.assertEqual(seed_result.returncode, 0, seed_result.stderr)
            self.assertTrue(cache_path.exists())

            invalid_run_id = "cache-invalid-manifest"
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
            self.assertIsNone(artifact["cache"])
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("manifest.invalid_integer", diagnostic_codes)

    def test_dry_run_invalidates_cache_when_source_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            initial_source_text = "<PlantModel><Equipment id='P-101' tag='P-101'/></PlantModel>"
            updated_source_text = (
                "<PlantModel>"
                "<Equipment id='P-101' tag='P-101'/>"
                "<Line id='L-1' tag='L-1'/>"
                "</PlantModel>"
            )
            source_path.write_text(initial_source_text, encoding="utf-8")

            run_id = "cache-invalidation-run"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(manifest_path, source_path=source_path, run_id=run_id)

            initial_hash = self.source_hash(initial_source_text)
            updated_hash = self.source_hash(updated_source_text)
            initial_cache_path = REPO_ROOT / "artifacts" / "cache" / f"{initial_hash}.json"
            updated_cache_path = REPO_ROOT / "artifacts" / "cache" / f"{updated_hash}.json"
            artifact_path = REPO_ROOT / "artifacts" / run_id / "dry_run_summary.json"
            self.cleanup_run_dir(run_id)
            self.cleanup_cache_path(initial_cache_path)
            self.cleanup_cache_path(updated_cache_path)

            first_result = self.run_dry_run(manifest_path)
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertTrue(initial_cache_path.exists())

            source_path.write_text(updated_source_text, encoding="utf-8")

            second_result = self.run_dry_run(manifest_path)

            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(
                artifact["cache"],
                {
                    "status": "miss",
                    "cache_key": updated_hash,
                    "cache_path": str(updated_cache_path.resolve()),
                },
            )
            self.assertTrue(updated_cache_path.exists())

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
            self.assertIsNone(artifact["cache"])
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
            self.assertEqual(
                artifact["legacy_xml_normalization"]["normalized_objects"],
                [
                    {
                        "object_id": "L-1",
                        "normalized_tag": "L-1",
                        "source_attributes": {"id": "L-1", "tag": "L-1"},
                        "diagnostics": [],
                    },
                    {
                        "object_id": "P-101",
                        "normalized_tag": "P-101",
                        "source_attributes": {
                            "id": "P-101",
                            "tag": "P-101",
                            "tag_variant_1": "P101",
                            "componentClass": "Pump",
                        },
                        "diagnostics": [
                            {
                                "code": "normalizer.ambiguous_normalized_tag",
                                "severity": "warning",
                                "message": "Normalized tag 'P-101' for object 'P-101' has an ambiguous raw variant 'P101'.",
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
