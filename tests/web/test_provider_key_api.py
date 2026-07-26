"""Saving a model credential once, and having it there next time (bead 2afe.9).

The endpoints are the whole user-visible feature: a signed-in hosted user
saves a key on one device and finds it on the next. What matters as much as
that working is what must never happen -- the key coming back out of the API,
reaching another user, or landing in an artifact.

The last test here is the one that would have caught this bead shipping inert.
Everything above it would pass against a store that is written to and never
read; that one asserts the saved credential is what the model call carries.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from hosted_env import fresh_principal, hosted_catalog_env

from pydexpi_datalog.web.deployment import DeploymentProfile
from pydexpi_datalog.web.review_api import create_review_api_app
from pydexpi_datalog.workflow.principal import Principal

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


def _hosted_app(root: Path, principal: Principal):
    return create_review_api_app(
        artifact_root=root,
        principal=principal,
        profile=DeploymentProfile.HOSTED,
        env=hosted_catalog_env(),
    )


def _tool_call_response(answer: str) -> dict[str, object]:
    """An OpenAI-compatible reply that answers via the provide_answer tool."""

    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "provide_answer",
                                "arguments": json.dumps({"answer_text": answer}),
                            },
                        }
                    ],
                }
            }
        ]
    }


class HostedProviderKeyApiTests(unittest.TestCase):
    """What a signed-in user can do with their own keys."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "sessions"
        self.principal = fresh_principal("keys")
        self.client = TestClient(_hosted_app(self.root, self.principal))

    def test_a_saved_key_is_listed_back_for_its_owner(self) -> None:
        saved = self.client.put(
            "/api/provider-keys/openai",
            json={"model": "gpt-4.1", "credential": "sk-abcdefghijklmnop"},
        )
        self.assertEqual(200, saved.status_code, saved.text)

        listed = self.client.get("/api/provider-keys")
        self.assertEqual(200, listed.status_code, listed.text)
        [entry] = listed.json()["keys"]
        self.assertEqual("openai", entry["provider"])
        self.assertEqual("gpt-4.1", entry["model"])

    def test_no_response_ever_carries_the_key_itself(self) -> None:
        """The credential goes in and does not come out. Checked on every route."""

        credential = "sk-abcdefghijklmnop"
        responses = [
            self.client.put(
                "/api/provider-keys/openai",
                json={"model": "gpt-4.1", "credential": credential},
            ),
            self.client.get("/api/provider-keys"),
            self.client.delete("/api/provider-keys/openai"),
        ]
        for response in responses:
            with self.subTest(url=response.request.url):
                self.assertNotIn(credential, response.text)
                self.assertNotIn("abcdefghijklmnop", response.text)

    def test_the_listing_shows_enough_to_recognise_a_key(self) -> None:
        self.client.put(
            "/api/provider-keys/openai",
            json={"model": "gpt-4.1", "credential": "sk-abcdefghijklmnop"},
        )
        [entry] = self.client.get("/api/provider-keys").json()["keys"]
        self.assertEqual("sk-a…mnop", entry["hint"])

    def test_saving_again_replaces_the_key(self) -> None:
        for credential, model in (("sk-first-key", "gpt-4.1"), ("sk-second", "gpt-5.1")):
            self.client.put(
                "/api/provider-keys/openai",
                json={"model": model, "credential": credential},
            )
        [entry] = self.client.get("/api/provider-keys").json()["keys"]
        self.assertEqual("gpt-5.1", entry["model"])

    def test_deleting_a_key_removes_it(self) -> None:
        self.client.put(
            "/api/provider-keys/openai",
            json={"model": "gpt-4.1", "credential": "sk-abcdefghijklmnop"},
        )
        deleted = self.client.delete("/api/provider-keys/openai")
        self.assertEqual(200, deleted.status_code, deleted.text)
        self.assertEqual([], self.client.get("/api/provider-keys").json()["keys"])

    def test_deleting_a_key_that_was_never_saved_is_a_404(self) -> None:
        response = self.client.delete("/api/provider-keys/openai")
        self.assertEqual(404, response.status_code, response.text)

    def test_a_provider_outside_the_catalogue_is_refused(self) -> None:
        """Re-validated here, as every other credentialled payload is."""

        response = self.client.put(
            "/api/provider-keys/not-a-provider",
            json={"model": "gpt-4.1", "credential": "sk-abcdefghijklmnop"},
        )
        self.assertEqual(400, response.status_code, response.text)
        self.assertEqual([], self.client.get("/api/provider-keys").json()["keys"])

    def test_a_model_the_provider_does_not_offer_is_refused(self) -> None:
        response = self.client.put(
            "/api/provider-keys/openai",
            json={"model": "not-a-model", "credential": "sk-abcdefghijklmnop"},
        )
        self.assertEqual(400, response.status_code, response.text)
        self.assertEqual([], self.client.get("/api/provider-keys").json()["keys"])

    def test_an_empty_credential_is_refused(self) -> None:
        response = self.client.put(
            "/api/provider-keys/openai", json={"model": "gpt-4.1", "credential": "  "}
        )
        self.assertEqual(400, response.status_code, response.text)


class KeysBelongToOneUserTests(unittest.TestCase):
    """The isolation rule of the hosted epic, at the API."""

    def test_one_user_cannot_see_or_delete_another_users_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            alice, bob = fresh_principal("alice"), fresh_principal("bob")
            alice_client = TestClient(_hosted_app(root, alice))
            bob_client = TestClient(_hosted_app(root, bob))

            alice_client.put(
                "/api/provider-keys/openai",
                json={"model": "gpt-4.1", "credential": "sk-alices-own-key"},
            )

            listed = bob_client.get("/api/provider-keys")
            self.assertEqual([], listed.json()["keys"])
            self.assertNotIn("alices-own-key", listed.text)
            self.assertEqual(404, bob_client.delete("/api/provider-keys/openai").status_code)

            # Alice still has hers: Bob's delete found nothing to remove.
            self.assertEqual(1, len(alice_client.get("/api/provider-keys").json()["keys"]))


class LocalProfileKeepsKeysInTheBrowserTests(unittest.TestCase):
    """ADR 0014 still governs the local profile, and the API says so."""

    def test_the_local_profile_offers_no_server_side_key_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_review_api_app(
                artifact_root=Path(tmp) / "sessions",
                profile=DeploymentProfile.LOCAL,
            )
            client = TestClient(app)
            for call in (
                lambda: client.get("/api/provider-keys"),
                lambda: client.put(
                    "/api/provider-keys/openai",
                    json={"model": "gpt-4.1", "credential": "sk-abcdefghijklmnop"},
                ),
                lambda: client.delete("/api/provider-keys/openai"),
            ):
                response = call()
                with self.subTest(url=response.request.url, method=response.request.method):
                    self.assertEqual(404, response.status_code, response.text)
                    body = response.json()
                    self.assertEqual(
                        "provider_keys.not_in_this_profile", body["error"]["code"]
                    )
                    self.assertIn("browser", body["error"]["message"])


class AStoredKeyNeverReachesAnArtifactTests(unittest.TestCase):
    """A review writes a lot to storage. None of it may be the key.

    Audit records, turn records and traces all capture "which provider
    answered", and the settings dict they capture is one field away from the
    credential. This runs a review in which the stored key is genuinely in
    play -- the scripted provider never reads a credential, so a search of
    artifacts written under it would prove much less -- and then walks
    everything that landed in the bucket looking for it.
    """

    def test_no_artifact_written_during_a_review_contains_the_key(self) -> None:
        credential = "sk-or-unmistakable-canary-value"
        with tempfile.TemporaryDirectory() as tmp_dir, mock.patch("httpx.post") as post:
            post.return_value.raise_for_status = mock.Mock()
            post.return_value.json.return_value = _tool_call_response("Canary answer.")
            root = Path(tmp_dir) / "sessions"
            principal = fresh_principal("canary")
            app = create_review_api_app(
                artifact_root=root,
                principal=principal,
                profile=DeploymentProfile.HOSTED,
                env=hosted_catalog_env(),
                force_scripted_provider=False,
            )
            client = TestClient(app)
            saved = client.put(
                "/api/provider-keys/openrouter",
                json={"model": "openai/gpt-4.1", "credential": credential},
            )
            self.assertEqual(200, saved.status_code, saved.text)

            session_id = "canary-session"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(200, prepared.status_code, prepared.text)
            turn = client.post(
                f"/api/review/sessions/{session_id}/turns",
                json={"question": "What is reachable from the pump?", "request_id": "c1"},
            )
            self.assertEqual(200, turn.status_code, turn.text)
            self.assertTrue(post.called, "the key was never in play, so this proves little")

            # Straight to the bucket rather than through the store: the claim
            # is that nothing anywhere under this user's prefix holds the key,
            # and `ArtifactStore.list` is deliberately one level deep.
            written = _every_object(principal.workspace)
            self.assertGreater(
                len(written), 5, "too few artifacts to call this a search"
            )
            offenders = [key for key, body in written if credential.encode() in body]
            self.assertEqual([], offenders, "a stored credential reached an artifact")


def _every_object(prefix: str) -> list[tuple[str, bytes]]:
    """Every object under `prefix`, read whole. Small by construction here."""

    import boto3
    from botocore.config import Config

    env = hosted_catalog_env()
    client = boto3.client(
        "s3",
        endpoint_url=env["HARBORFIELD_S3_ENDPOINT_URL"] or None,
        aws_access_key_id=env["HARBORFIELD_S3_ACCESS_KEY_ID"] or None,
        aws_secret_access_key=env["HARBORFIELD_S3_SECRET_ACCESS_KEY"] or None,
        region_name=env["HARBORFIELD_S3_REGION"] or "us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = env["HARBORFIELD_S3_BUCKET"]
    found: list[tuple[str, bytes]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            found.append(
                (key, client.get_object(Bucket=bucket, Key=key)["Body"].read())
            )
    return found


class SavedKeysAreActuallyUsedTests(unittest.TestCase):
    """The test that stops this bead shipping as write-only plumbing.

    Every test above would pass against a store that is written to and never
    read. This one saves a key, never configures the session, and asserts the
    model call carries that key -- which is the feature: sign in on a new
    device and ask a question without re-entering anything.
    """

    def test_a_stored_key_is_what_the_model_call_carries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, mock.patch("httpx.post") as post:
            post.return_value.raise_for_status = mock.Mock()
            post.return_value.json.return_value = _tool_call_response(
                "From the stored key."
            )
            root = Path(tmp_dir) / "sessions"
            # Routing is this test's subject, so it opts out of the scripted
            # hermeticity switch. httpx.post is mocked: no real call.
            app = create_review_api_app(
                artifact_root=root,
                principal=fresh_principal("stored-key"),
                profile=DeploymentProfile.HOSTED,
                env=hosted_catalog_env(),
                force_scripted_provider=False,
            )
            client = TestClient(app)
            saved = client.put(
                "/api/provider-keys/openrouter",
                json={
                    "model": "openai/gpt-4.1",
                    "credential": "sk-or-stored-credential",
                },
            )
            self.assertEqual(200, saved.status_code, saved.text)

            session_id = "stored-key-session"
            prepared = client.post(
                f"/api/review/sessions/{session_id}/prepare",
                json={
                    "filename": "E06V01-VER.EX01.xml",
                    "content": E06_FIXTURE.read_text(encoding="utf-8"),
                },
            )
            self.assertEqual(200, prepared.status_code, prepared.text)

            # No provider-settings call: the point is that none is needed.
            turn = client.post(
                f"/api/review/sessions/{session_id}/turns",
                json={"question": "What is reachable from the pump?", "request_id": "r1"},
            )
            self.assertEqual(200, turn.status_code, turn.text)

            self.assertTrue(post.called, "the stored key was never used for a call")
            headers = post.call_args.kwargs["headers"]
            self.assertEqual(
                "Bearer sk-or-stored-credential", headers.get("Authorization")
            )


if __name__ == "__main__":
    unittest.main()
