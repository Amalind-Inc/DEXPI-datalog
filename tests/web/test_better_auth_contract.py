"""The cross-language contract between Better Auth and the Python verifier.

Every other auth test signs its own tokens, which proves the verifier is
self-consistent but not that it agrees with the issuer. This one drives the
real Better Auth library, takes the tokens and JWKS it actually produces, and
verifies them with the real resolver.

That boundary spans two languages and two crypto libraries, and it is the kind
that breaks silently on a dependency upgrade -- Better Auth changing its
default signing algorithm, or the subject claim moving -- in a way no
same-language test would notice.

The suite runs without node installed: the test skips with a reason rather
than failing, and says exactly what is missing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import jwt

from pydexpi_datalog.web.hosted_auth import (
    HostedAuthSettings,
    HostedPrincipalResolver,
    TokenRejected,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
EMIT_SCRIPT = FRONTEND / "scripts" / "emit-test-tokens.mjs"


def _skip_reason() -> str | None:
    if shutil.which("node") is None:
        return "node is not installed: cannot drive the real Better Auth library"
    if not (FRONTEND / "node_modules" / "better-auth").is_dir():
        return "frontend dependencies are not installed: run `npm install` in frontend/"
    if not EMIT_SCRIPT.is_file():
        return f"missing {EMIT_SCRIPT.relative_to(REPO_ROOT)}"
    return None


class BetterAuthContractTests(unittest.TestCase):
    """Tokens minted by the issuer must be accepted by the resource server."""

    @classmethod
    def setUpClass(cls) -> None:
        reason = _skip_reason()
        if reason:
            raise unittest.SkipTest(reason)
        cls._tmp = tempfile.TemporaryDirectory()
        result = subprocess.run(
            ["node", str(EMIT_SCRIPT), cls._tmp.name],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            cls._tmp.cleanup()
            raise AssertionError(
                "could not mint Better Auth tokens:\n" + result.stdout + result.stderr
            )
        cls.data = json.loads(
            (Path(cls._tmp.name) / "tokens.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        tmp = getattr(cls, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def _resolver(self) -> HostedPrincipalResolver:
        keys = self.data["jwks"]["keys"]

        def key_for(token: str) -> object:
            kid = jwt.get_unverified_header(token)["kid"]
            for key in keys:
                if key["kid"] == kid:
                    return jwt.PyJWK(key).key
            raise KeyError(kid)

        base = self.data["baseURL"]
        return HostedPrincipalResolver(
            settings=HostedAuthSettings(
                issuer=base, audience=base, jwks_url=f"{base}/api/auth/jwks"
            ),
            key_resolver=key_for,
        )

    def test_a_real_token_resolves_a_principal(self) -> None:
        resolver = self._resolver()
        for user in self.data["users"]:
            with self.subTest(email=user["email"]):
                principal = resolver.principal_for(f"Bearer {user['token']}")
                self.assertEqual(principal.user_id, user["userId"])
                self.assertTrue(principal.workspace)

    def test_two_real_users_get_two_workspaces(self) -> None:
        resolver = self._resolver()
        workspaces = {
            resolver.principal_for(f"Bearer {user['token']}").workspace
            for user in self.data["users"]
        }
        self.assertEqual(len(workspaces), len(self.data["users"]))

    def test_a_tampered_real_token_is_rejected(self) -> None:
        resolver = self._resolver()
        genuine = self.data["users"][0]["token"]
        with self.assertRaises(TokenRejected):
            resolver.principal_for(f"Bearer {genuine[:-4]}AAAA")

    def test_the_issuer_signs_with_an_algorithm_we_accept(self) -> None:
        # The failure this catches: Better Auth changes its default key type on
        # an upgrade and every hosted request starts returning 401.
        from pydexpi_datalog.web.hosted_auth import ACCEPTED_ALGORITHMS

        for user in self.data["users"]:
            with self.subTest(email=user["email"]):
                header = jwt.get_unverified_header(user["token"])
                self.assertIn(header["alg"], ACCEPTED_ALGORITHMS)


if __name__ == "__main__":
    unittest.main()
