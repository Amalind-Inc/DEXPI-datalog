"""The deployment entry point: one explicit profile, resolved once.

This is the only place that decides which deployment profile is running
(ADR 0016). It refuses to start without an answer, unlike the app factory it
calls, which defaults to local for library and test callers. The asymmetry is
deliberate: a script importing the factory should not need an environment, but
a served deployment guessing "local" would mean a hosted instance quietly
serving every user from one workspace with no sign-in.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..workflow.principal import resolve_local_principal
from .deployment import resolve_profile
from .review_api import create_review_api_app

# Composition root: the profile and the principal are resolved here and
# everything below scopes storage by the principal's workspace.
profile = resolve_profile(os.environ)
artifact_root = Path(
    os.environ.get("PYDEXPI_REVIEW_ARTIFACT_ROOT", ".tmp/review-sessions")
)
app = create_review_api_app(
    artifact_root=artifact_root,
    principal=resolve_local_principal(),
    profile=profile,
)
