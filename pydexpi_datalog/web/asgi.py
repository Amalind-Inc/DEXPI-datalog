from __future__ import annotations

import os
from pathlib import Path

from ..workflow.principal import resolve_local_principal
from .review_api import create_review_api_app


# Composition root for the local deployment profile: the principal is resolved
# once here and everything below scopes storage by its workspace (ADR 0016).
artifact_root = Path(
    os.environ.get("PYDEXPI_REVIEW_ARTIFACT_ROOT", ".tmp/review-sessions")
)
app = create_review_api_app(
    artifact_root=artifact_root,
    principal=resolve_local_principal(),
)
