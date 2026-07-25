"""Two signed-in users must not be able to reach each other's work.

This is the acceptance test for the hosted profile's whole point. It drives
the real API over HTTP with real verified tokens, and asserts on what a user
can observe rather than on where bytes landed: a leak that a storage-layout
assertion would miss is still a leak.

Hermetic by construction -- the keypair is generated in-process and the key
lookup is injected, so no identity provider is contacted.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from pydexpi_datalog.web.deployment import DeploymentProfile
from pydexpi_datalog.web.hosted_auth import (
    HostedAuthSettings,
    HostedPrincipalResolver,
)
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

ISSUER = "https://issuer.example.com/"
AUDIENCE = "pydexpi-datalog"
ADVISORY_PACK = """---
pack_id: isolation-pack
version: 1
title: Isolation Pack
authoritative: false
trust_notice: Advisory only.
---

# Isolation Pack

## Checklist

Confirm isolation valves around major equipment.
"""


class HostedIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.fixture = E06_FIXTURE.read_text(encoding="utf-8")

    def _token(self, subject: str) -> str:
        return jwt.encode(
            {
                "sub": subject,
                "iss": ISSUER,
                "aud": AUDIENCE,
                "iat": int(time.time()) - 5,
                "exp": int(time.time()) + 300,
            },
            self.key,  # type: ignore[arg-type]
            algorithm="RS256",
        )

    def _hosted_app(self, root: Path):
        return create_review_api_app(
            artifact_root=root,
            profile=DeploymentProfile.HOSTED,
            principal_resolver=HostedPrincipalResolver(
                settings=HostedAuthSettings(
                    issuer=ISSUER, audience=AUDIENCE, jwks_url="https://unused"
                ),
                key_resolver=lambda _token: self.key.public_key(),
            ),
        )

    def _auth(self, subject: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token(subject)}"}

    def _prepare(self, client: TestClient, session_id: str, subject: str):
        return client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={"filename": "E06.xml", "content": self.fixture},
            headers=self._auth(subject),
        )

    def test_each_user_lists_only_their_own_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(self._hosted_app(Path(tmp) / "sessions"))

            self.assertEqual(
                self._prepare(client, "alice-session", "alice").status_code, 200
            )
            self.assertEqual(
                self._prepare(client, "bob-session", "bob").status_code, 200
            )

            for subject, expected in (("alice", "alice-session"), ("bob", "bob-session")):
                with self.subTest(subject=subject):
                    listed = client.get(
                        "/api/review/sessions", headers=self._auth(subject)
                    )
                    self.assertEqual(listed.status_code, 200, listed.text)
                    ids = [s["session_id"] for s in listed.json()["sessions"]]
                    self.assertEqual(ids, [expected])

    def test_one_user_cannot_read_another_users_session_by_guessing_its_id(
        self,
    ) -> None:
        # Session ids are client-minted and therefore guessable. Scoping that
        # relies on nobody typing the right id is not scoping.
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(self._hosted_app(Path(tmp) / "sessions"))
            self.assertEqual(
                self._prepare(client, "alice-session", "alice").status_code, 200
            )

            stolen = client.get(
                "/api/review/sessions/alice-session/topology",
                headers=self._auth("bob"),
            )
            self.assertNotEqual(stolen.status_code, 200)

    def test_authored_rule_packs_do_not_cross_users(self) -> None:
        # ADR 0016 calls the shared authored-pack directory out by name: an
        # author-confirmed rule is scoped to one user and must not be visible,
        # let alone trusted, by another.
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(self._hosted_app(Path(tmp) / "sessions"))
            created = client.post(
                "/api/rule-packs",
                json={"markdown": ADVISORY_PACK},
                headers=self._auth("alice"),
            )
            self.assertEqual(created.status_code, 200, created.text)

            for subject, expected in (("alice", 1), ("bob", 0)):
                with self.subTest(subject=subject):
                    listed = client.get("/api/rule-packs", headers=self._auth(subject))
                    self.assertEqual(listed.status_code, 200, listed.text)
                    authored = [
                        pack
                        for pack in listed.json()["packs"]
                        if pack.get("source") == "user"
                    ]
                    self.assertEqual(len(authored), expected)

    def test_an_unauthenticated_request_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(self._hosted_app(Path(tmp) / "sessions"))
            response = client.get("/api/review/sessions")
            self.assertEqual(response.status_code, 401)

    def test_a_rejected_token_looks_the_same_as_no_token(self) -> None:
        # The response must not reveal whether the token was expired, forged,
        # or simply absent, nor whether the workspace exists.
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(self._hosted_app(Path(tmp) / "sessions"))
            self.assertEqual(
                self._prepare(client, "alice-session", "alice").status_code, 200
            )

            expired = jwt.encode(
                {
                    "sub": "alice",
                    "iss": ISSUER,
                    "aud": AUDIENCE,
                    "exp": int(time.time()) - 1,
                },
                self.key,  # type: ignore[arg-type]
                algorithm="RS256",
            )
            responses = [
                client.get("/api/review/sessions"),
                client.get(
                    "/api/review/sessions", headers={"Authorization": "Bearer nonsense"}
                ),
                client.get(
                    "/api/review/sessions",
                    headers={"Authorization": f"Bearer {expired}"},
                ),
            ]
            self.assertEqual({r.status_code for r in responses}, {401})
            self.assertEqual(len({r.text for r in responses}), 1)


class LocalProfileNeedsNoCredentialsTests(unittest.TestCase):
    """The local profile has no sign-in surface at all -- not a stub."""

    def test_local_serves_without_any_authorization_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(
                create_review_api_app(
                    artifact_root=Path(tmp) / "sessions",
                    profile=DeploymentProfile.LOCAL,
                )
            )
            listed = client.get("/api/review/sessions")
            self.assertEqual(listed.status_code, 200, listed.text)

    def test_local_ignores_a_bearer_token_rather_than_honouring_it(self) -> None:
        # A token must not be able to select a workspace in a profile that has
        # no accounts: that would be a hosted feature leaking into local.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            client = TestClient(
                create_review_api_app(
                    artifact_root=root, profile=DeploymentProfile.LOCAL
                )
            )
            client.post(
                "/api/review/sessions/local-session/prepare",
                json={
                    "filename": "E06.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            with_token = client.get(
                "/api/review/sessions",
                headers={"Authorization": "Bearer whatever"},
            )
            self.assertEqual(with_token.status_code, 200)
            self.assertEqual(
                [s["session_id"] for s in with_token.json()["sessions"]],
                ["local-session"],
            )


if __name__ == "__main__":
    unittest.main()
