from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

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

HYBRID_CANDIDATE_MARKDOWN = textwrap.dedent(
    """\
    ---
    pack_id: promote-slice-pack
    version: 1
    title: Promote slice pack
    authoritative: false
    trust_notice: Advisory guidance only until clauses are promoted.
    ---

    # Promote slice pack

    ## Pump presence

    The prepared diagram must include at least one CentrifugalPump.

    ## Fire relief adequacy

    Relief capacity must be adequate for the worst-case fire scenario.
    """
)


class PromoteFromAdvisoryVerticalSliceTests(unittest.TestCase):
    def test_ingest_promote_confirm_run_evidence_for_in_island_clause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)

            created = client.post(
                "/api/rule-packs", json={"markdown": HYBRID_CANDIDATE_MARKDOWN}
            )
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.json()["pack"]["rules"], [])

            abstain = client.post(
                "/api/rule-packs/promote-slice-pack/promote",
                json={"advisory_title": "Fire relief adequacy"},
            )
            self.assertEqual(abstain.status_code, 200, abstain.text)
            abstain_body = abstain.json()
            self.assertEqual(abstain_body["status"], "abstained")
            self.assertEqual(abstain_body["code"], "promote.outside_island")
            listed = client.get("/api/rule-packs")
            by_id = {p["pack_id"]: p for p in listed.json()["packs"]}
            self.assertEqual(by_id["promote-slice-pack"]["rules"], [])
            self.assertEqual(len(by_id["promote-slice-pack"]["advisory_guidance"]), 2)

            draft_resp = client.post(
                "/api/rule-packs/promote-slice-pack/promote",
                json={"advisory_title": "Pump presence"},
            )
            self.assertEqual(draft_resp.status_code, 200, draft_resp.text)
            draft_body = draft_resp.json()
            self.assertEqual(draft_body["status"], "draft")
            draft = draft_body["draft"]
            self.assertEqual(draft["trust"], "pending_author_confirmation")
            self.assertFalse(draft.get("authoritative", False))
            self.assertIn("plain_language_meaning", draft["restatement"])
            self.assertEqual(draft["executable_logic"]["disclosure"], "collapsed")
            self.assertIn(".decl rule_result", draft["executable_logic"]["content"])
            self.assertIn(
                draft["executable_logic"]["content"],
                # displayed == executed: confirm persists this exact fence
                draft["executable_logic"]["content"],
            )

            confirm = client.post(
                "/api/rule-packs/promote-slice-pack/promote/confirm",
                json={"draft": draft},
            )
            self.assertEqual(confirm.status_code, 200, confirm.text)
            confirmed = confirm.json()["pack"]
            self.assertEqual(confirmed["source"], "user")
            self.assertFalse(confirmed["authoritative"])
            self.assertEqual(len(confirmed["rules"]), 1)
            rule = confirmed["rules"][0]
            self.assertEqual(rule["rule_id"], draft["rule_id"])
            self.assertEqual(
                rule["executable_logic"]["content"],
                draft["executable_logic"]["content"],
            )
            self.assertEqual(rule["trust"], "author_confirmed")
            self.assertGreaterEqual(len(confirmed["advisory_guidance"]), 1)

            session_id = "promote-slice-session"
            prepare = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(prepare.status_code, 200, prepare.text)
            load = client.post(
                f"/api/review/sessions/{session_id}/rule-packs/promote-slice-pack/load"
            )
            self.assertEqual(load.status_code, 200, load.text)
            self.assertTrue(load.json()["skill_context"])

            run = client.post(
                f"/api/review/sessions/{session_id}/rule-packs/promote-slice-pack/run"
            )
            self.assertEqual(run.status_code, 200, run.text)
            run_body = run.json()
            self.assertEqual(run_body["mode"], "rule_evaluation")
            self.assertEqual(len(run_body["results"]), 1)
            result = run_body["results"][0]
            self.assertEqual(result["outcome"], "satisfied")
            self.assertIn("centrifugal pump", str(result["summary"]["text"]).lower())
            self.assertTrue(result["evidence"]["items"] or result["evidence_highlight"])
            self.assertFalse(result["pack"]["authoritative"])
            self.assertIn("walkthrough", run_body)
            for step in run_body["walkthrough"]["steps"]:
                self.assertEqual(step["kind"], "advisory_checklist_step")
                self.assertNotIn(
                    step.get("outcome"),
                    ("satisfied", "violated", "indeterminate"),
                )


if __name__ == "__main__":
    unittest.main()
