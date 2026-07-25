"""Turning a bearer token into a Principal, for the hosted profile only.

The hosted profile signs users in through an external identity provider and
resolves the `Principal` from a verified token (ADR 0016). This module is
deliberately provider-agnostic: it verifies an RS256 JWT against the issuer's
published JWKS, so Logto, Zitadel, Auth0, Clerk and anything else that speaks
OIDC differ only by configuration.

Two decisions here are security-shaped and worth stating.

**The workspace is derived, not taken.** The workspace is a storage path
segment, so using the token's subject verbatim would let the identity provider
choose our directory names -- real subjects include `auth0|abc`, bare URLs, and
in principle `..`. It is instead a digest of issuer and subject: always a safe
segment, stable for a given user, and different for the same subject id coming
from two different providers, which would otherwise hand one provider's user
another's artifacts.

**Every rejection is identical.** Expired, forged, wrong audience, absent --
the caller learns only that it was refused. Verification is purely
cryptographic and never consults storage, so it cannot leak whether a
workspace exists even by timing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import jwt

from ..workflow.principal import InvalidWorkspace, Principal

# RS256 only. Accepting whichever algorithm the token names is the classic JWT
# forgery: an attacker signs HS256 using the public key as the shared secret.
_ALGORITHMS = ["RS256"]

_BEARER_PREFIX = "Bearer "

# One message for every failure. See the module docstring.
_REJECTION = "the bearer token was not accepted"
WORKSPACE_DIGEST_LENGTH = 32

# Read only by the composition root, and only in the hosted profile.
HOSTED_AUTH_ENV_VARS = (
    "PYDEXPI_OIDC_ISSUER",
    "PYDEXPI_OIDC_AUDIENCE",
    "PYDEXPI_OIDC_JWKS_URL",
)


class HostedAuthNotConfigured(ValueError):
    """The hosted profile was selected without the settings to verify a token."""


class TokenRejected(Exception):
    """The request carried no usable identity. Deliberately uninformative."""

    def __init__(self) -> None:
        super().__init__(_REJECTION)


@dataclass(frozen=True)
class HostedAuthSettings:
    """Where tokens come from and who they must be addressed to."""

    issuer: str
    audience: str
    jwks_url: str


def hosted_auth_settings_from_env(env: Mapping[str, str]) -> HostedAuthSettings:
    """Identity settings for a hosted deployment, or refuse to start.

    Every missing setting is reported at once. An operator bringing a hosted
    instance up should learn the whole list from one failed boot rather than
    discovering it one restart at a time.
    """

    values = {name: env.get(name, "").strip() for name in HOSTED_AUTH_ENV_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise HostedAuthNotConfigured(
            "the hosted deployment profile verifies a bearer token on every "
            "request, so it cannot start without an identity provider. "
            f"Missing: {', '.join(missing)}."
        )
    issuer, audience, jwks_url = (values[name] for name in HOSTED_AUTH_ENV_VARS)
    return HostedAuthSettings(issuer=issuer, audience=audience, jwks_url=jwks_url)



def workspace_for(issuer: str, subject: str) -> str:
    """The storage scope for a subject at an issuer.

    Opaque on purpose: the subject is user-identifying and this value ends up
    in artifact paths. The catalog is where a workspace is mapped back to a
    person when support needs it.
    """

    digest = hashlib.sha256(f"{issuer}\n{subject}".encode())
    return digest.hexdigest()[:WORKSPACE_DIGEST_LENGTH]


class HostedPrincipalResolver:
    """Resolves the Principal for one hosted request, or refuses it."""

    def __init__(
        self,
        *,
        settings: HostedAuthSettings,
        key_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        """`key_resolver` maps a raw token to the key that should verify it.

        Injected so tests never reach a provider. The default resolves the key
        from the issuer's JWKS by the token's `kid`, with PyJWT's own caching.
        """

        self._settings = settings
        self._key_resolver = key_resolver or self._key_from_jwks
        self._jwks_client: jwt.PyJWKClient | None = None

    def _key_from_jwks(self, token: str) -> Any:
        if self._jwks_client is None:
            self._jwks_client = jwt.PyJWKClient(self._settings.jwks_url)
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def principal_for(self, authorization_header: str | None) -> Principal:
        """The signed-in user behind this request.

        Raises `TokenRejected` for every failure, with no detail about which.
        """

        token = self._bearer_token(authorization_header)
        claims = self._verified_claims(token)
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise TokenRejected
        try:
            return Principal(
                user_id=subject,
                workspace=workspace_for(self._settings.issuer, subject),
            )
        except InvalidWorkspace as error:  # pragma: no cover - digest is safe
            # Unreachable while the workspace is a hex digest, but a Principal
            # that failed its own validation must never be returned.
            raise TokenRejected from error

    def _bearer_token(self, header: str | None) -> str:
        if not header or not header.startswith(_BEARER_PREFIX):
            raise TokenRejected
        token = header[len(_BEARER_PREFIX) :].strip()
        if not token:
            raise TokenRejected
        return token

    def _verified_claims(self, token: str) -> dict[str, Any]:
        try:
            key = self._key_resolver(token)
            return jwt.decode(
                token,
                key=key,
                algorithms=_ALGORITHMS,
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception as error:
            # Every provider and library failure collapses to one answer: an
            # unreadable JWKS and a forged signature are the same event to the
            # caller. Narrowing this would start leaking which check failed.
            raise TokenRejected from error
