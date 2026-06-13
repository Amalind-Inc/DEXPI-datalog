from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class ReviewOnlyCliTests(unittest.TestCase):
    def write_manifest(
        self,
        manifest_path: Path,
        *,
        source_path: Path,
        rule_pack_path: Path,
        run_id: str,
        execution_mode: str = "review-only",
    ) -> None:
        manifest = {
            "schema_version": 1,
            "input": {"dexpi_xml": str(source_path)},
            "rule_pack": {
                "name": "pump-safety",
                "path": str(rule_pack_path),
                "version": 4,
                "lifecycle_state": "active",
            },
            "execution": {"mode": execution_mode},
            "output": {"run_id": run_id},
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def write_rule_pack(self, rule_pack_path: Path) -> None:
        rule_pack_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "rule_id": "equipment-tag-present",
                            "severity": "informational",
                            "conditions": {
                                "all": [
                                    {
                                        "predicate": "has_tag",
                                        "args": {"object_ref": "trigger"},
                                    }
                                ]
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def write_invalid_rule_pack(self, rule_pack_path: Path) -> None:
        rule_pack_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "rule_id": "broken-rule",
                            "severity": "informational",
                            "conditions": {
                                "all": [
                                    {
                                        "predicate": "missing_predicate",
                                        "args": {"object_ref": "trigger"},
                                    }
                                ]
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def run_review_only(self, manifest_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pydexpi_datalog", "review-only", str(manifest_path)],
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

    def load_artifact_set(self, run_id: str) -> dict[str, object]:
        artifact_set_path = REPO_ROOT / "artifacts" / run_id / "artifact_set.json"
        return json.loads(artifact_set_path.read_text(encoding="utf-8"))

    def test_review_only_persists_raw_findings_with_evidence_and_no_patch_proposals(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101' tag='P-101' /></PlantModel>",
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            self.write_rule_pack(rule_pack_path)

            run_id = "review-only-run"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(
                manifest_path,
                source_path=source_path,
                rule_pack_path=rule_pack_path,
                run_id=run_id,
            )

            artifact_path = REPO_ROOT / "artifacts" / run_id / "review_only.json"
            self.cleanup_run_dir(run_id)

            result = self.run_review_only(manifest_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(artifact_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["run"]["status"], "ok")
            self.assertEqual(artifact["run"]["execution_mode"], "review-only")
            self.assertEqual(
                artifact["findings"],
                [
                    {
                        "rule_id": "equipment-tag-present",
                        "severity": "informational",
                        "affected_object_ids": ["P-101"],
                        "evidence_trail": {
                            "primary_rule": "equipment-tag-present",
                            "supporting_facts": [
                                {
                                    "predicate": "has_tag",
                                    "object_id": "P-101",
                                    "canonical_tag": "P-101",
                                }
                            ],
                        },
                    }
                ],
            )
            self.assertEqual(artifact["patch_proposals"], [])

    def test_review_only_console_output_is_rendered_from_persisted_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101' tag='P-101' /></PlantModel>",
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            self.write_rule_pack(rule_pack_path)

            run_id = "review-only-render"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(
                manifest_path,
                source_path=source_path,
                rule_pack_path=rule_pack_path,
                run_id=run_id,
            )

            artifact_path = REPO_ROOT / "artifacts" / run_id / "review_only.json"
            self.cleanup_run_dir(run_id)

            result = self.run_review_only(manifest_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            expected_console = "\n".join(
                [
                    "Review-Only Report",
                    "Status: ok",
                    f"Run ID: {run_id}",
                    "",
                    "Findings: 1",
                    "[informational] equipment-tag-present P-101",
                ]
            )
            self.assertEqual(result.stdout.strip(), expected_console)
            self.assertEqual(
                artifact["findings"][0]["rule_id"], "equipment-tag-present"
            )
            self.assertEqual(
                artifact["findings"][0]["affected_object_ids"], ["P-101"]
            )

    def test_review_only_rejects_non_review_only_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101' tag='P-101' /></PlantModel>",
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            self.write_rule_pack(rule_pack_path)

            run_id = "wrong-review-mode"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(
                manifest_path,
                source_path=source_path,
                rule_pack_path=rule_pack_path,
                run_id=run_id,
                execution_mode="dry-run",
            )

            artifact_path = REPO_ROOT / "artifacts" / run_id / "review_only.json"
            self.cleanup_run_dir(run_id)

            result = self.run_review_only(manifest_path)

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Status: failed", result.stdout)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("manifest.execution_mode_mismatch", diagnostic_codes)
            self.assertEqual(artifact["findings"], [])
            self.assertEqual(artifact["patch_proposals"], [])

    def test_review_only_persists_rule_pack_validation_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101' tag='P-101' /></PlantModel>",
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            self.write_invalid_rule_pack(rule_pack_path)

            run_id = "rule-pack-invalid"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(
                manifest_path,
                source_path=source_path,
                rule_pack_path=rule_pack_path,
                run_id=run_id,
            )

            artifact_path = REPO_ROOT / "artifacts" / run_id / "review_only.json"
            self.cleanup_run_dir(run_id)

            result = self.run_review_only(manifest_path)

            self.assertEqual(result.returncode, 1, result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("rule_pack.unknown_predicate", diagnostic_codes)
            self.assertEqual(artifact["findings"], [])
            self.assertEqual(artifact["patch_proposals"], [])

    def test_review_only_persists_artifact_set_with_stable_ids_and_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                (
                    "<PlantModel>"
                    "<Equipment id='P-101' tag='P-101' />"
                    "<Equipment id='P-102' tag='P-102' />"
                    "</PlantModel>"
                ),
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            self.write_rule_pack(rule_pack_path)

            run_id = "artifact-set-run"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(
                manifest_path,
                source_path=source_path,
                rule_pack_path=rule_pack_path,
                run_id=run_id,
            )

            run_artifact_dir = REPO_ROOT / "artifacts" / run_id
            artifact_path = run_artifact_dir / "review_only.json"
            artifact_set_path = run_artifact_dir / "artifact_set.json"
            self.cleanup_run_dir(run_id)

            result = self.run_review_only(manifest_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(artifact_path.exists())
            self.assertTrue(artifact_set_path.exists())

            artifact_set = self.load_artifact_set(run_id)
            self.assertEqual(artifact_set["run_id"], run_id)
            self.assertEqual(
                artifact_set["artifact_ids"],
                {
                    "manifest": f"{run_id}:manifest",
                    "review_only": f"{run_id}:review_only",
                },
            )
            self.assertEqual(
                artifact_set["artifacts"],
                [
                    {
                        "artifact_id": f"{run_id}:manifest",
                        "artifact_type": "manifest_copy",
                        "path": str((run_artifact_dir / "manifest.json").resolve()),
                    },
                    {
                        "artifact_id": f"{run_id}:review_only",
                        "artifact_type": "review_only",
                        "path": str(artifact_path.resolve()),
                    },
                ],
            )

    def test_review_only_console_groups_repeated_findings_while_artifact_keeps_records(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                (
                    "<PlantModel>"
                    "<Equipment id='P-101' tag='P-101' />"
                    "<Equipment id='P-102' tag='P-102' />"
                    "</PlantModel>"
                ),
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            self.write_rule_pack(rule_pack_path)

            run_id = "grouped-findings-run"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(
                manifest_path,
                source_path=source_path,
                rule_pack_path=rule_pack_path,
                run_id=run_id,
            )

            artifact_path = REPO_ROOT / "artifacts" / run_id / "review_only.json"
            self.cleanup_run_dir(run_id)

            result = self.run_review_only(manifest_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(len(artifact["findings"]), 2)
            self.assertEqual(
                artifact["findings"],
                [
                    {
                        "rule_id": "equipment-tag-present",
                        "severity": "informational",
                        "affected_object_ids": ["P-101"],
                        "evidence_trail": {
                            "primary_rule": "equipment-tag-present",
                            "supporting_facts": [
                                {
                                    "predicate": "has_tag",
                                    "object_id": "P-101",
                                    "canonical_tag": "P-101",
                                }
                            ],
                        },
                    },
                    {
                        "rule_id": "equipment-tag-present",
                        "severity": "informational",
                        "affected_object_ids": ["P-102"],
                        "evidence_trail": {
                            "primary_rule": "equipment-tag-present",
                            "supporting_facts": [
                                {
                                    "predicate": "has_tag",
                                    "object_id": "P-102",
                                    "canonical_tag": "P-102",
                                }
                            ],
                        },
                    },
                ],
            )
            expected_console = "\n".join(
                [
                    "Review-Only Report",
                    "Status: ok",
                    f"Run ID: {run_id}",
                    "",
                    "Findings: 2",
                    "2x [informational] equipment-tag-present examples: P-101, P-102",
                ]
            )
            self.assertEqual(result.stdout.strip(), expected_console)

    def test_failed_review_only_run_persists_categorized_failure_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101' tag='P-101' /></PlantModel>",
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            self.write_invalid_rule_pack(rule_pack_path)

            run_id = "failed-review-only-run"
            manifest_path = tmp_path / "manifest.json"
            self.write_manifest(
                manifest_path,
                source_path=source_path,
                rule_pack_path=rule_pack_path,
                run_id=run_id,
            )

            run_artifact_dir = REPO_ROOT / "artifacts" / run_id
            artifact_path = run_artifact_dir / "review_only.json"
            artifact_set_path = run_artifact_dir / "artifact_set.json"
            self.cleanup_run_dir(run_id)

            result = self.run_review_only(manifest_path)

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(artifact_path.exists())
            self.assertTrue(artifact_set_path.exists())

            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact_set = self.load_artifact_set(run_id)
            self.assertEqual(artifact["run"]["status"], "failed")
            self.assertEqual(artifact["failure"], {"category": "evaluation"})
            diagnostic_codes = {item["code"] for item in artifact["diagnostics"]}
            self.assertIn("rule_pack.unknown_predicate", diagnostic_codes)
            self.assertEqual(
                artifact_set["failure"],
                {
                    "category": "evaluation",
                    "artifact_id": f"{run_id}:review_only",
                },
            )


if __name__ == "__main__":
    unittest.main()
