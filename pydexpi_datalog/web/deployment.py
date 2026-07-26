"""Which deployment profile this process is, and what each one is built from.

PortLog ships two profiles from one codebase (ADR 0016). The `local`
profile keeps every artifact on the operator's machine with no accounts; the
`hosted` profile persists per-user work behind sign-in. The choice is made
once, here, at the composition root, and is invisible below it: no workflow,
verification, or QA module may branch on deployment mode.

The expected failure mode is skew -- hosted grows capability, the local path
rots into a demo, and the standalone product becomes theatre. Two things in
this module exist to make skew visible rather than gradual:

`ProfileBundle` names an implementation for every seam, per profile, as data.
Adding a seam means every profile must name something for it, so a hosted-only
capability cannot be introduced by simply not mentioning local.

`resolve_profile` refuses to guess. Defaulting would be dangerous in one
specific direction: a hosted deployment that forgot the setting would fall
back to a single shared workspace with no sign-in, which looks like it works.

This module lives under `web/` deliberately. Everything below the composition
root sits in `workflow/`, `verification/`, `qa/`, and `semantics/`, so those
layers importing it would be an upward dependency -- a layering violation a
test can see, rather than a convention a reviewer has to remember.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..workflow.artifact_store import ArtifactStore, LocalArtifactStore
from ..workflow.principal import Principal
from ..workflow.provider_keys import (
    SECRET_BYTES,
    ProviderKeyStore,
    libsql_provider_keys,
)
from ..workflow.s3_artifact_store import (
    HOSTED_STORAGE_ENV_VARS,
    S3ArtifactStore,
    S3Settings,
    build_s3_client,
)
from ..workflow.session_catalog import (
    CATALOG_FILENAME,
    SessionCatalog,
    libsql_catalog,
    local_catalog,
)

PROFILE_ENV_VAR = "HARBORFIELD_DEPLOYMENT_PROFILE"

# Read only by the hosted profile, and only when it builds its catalog.
HOSTED_CATALOG_ENV_VARS = (
    "HARBORFIELD_LIBSQL_URL",
    "HARBORFIELD_LIBSQL_AUTH_TOKEN",
)
_REQUIRED_CATALOG_ENV_VARS = ("HARBORFIELD_LIBSQL_URL",)


class DeploymentProfileError(ValueError):
    """The deployment profile is missing or is not one this build knows."""


class HostedCatalogNotConfigured(ValueError):
    """The hosted profile was selected without a catalog to write to."""


@dataclass(frozen=True)
class HostedCatalogSettings:
    """Which libSQL database the hosted profile indexes sessions in."""

    url: str
    auth_token: str


def hosted_catalog_settings_from_env(
    env: Mapping[str, str],
) -> HostedCatalogSettings:
    """Catalog settings for a hosted deployment, or refuse to start.

    The auth token is optional because the server, not this code, is the
    authority on whether it needs one: Turso issues tokens, while a
    `libsql-server` on a private network may accept anonymous clients.
    Refusing to start without a token would reject a deployment the database
    itself is happy to serve.
    """

    values = {name: env.get(name, "").strip() for name in HOSTED_CATALOG_ENV_VARS}
    missing = [name for name in _REQUIRED_CATALOG_ENV_VARS if not values[name]]
    if missing:
        raise HostedCatalogNotConfigured(
            "the hosted deployment profile keeps its session index in a "
            "shared libSQL database, so it cannot start without one: a local "
            "file would be lost the next time the instance is replaced. "
            f"Missing: {', '.join(missing)}."
        )
    return HostedCatalogSettings(
        url=values["HARBORFIELD_LIBSQL_URL"],
        auth_token=values["HARBORFIELD_LIBSQL_AUTH_TOKEN"],
    )


class HostedStorageNotConfigured(ValueError):
    """The hosted profile was selected without a bucket to write artifacts to."""


def hosted_storage_settings_from_env(env: Mapping[str, str]) -> S3Settings:
    """Object-storage settings for a hosted deployment, or refuse to start.

    Only the bucket is required. The endpoint is optional because an empty
    one means AWS S3 itself, and the credentials are optional because a
    deployment running with an instance role or IRSA has none to give --
    boto3's own credential chain is better at finding them than a
    reimplementation here would be.
    """

    values = {name: env.get(name, "").strip() for name in HOSTED_STORAGE_ENV_VARS}
    if not values["HARBORFIELD_S3_BUCKET"]:
        raise HostedStorageNotConfigured(
            "the hosted deployment profile keeps review artifacts in object "
            "storage, so it cannot start without a bucket: an instance disk "
            "is lost the next time the instance is replaced. "
            "Missing: HARBORFIELD_S3_BUCKET."
        )
    return S3Settings(
        bucket=values["HARBORFIELD_S3_BUCKET"],
        endpoint_url=values["HARBORFIELD_S3_ENDPOINT_URL"] or None,
        access_key_id=values["HARBORFIELD_S3_ACCESS_KEY_ID"] or None,
        secret_access_key=values["HARBORFIELD_S3_SECRET_ACCESS_KEY"] or None,
        region=values["HARBORFIELD_S3_REGION"] or "us-east-1",
    )


BYOK_SECRET_ENV_VAR = "HARBORFIELD_BYOK_SECRET"


class HostedProviderKeysNotConfigured(ValueError):
    """The hosted profile was selected without a secret to encrypt keys with."""


def hosted_provider_key_secret_from_env(env: Mapping[str, str]) -> bytes:
    """The key-encryption secret for a hosted deployment, or refuse to start.

    Required, with no fallback. Storing credentials in the clear is the
    obvious wrong answer; generating a secret per instance is the subtle one,
    because it looks like it works -- a user's key decrypts on the instance
    that stored it and nowhere else, so the bug appears only behind a load
    balancer, or only after a redeploy.

    The message never quotes the value. This raises at boot, boot errors are
    logged, and this particular value is the one thing in the deployment
    that must never reach a log.
    """

    raw = env.get(BYOK_SECRET_ENV_VAR, "").strip()
    advice = (
        f"Generate one with `openssl rand -base64 {SECRET_BYTES}` and set it "
        f"identically on every instance: a key saved by one instance must "
        f"decrypt on the next."
    )
    if not raw:
        raise HostedProviderKeysNotConfigured(
            f"the hosted deployment profile stores each user's model "
            f"credentials encrypted, so it cannot start without a secret to "
            f"encrypt them with. Missing: {BYOK_SECRET_ENV_VAR}. {advice}"
        )
    try:
        secret = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HostedProviderKeysNotConfigured(
            f"{BYOK_SECRET_ENV_VAR} is not valid base64. {advice}"
        ) from error
    if len(secret) != SECRET_BYTES:
        raise HostedProviderKeysNotConfigured(
            f"{BYOK_SECRET_ENV_VAR} must decode to exactly {SECRET_BYTES} "
            f"bytes, got {len(secret)}. {advice}"
        )
    return secret


class DeploymentProfile(StrEnum):
    """The deployment profiles this codebase ships."""

    LOCAL = "local"
    HOSTED = "hosted"


def resolve_profile(env: Mapping[str, str]) -> DeploymentProfile:
    """Read the profile from the environment, or refuse to start.

    Both an unset and an unrecognised value are errors. The message names the
    setting and every value this build accepts, because the reader is an
    operator looking at a failed boot, not someone with the source open.
    """

    raw = env.get(PROFILE_ENV_VAR, "").strip().lower()
    valid = ", ".join(profile.value for profile in DeploymentProfile)
    if not raw:
        raise DeploymentProfileError(
            f"{PROFILE_ENV_VAR} is not set. This deployment must say which "
            f"profile it is running: one of {valid}. There is no default: a "
            f"hosted deployment falling back to local would serve every user "
            f"from one workspace with no sign-in."
        )
    try:
        return DeploymentProfile(raw)
    except ValueError as error:
        raise DeploymentProfileError(
            f"{PROFILE_ENV_VAR}={raw!r} is not a deployment profile this "
            f"build knows. Valid profiles: {valid}."
        ) from error


def profile_from_env_or_default(
    env: Mapping[str, str], default: DeploymentProfile = DeploymentProfile.LOCAL
) -> DeploymentProfile:
    """Read the profile for a library caller, falling back to `default`.

    Unlike `resolve_profile`, an unset value is allowed: importing the app
    factory in a test or a script should not require an environment. A value
    that *is* set but unrecognised still raises. That asymmetry is the point --
    if a typo in CI quietly fell back to local, the run that claims to cover
    the other profile would be covering this one twice.
    """

    if not env.get(PROFILE_ENV_VAR, "").strip():
        return default
    return resolve_profile(env)


@dataclass(frozen=True)
class ProfileBundle:
    """The implementations one profile is composed from.

    Every seam that differs between profiles is a field here, so the whole
    difference between local and hosted is readable in one place. A seam
    added without a hosted answer will not construct.
    """

    profile: DeploymentProfile
    build_store: Callable[[Path, Principal, Mapping[str, str]], ArtifactStore]
    build_catalog: Callable[[Path, Mapping[str, str]], SessionCatalog]
    build_key_store: Callable[[Path, Mapping[str, str]], ProviderKeyStore | None]
    """Where users' model credentials live, or None when nowhere.

    The local profile answers None, which is the answer ADR 0014 gives: a
    single operator's keys stay in their browser. That is a real profile
    difference rather than an unbuilt seam, so it is stated here with the
    others instead of being discovered at a call site.
    """


def _local_store(
    artifact_root: Path,
    principal: Principal,
    env: Mapping[str, str] | None = None,
) -> ArtifactStore:
    """A directory tree under the principal's workspace."""

    del env
    return LocalArtifactStore(artifact_root / principal.workspace)


def _hosted_store(
    artifact_root: Path,
    principal: Principal,
    env: Mapping[str, str] | None = None,
) -> ArtifactStore:
    """A bucket prefix owned by the principal's workspace.

    The artifact root is ignored, for the reason the hosted catalog ignores
    it: an instance that fell back to its own disk would look healthy and
    lose every artifact at the next redeploy.
    """

    del artifact_root
    settings = hosted_storage_settings_from_env(env or {})
    return S3ArtifactStore(
        client=build_s3_client(settings),
        bucket=settings.bucket,
        prefix=principal.workspace,
    )


def _local_catalog(
    artifact_root: Path, env: Mapping[str, str] | None = None
) -> SessionCatalog:
    """One SQLite file holding every workspace's rows, scoped by column.

    The environment is accepted and ignored: a local deployment is configured
    by where it is run, not by what it is told.
    """

    del env
    return local_catalog(artifact_root / CATALOG_FILENAME)


def _hosted_catalog(
    artifact_root: Path, env: Mapping[str, str] | None = None
) -> SessionCatalog:
    """One libSQL database, shared by every instance of the deployment.

    The artifact root is ignored on purpose. A hosted catalog that fell back
    to the container's disk would look healthy right up to the redeploy that
    threw the disk away, so there is no path here that can write one.
    """

    del artifact_root
    settings = hosted_catalog_settings_from_env(env or {})
    return libsql_catalog(url=settings.url, auth_token=settings.auth_token)


def _no_key_store(
    artifact_root: Path, env: Mapping[str, str] | None = None
) -> ProviderKeyStore | None:
    """The local profile keeps no server-side credentials (ADR 0014).

    Not an omission. A key table on the operator's own machine would be
    protecting their key from themselves, while adding a secret to manage
    and a file to back up. The browser already holds it.
    """

    del artifact_root, env
    return None


def _hosted_key_store(
    artifact_root: Path, env: Mapping[str, str] | None = None
) -> ProviderKeyStore:
    """Encrypted per-user credentials in the shared libSQL database.

    Shares the catalog's database and its settings, because a deployment
    that has one has the other and a second connection string would be a
    second thing to get wrong. The artifact root is ignored for the reason
    it is everywhere else in this profile: nothing lands on the instance.
    """

    del artifact_root
    environment = env or {}
    settings = hosted_catalog_settings_from_env(environment)
    return libsql_provider_keys(
        url=settings.url,
        auth_token=settings.auth_token,
        secret=hosted_provider_key_secret_from_env(environment),
    )


_BUNDLES: dict[DeploymentProfile, ProfileBundle] = {
    DeploymentProfile.LOCAL: ProfileBundle(
        profile=DeploymentProfile.LOCAL,
        build_store=_local_store,
        build_catalog=_local_catalog,
        build_key_store=_no_key_store,
    ),
    DeploymentProfile.HOSTED: ProfileBundle(
        profile=DeploymentProfile.HOSTED,
        build_store=_hosted_store,
        build_catalog=_hosted_catalog,
        build_key_store=_hosted_key_store,
    ),
}


def bundle_for(profile: DeploymentProfile) -> ProfileBundle:
    """The implementations that make up `profile`."""

    return _BUNDLES[profile]
