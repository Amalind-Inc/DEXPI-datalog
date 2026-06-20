from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from pydexpi_datalog.suppressions import apply_suppressions


class SuppressionTests(unittest.TestCase):
    def raw_finding(self) -> dict[str, object]:
        return {
            "rule_id": "equipment-tag-present",
            "severity": "informational",
            "affected_object_ids": ["P-101"],
            "evidence_trail": {
                "primary_rule": "equipment-tag-present",
                "supporting_facts": [
                    {
                        "predicate": "has_tag",
                        "object_id": "P-101",
                        "normalized_tag": "P-101",
                    }
                ],
            },
        }

    def matching_waiver(self) -> dict[str, object]:
        return {
            "waiver_id": "WVR-001",
            "rule_id": "equipment-tag-present",
            "affected_object_id": "P-101",
            "rationale": "Reviewed and accepted for this run.",
        }

    def write_manifest(
        self, manifest_path: Path, *, source_path: Path, rule_pack_path: Path, run_id: str
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
            "execution": {"mode": "review-only"},
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

    def run_review_only(self, manifest_path: Path) -> subprocess.CompletedProcess[str]:
        repo_root = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [sys.executable, "-m", "pydexpi_datalog", "review-only", str(manifest_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_matching_waiver_suppresses_finding_while_preserving_raw_record(self) -> None:
        raw_finding = self.raw_finding()
        waiver = self.matching_waiver()

        suppression_result = apply_suppressions([raw_finding], [waiver])

        self.assertEqual(suppression_result.diagnostics, [])
        self.assertEqual(suppression_result.raw_findings, [raw_finding])
        self.assertEqual(suppression_result.suppressed_findings, [])
        self.assertEqual(
            suppression_result.suppression_records,
            [
                {
                    "waiver_id": "WVR-001",
                    "rule_id": "equipment-tag-present",
                    "affected_object_ids": ["P-101"],
                    "rationale": "Reviewed and accepted for this run.",
                }
            ],
        )

    def test_suppression_does_not_mutate_raw_finding_record(self) -> None:
        raw_finding = self.raw_finding()
        original_snapshot = self.raw_finding()
        waiver = self.matching_waiver()

        suppression_result = apply_suppressions([raw_finding], [waiver])

        self.assertEqual(raw_finding, original_snapshot)
        self.assertEqual(suppression_result.raw_findings[0], original_snapshot)

    def test_review_only_continues_to_surface_raw_findings_even_when_waiver_matches(
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
            manifest_path = tmp_path / "manifest.json"
            run_id = "review-only-waiver-boundary"
            self.write_manifest(
                manifest_path,
                source_path=source_path,
                rule_pack_path=rule_pack_path,
                run_id=run_id,
            )

            raw_finding = self.raw_finding()
            waiver = self.matching_waiver()

            suppression_result = apply_suppressions([raw_finding], [waiver])
            self.assertEqual(suppression_result.suppressed_findings, [])

            repo_root = Path(__file__).resolve().parents[1]
            run_artifact_dir = repo_root / "artifacts" / run_id
            if run_artifact_dir.exists():
                shutil.rmtree(run_artifact_dir)
            self.addCleanup(lambda: shutil.rmtree(run_artifact_dir, ignore_errors=True))

            result = self.run_review_only(manifest_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(
                (run_artifact_dir / "review_only.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                artifact["findings"],
                [raw_finding],
            )


if __name__ == "__main__":
    unittest.main()
