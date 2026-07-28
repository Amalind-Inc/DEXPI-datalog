from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from hosted_env import fresh_principal

from pydexpi_datalog.web.review_api import create_review_api_app

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "TrainingTestCases" / "dexpi 1.3" / "example pids" / "E03 Pump With Nozzles" / "E03V01-VER.EX01.xml"


class RenderBundleApiTests(unittest.TestCase):
    def test_conditional_bundle_fetch_returns_304_without_session_overlays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_review_api_app(principal=fresh_principal(), artifact_root=Path(tmp)))
            prepared = client.post("/api/review/sessions/cache-session/prepare", json={"filename": FIXTURE.name, "content": FIXTURE.read_text()})
            self.assertEqual(prepared.status_code, 200)
            first = client.get("/api/review/sessions/cache-session/render-bundle")
            self.assertEqual(first.status_code, 200)
            etag = first.headers["etag"]
            self.assertNotIn("evidence_highlight", first.json()["render_data"])
            cached = client.get("/api/review/sessions/cache-session/render-bundle", headers={"If-None-Match": etag})
            self.assertEqual(cached.status_code, 304)
            second = client.post("/api/review/sessions/cache-session-two/prepare", json={"filename": FIXTURE.name, "content": FIXTURE.read_text()})
            self.assertEqual(second.status_code, 200)
            same_source = client.get("/api/review/sessions/cache-session-two/render-bundle")
            self.assertEqual(same_source.headers["etag"], etag)
            self.assertEqual(same_source.json(), first.json())
            self.assertNotIn("session_id", same_source.json()["render_data"])


if __name__ == "__main__":
    unittest.main()
