"""Behavioural contract for hosted-profile token verification.

The hosted profile resolves the Principal from a verified bearer token
(ADR 0016). Everything here is hermetic: a keypair is generated in-process and
the key lookup is injected, so no test reaches an identity provider and no
credential is needed to run the suite.

The rejection tests carry most of the weight. A verifier that accepts one
malformed token accepts every attacker who finds it, so the negative cases are
enumerated rather than sampled.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import unittest

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pydexpi_datalog.web.hosted_auth import (
    HOSTED_AUTH_ENV_VARS,
    HostedAuthNotConfigured,
    HostedAuthSettings,
    HostedPrincipalResolver,
    TokenRejected,
    hosted_auth_settings_from_env,
)

ISSUER = "https://issuer.example.com/"
AUDIENCE = "pydexpi-datalog"


def _keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class HostedAuthTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Key generation is slow enough to be worth doing once for the module.
        cls.key = _keypair()
        cls.other_key = _keypair()

    def _resolver(self) -> HostedPrincipalResolver:
        return HostedPrincipalResolver(
            settings=HostedAuthSettings(
                issuer=ISSUER, audience=AUDIENCE, jwks_url="https://unused.example"
            ),
            # Injected so the suite never makes a network call. Production
            # resolves the key from the provider's JWKS by `kid`.
            key_resolver=lambda _token: self.key.public_key(),
        )

    def _token(self, **overrides: object) -> str:
        claims: dict[str, object] = {
            "sub": "user-abc",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(time.time()) - 10,
            "exp": int(time.time()) + 300,
        }
        claims.update(overrides)
        key = overrides.pop("__key__", self.key)
        return jwt.encode(claims, key, algorithm="RS256")  # type: ignore[arg-type]


class AcceptedTokenTests(HostedAuthTestCase):
    def test_a_valid_token_resolves_a_principal(self) -> None:
        principal = self._resolver().principal_for(f"Bearer {self._token()}")
        self.assertEqual(principal.user_id, "user-abc")
        self.assertTrue(principal.workspace)

    def test_the_workspace_is_stable_for_the_same_subject(self) -> None:
        resolver = self._resolver()
        first = resolver.principal_for(f"Bearer {self._token()}")
        second = resolver.principal_for(f"Bearer {self._token(iat=int(time.time()))}")
        self.assertEqual(first.workspace, second.workspace)

    def test_different_subjects_get_different_workspaces(self) -> None:
        resolver = self._resolver()
        one = resolver.principal_for(f"Bearer {self._token(sub='user-one')}")
        two = resolver.principal_for(f"Bearer {self._token(sub='user-two')}")
        self.assertNotEqual(one.workspace, two.workspace)

    def test_a_subject_that_is_not_a_safe_path_segment_still_works(self) -> None:
        # Real providers mint subjects like "auth0|abc" or a bare URL. The
        # workspace is a storage path segment, so it cannot be the subject
        # verbatim without letting the provider choose our directory names.
        for subject in ("auth0|abc", "https://accounts.example/12345", "..", "a/b"):
            with self.subTest(subject=subject):
                principal = self._resolver().principal_for(
                    f"Bearer {self._token(sub=subject)}"
                )
                self.assertEqual(principal.user_id, subject)
                self.assertNotIn("/", principal.workspace)
                self.assertNotIn("\\", principal.workspace)
                self.assertNotIn("..", principal.workspace)

    def test_the_same_subject_from_a_different_issuer_is_a_different_workspace(
        self,
    ) -> None:
        # Two identity providers can both mint sub="12345". Deriving the
        # workspace from the subject alone would hand one provider's user the
        # other's artifacts.
        mine = self._resolver().principal_for(f"Bearer {self._token()}")
        other_issuer = "https://other.example.com/"
        theirs = HostedPrincipalResolver(
            settings=HostedAuthSettings(
                issuer=other_issuer, audience=AUDIENCE, jwks_url="https://unused"
            ),
            key_resolver=lambda _token: self.key.public_key(),
        ).principal_for(f"Bearer {self._token(iss=other_issuer)}")
        self.assertEqual(mine.user_id, theirs.user_id)
        self.assertNotEqual(mine.workspace, theirs.workspace)


class RejectedTokenTests(HostedAuthTestCase):
    def _assert_rejected(self, header: str | None) -> str:
        with self.assertRaises(TokenRejected) as caught:
            self._resolver().principal_for(header)
        return str(caught.exception)

    def test_a_missing_or_malformed_authorization_header_is_rejected(self) -> None:
        for header in (
            None,
            "",
            "   ",
            "Basic abc",
            "Bearer",
            "Bearer ",
            self._token(),  # bare token, no scheme
            f"bearer {self._token()}",  # scheme is case-sensitive per RFC 6750
        ):
            with self.subTest(header=header):
                self._assert_rejected(header)

    def test_an_expired_token_is_rejected(self) -> None:
        expired = self._token(exp=int(time.time()) - 1, iat=int(time.time()) - 600)
        self._assert_rejected(f"Bearer {expired}")

    def test_a_token_for_another_audience_is_rejected(self) -> None:
        self._assert_rejected(f"Bearer {self._token(aud='someone-else')}")

    def test_a_token_from_another_issuer_is_rejected(self) -> None:
        self._assert_rejected(f"Bearer {self._token(iss='https://evil.example/')}")

    def test_a_token_without_a_subject_is_rejected(self) -> None:
        self._assert_rejected(f"Bearer {self._token(sub='')}")

    def test_a_token_signed_by_an_unknown_key_is_rejected(self) -> None:
        forged = jwt.encode(
            {
                "sub": "user-abc",
                "iss": ISSUER,
                "aud": AUDIENCE,
                "exp": int(time.time()) + 300,
            },
            self.other_key,  # type: ignore[arg-type]
            algorithm="RS256",
        )
        self._assert_rejected(f"Bearer {forged}")

    def test_an_unsigned_token_is_rejected(self) -> None:
        # `alg: none` is the oldest JWT attack there is.
        unsigned = jwt.encode(
            {"sub": "user-abc", "iss": ISSUER, "aud": AUDIENCE}, None, algorithm="none"
        )
        self._assert_rejected(f"Bearer {unsigned}")

    def test_a_symmetric_token_signed_with_the_public_key_is_rejected(self) -> None:
        # Algorithm confusion: the attacker knows the public key, because it
        # is public, and signs HS256 with it hoping the verifier treats it as
        # a shared secret. Accepting whichever algorithm the token names is
        # the bug.
        #
        # The token is assembled by hand. PyJWT refuses to *encode* HS256 with
        # a PEM key, which is a good guardrail but not one the attacker is
        # bound by, so building this through the library would test PyJWT's
        # politeness rather than our verifier.
        public_pem = (
            self.key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("utf-8")
        )

        def b64(raw: bytes) -> bytes:
            return base64.urlsafe_b64encode(raw).rstrip(b"=")

        header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = b64(
            json.dumps(
                {
                    "sub": "user-abc",
                    "iss": ISSUER,
                    "aud": AUDIENCE,
                    "exp": int(time.time()) + 300,
                }
            ).encode()
        )
        signing_input = header + b"." + payload
        signature = b64(
            hmac.new(
                public_pem.encode(), signing_input, hashlib.sha256
            ).digest()
        )
        confused = (signing_input + b"." + signature).decode()

        # Sanity: the forgery is genuinely well-formed and correctly signed
        # under the public key, so a verifier that trusted the header's `alg`
        # would accept it. Checked with raw HMAC rather than PyJWT, which
        # refuses PEM as an HMAC secret on decode as well as on encode.
        self.assertTrue(
            hmac.compare_digest(
                signature,
                b64(
                    hmac.new(
                        public_pem.encode(), signing_input, hashlib.sha256
                    ).digest()
                ),
            )
        )
        self._assert_rejected(f"Bearer {confused}")

    def test_garbage_is_rejected(self) -> None:
        for value in ("Bearer not-a-token", "Bearer a.b.c", "Bearer " + "x" * 5000):
            with self.subTest(value=value[:20]):
                self._assert_rejected(value)

    def test_every_rejection_reads_the_same(self) -> None:
        # An expired token, a forged token, and a token for a workspace that
        # does not exist must be indistinguishable to the caller. Anything
        # else is an oracle.
        messages = {
            self._assert_rejected(None),
            self._assert_rejected("Bearer garbage"),
            self._assert_rejected(
                f"Bearer {self._token(exp=int(time.time()) - 1)}"
            ),
            self._assert_rejected(f"Bearer {self._token(aud='someone-else')}"),
            self._assert_rejected(f"Bearer {self._token(sub='nobody-has-this')}"[:-3]),
        }
        self.assertEqual(len(messages), 1, messages)


class HostedAuthConfigurationTests(unittest.TestCase):
    """A hosted deployment missing its identity settings must not boot.

    Starting anyway is the failure that matters: an unauthenticated hosted
    instance looks healthy while serving everyone from one workspace.
    """

    def _env(self) -> dict[str, str]:
        return {
            "PYDEXPI_OIDC_ISSUER": ISSUER,
            "PYDEXPI_OIDC_AUDIENCE": AUDIENCE,
            "PYDEXPI_OIDC_JWKS_URL": "https://issuer.example.com/jwks",
        }

    def test_a_complete_environment_produces_settings(self) -> None:
        settings = hosted_auth_settings_from_env(self._env())
        self.assertEqual(settings.issuer, ISSUER)
        self.assertEqual(settings.audience, AUDIENCE)

    def test_each_missing_setting_is_refused_by_name(self) -> None:
        for missing in HOSTED_AUTH_ENV_VARS:
            with self.subTest(missing=missing):
                env = self._env()
                del env[missing]
                with self.assertRaises(HostedAuthNotConfigured) as caught:
                    hosted_auth_settings_from_env(env)
                self.assertIn(missing, str(caught.exception))

    def test_a_blank_setting_counts_as_missing(self) -> None:
        env = self._env()
        env["PYDEXPI_OIDC_AUDIENCE"] = "   "
        with self.assertRaises(HostedAuthNotConfigured):
            hosted_auth_settings_from_env(env)

    def test_an_empty_environment_names_every_missing_setting_at_once(self) -> None:
        # One boot, one complete answer: an operator should not have to fix
        # and restart three times to learn three things.
        with self.assertRaises(HostedAuthNotConfigured) as caught:
            hosted_auth_settings_from_env({})
        for name in HOSTED_AUTH_ENV_VARS:
            self.assertIn(name, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
