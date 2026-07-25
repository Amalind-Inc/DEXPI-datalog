"""The deployment entry point: one explicit profile, resolved once.

This is the only place that decides which deployment profile is running
(ADR 0016). It refuses to start without an answer, unlike the app factory it
calls, which defaults to local for library and test callers. The asymmetry is
deliberate: a script importing the factory should not need an environment, but
a served deployment guessing "local" would mean a hosted instance quietly
serving every user from one workspace with no sign-in.

The same reasoning governs identity. In the hosted profile the identity
provider settings are required, so an instance missing them fails to boot
rather than coming up unauthenticated -- which would look healthy while
serving everyone from one workspace. The local profile reads none of them and
has no sign-in surface at all.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..workflow.principal import resolve_local_principal
from .deployment import DeploymentProfile, resolve_profile
from .hosted_auth import HostedPrincipalResolver, hosted_auth_settings_from_env
from .review_api import create_review_api_app

# Composition root: the profile and the identity seam are resolved here, and
# everything below scopes storage by the principal's workspace.
profile = resolve_profile(os.environ)
artifact_root = Path(
    os.environ.get("PYDEXPI_REVIEW_ARTIFACT_ROOT", ".tmp/review-sessions")
)

if profile is DeploymentProfile.HOSTED:
    # Many signed-in users per process: the owner is resolved per request from
    # a verified token, so no single principal is bound to the app.
    app = create_review_api_app(
        artifact_root=artifact_root,
        profile=profile,
        principal_resolver=HostedPrincipalResolver(
            settings=hosted_auth_settings_from_env(os.environ)
        ),
    )
else:
    # One operator per process, no accounts, no credentials.
    app = create_review_api_app(
        artifact_root=artifact_root,
        profile=profile,
        principal=resolve_local_principal(),
    )
