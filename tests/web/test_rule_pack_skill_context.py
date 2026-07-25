from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

# Every app here gets a fresh workspace. The hosted profile keeps authored
# packs and artifacts in a bucket that outlives the run, so a fixed
# workspace would meet the previous run's packs on the second pass
# (bead 2afe.8). Locally the temporary artifact root already isolates.
from hosted_env import fresh_principal

from pydexpi_datalog.web.review_api import create_review_api_app

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)

ADVISORY_A = textwrap.dedent(
    """\
    ---
    pack_id: skill-pack-a
    version: 1
    title: Skill Pack A
    authoritative: false
    trust_notice: Advisory only.
    ---

    # Skill Pack A

    ## Isolation checklist

    Confirm isolation valves around major equipment.
    """
)

ADVISORY_B = textwrap.dedent(
    """\
    ---
    pack_id: skill-pack-b
    version: 1
    title: Skill Pack B
    authoritative: false
    trust_notice: Advisory only.
    ---

    # Skill Pack B

    ## Relief review

    Walk relief paths before trusting engine outcomes.
    """
)


class AttachSkillContextTests(unittest.TestCase):
    def test_attach_injects_advisory_skill_context_without_rule_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(principal=fresh_principal(), artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)

            for markdown in (ADVISORY_A, ADVISORY_B):
                created = client.post("/api/rule-packs", json={"markdown": markdown})
                self.assertEqual(created.status_code, 200, created.text)

            session_id = "skill-context-session"
            prepare = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(prepare.status_code, 200, prepare.text)

            load_a = client.post(
                f"/api/review/sessions/{session_id}/rule-packs/skill-pack-a/load"
            )
            self.assertEqual(load_a.status_code, 200, load_a.text)
            body_a = load_a.json()
            self.assertTrue(body_a["loaded"])
            skill_a = body_a["skill_context"]
            self.assertEqual(
                [entry["pack_id"] for entry in skill_a],
                ["skill-pack-a"],
            )
            self.assertEqual(skill_a[0]["sections"][0]["title"], "Isolation checklist")
            self.assertIn("isolation valves", skill_a[0]["sections"][0]["body"].lower())

            results = client.get(
                f"/api/review/sessions/{session_id}/rule-pack-results"
            )
            self.assertEqual(results.status_code, 200)
            self.assertEqual(results.json()["results"], [])

            load_b = client.post(
                f"/api/review/sessions/{session_id}/rule-packs/skill-pack-b/load"
            )
            self.assertEqual(load_b.status_code, 200, load_b.text)
            skill_both = load_b.json()["skill_context"]
            self.assertEqual(
                [entry["pack_id"] for entry in skill_both],
                ["skill-pack-a", "skill-pack-b"],
            )

            unload_a = client.post(
                f"/api/review/sessions/{session_id}/rule-packs/skill-pack-a/unload"
            )
            self.assertEqual(unload_a.status_code, 200, unload_a.text)
            skill_left = unload_a.json()["skill_context"]
            self.assertEqual(
                [entry["pack_id"] for entry in skill_left],
                ["skill-pack-b"],
            )
            self.assertEqual(unload_a.json()["loaded"], False)
            self.assertEqual(unload_a.json()["pack_id"], "skill-pack-a")

            results_after = client.get(
                f"/api/review/sessions/{session_id}/rule-pack-results"
            )
            self.assertEqual(results_after.json()["results"], [])


if __name__ == "__main__":
    unittest.main()
