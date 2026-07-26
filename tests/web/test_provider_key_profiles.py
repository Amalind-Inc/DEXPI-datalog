"""Which profile keeps provider keys, and what a missing secret does.

Bead 2afe.9, ADR 0014 and ADR 0016. The local profile has no server-side key
store, deliberately: a single operator on their own machine gains nothing
from a key table, and ADR 0014's reasoning still holds there. The hosted
profile has one, and refuses to start without a secret to encrypt with --
because the alternative failure is silent, and silently storing a credential
in the clear is the worst outcome this bead can produce.
"""

from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from pydexpi_datalog.web.deployment import (
    BYOK_SECRET_ENV_VAR,
    DeploymentProfile,
    HostedProviderKeysNotConfigured,
    bundle_for,
    hosted_provider_key_secret_from_env,
)
from pydexpi_datalog.workflow.provider_keys import SECRET_BYTES

GOOD_SECRET = base64.b64encode(b"k" * SECRET_BYTES).decode("ascii")


class SecretFromEnvironmentTests(unittest.TestCase):
    """A hosted deployment says what is wrong with its secret, at boot."""

    def test_a_valid_secret_is_decoded(self) -> None:
        secret = hosted_provider_key_secret_from_env({BYOK_SECRET_ENV_VAR: GOOD_SECRET})
        self.assertEqual(b"k" * SECRET_BYTES, secret)

    def test_a_missing_secret_refuses_to_start(self) -> None:
        with self.assertRaises(HostedProviderKeysNotConfigured) as caught:
            hosted_provider_key_secret_from_env({})
        message = str(caught.exception)
        self.assertIn(BYOK_SECRET_ENV_VAR, message)
        self.assertIn("openssl", message, "the message should say how to make one")

    def test_a_secret_of_the_wrong_length_refuses_to_start(self) -> None:
        """Caught at boot, not on the first user who tries to save a key."""

        with self.assertRaises(HostedProviderKeysNotConfigured) as caught:
            hosted_provider_key_secret_from_env(
                {BYOK_SECRET_ENV_VAR: base64.b64encode(b"short").decode("ascii")}
            )
        self.assertIn(str(SECRET_BYTES), str(caught.exception))

    def test_a_secret_that_is_not_base64_refuses_to_start(self) -> None:
        with self.assertRaises(HostedProviderKeysNotConfigured) as caught:
            hosted_provider_key_secret_from_env({BYOK_SECRET_ENV_VAR: "not base64!!"})
        self.assertIn("base64", str(caught.exception))

    def test_the_failure_never_quotes_the_secret(self) -> None:
        """A boot error lands in a log; the secret must not go with it."""

        leaked = base64.b64encode(b"z" * 8).decode("ascii")
        with self.assertRaises(HostedProviderKeysNotConfigured) as caught:
            hosted_provider_key_secret_from_env({BYOK_SECRET_ENV_VAR: leaked})
        self.assertNotIn(leaked, str(caught.exception))


class ProfilesDifferOnKeyStorageTests(unittest.TestCase):
    """The whole profile difference for this seam, read off the bundle."""

    def test_the_local_profile_has_no_server_side_key_store(self) -> None:
        """ADR 0014 still governs the local profile: keys stay in the browser."""

        bundle = bundle_for(DeploymentProfile.LOCAL)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(bundle.build_key_store(Path(tmp), {}))

    def test_the_hosted_profile_builds_a_store(self) -> None:
        bundle = bundle_for(DeploymentProfile.HOSTED)
        with tempfile.TemporaryDirectory() as tmp:
            store = bundle.build_key_store(
                Path(tmp),
                {
                    BYOK_SECRET_ENV_VAR: GOOD_SECRET,
                    "HARBORFIELD_LIBSQL_URL": _libsql_url(),
                },
            )
        self.assertIsNotNone(store)

    def test_the_hosted_profile_refuses_to_start_without_a_secret(self) -> None:
        """No fallback to plaintext, and no fallback to a generated key.

        A generated key would be worse than refusing: every instance would
        generate a different one, so a user's saved key would decrypt on the
        instance that stored it and nowhere else.
        """

        bundle = bundle_for(DeploymentProfile.HOSTED)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HostedProviderKeysNotConfigured):
                bundle.build_key_store(Path(tmp), {"HARBORFIELD_LIBSQL_URL": _libsql_url()})

    def test_the_hosted_store_does_not_touch_the_artifact_root(self) -> None:
        """The same rule as the catalog and the object store: no instance disk."""

        bundle = bundle_for(DeploymentProfile.HOSTED)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle.build_key_store(
                Path(tmp),
                {
                    BYOK_SECRET_ENV_VAR: GOOD_SECRET,
                    "HARBORFIELD_LIBSQL_URL": _libsql_url(),
                },
            )
            self.assertEqual([], list(root.iterdir()), "hosted wrote to the local disk")


def _libsql_url() -> str:
    import os

    url = os.environ.get("HARBORFIELD_LIBSQL_TEST_URL", "").strip()
    if not url:
        raise unittest.SkipTest("HARBORFIELD_LIBSQL_TEST_URL unset: nothing claimed")
    return url


if __name__ == "__main__":
    unittest.main()
