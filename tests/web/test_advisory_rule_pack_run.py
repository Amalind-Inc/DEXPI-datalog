from __future__ import annotations

import textwrap
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

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

ADVISORY_ONLY = textwrap.dedent(
    """\
    ---
    pack_id: advisory-walkthrough-pack
    version: 1
    title: Advisory Walkthrough Pack
    authoritative: false
    trust_notice: Advisory guidance only; not an authoritative standard.
    ---

    # Advisory Walkthrough Pack

    ## Isolation checklist

    Confirm isolation valves around major equipment.

    ## Relief review

    Walk relief paths before trusting engine outcomes.
    """
)


class AdvisoryOnlyRulePackRunTests(unittest.TestCase):
    def test_run_advisory_only_pack_returns_walkthrough_without_rule_outcomes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)

            created = client.post(
                "/api/rule-packs", json={"markdown": ADVISORY_ONLY}
            )
            self.assertEqual(created.status_code, 200, created.text)

            session_id = "advisory-run-session"
            prepare = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(prepare.status_code, 200, prepare.text)

            load = client.post(
                f"/api/review/sessions/{session_id}/rule-packs/"
                "advisory-walkthrough-pack/load"
            )
            self.assertEqual(load.status_code, 200, load.text)

            run = client.post(
                f"/api/review/sessions/{session_id}/rule-packs/"
                "advisory-walkthrough-pack/run"
            )
            self.assertEqual(run.status_code, 200, run.text)
            body = run.json()
            self.assertEqual(body["status"], "answered")
            self.assertEqual(body["mode"], "advisory_walkthrough")
            self.assertEqual(body["results"], [])
            walkthrough = body["walkthrough"]
            self.assertEqual(walkthrough["kind"], "advisory_pack_walkthrough")
            self.assertEqual(walkthrough["pack_id"], "advisory-walkthrough-pack")
            self.assertIn("advisory", walkthrough["disclaimer"].lower())
            self.assertIn(
                "not engine findings or rule evaluation outcomes",
                walkthrough["disclaimer"].lower(),
            )
            titles = [step["title"] for step in walkthrough["steps"]]
            self.assertEqual(titles, ["Isolation checklist", "Relief review"])
            for step in walkthrough["steps"]:
                self.assertEqual(step["kind"], "advisory_checklist_step")
                self.assertNotIn(
                    step.get("outcome"),
                    ("satisfied", "violated", "indeterminate"),
                )

            stored = client.get(
                f"/api/review/sessions/{session_id}/rule-pack-results"
            )
            self.assertEqual(stored.status_code, 200)
            self.assertEqual(stored.json()["results"], [])


if __name__ == "__main__":
    unittest.main()
