"""Which deployment profile this process is, and what each one is built from.

DEXPI-datalog ships two profiles from one codebase (ADR 0016). The `local`
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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..workflow.artifact_store import ArtifactStore, LocalArtifactStore
from ..workflow.principal import Principal
from ..workflow.session_catalog import CATALOG_FILENAME, SessionCatalog

PROFILE_ENV_VAR = "PYDEXPI_DEPLOYMENT_PROFILE"


class DeploymentProfileError(ValueError):
    """The deployment profile is missing or is not one this build knows."""


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
    build_store: Callable[[Path, Principal], ArtifactStore]
    build_catalog: Callable[[Path], SessionCatalog]


def _local_store(artifact_root: Path, principal: Principal) -> ArtifactStore:
    """A directory tree under the principal's workspace."""

    return LocalArtifactStore(artifact_root / principal.workspace)


def _local_catalog(artifact_root: Path) -> SessionCatalog:
    """One SQLite database holding every workspace's rows, scoped by column."""

    return SessionCatalog(artifact_root / CATALOG_FILENAME)


_BUNDLES: dict[DeploymentProfile, ProfileBundle] = {
    DeploymentProfile.LOCAL: ProfileBundle(
        profile=DeploymentProfile.LOCAL,
        build_store=_local_store,
        build_catalog=_local_catalog,
    ),
    # The hosted profile is wired but not yet distinct: its object-store
    # artifacts (bead pydexpi-datalog-1-2afe.8), libSQL catalog (2afe.7), and
    # verified-token principal (2afe.6) are not built. It names the local
    # implementations meanwhile, so the harness that runs the suite under both
    # profiles exists before the capabilities it has to keep honest. Replacing
    # a line here is what puts a hosted implementation under the whole suite.
    DeploymentProfile.HOSTED: ProfileBundle(
        profile=DeploymentProfile.HOSTED,
        build_store=_local_store,
        build_catalog=_local_catalog,
    ),
}


def bundle_for(profile: DeploymentProfile) -> ProfileBundle:
    """The implementations that make up `profile`."""

    return _BUNDLES[profile]
