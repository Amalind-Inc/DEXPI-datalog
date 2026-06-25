from __future__ import annotations

import os
from pathlib import Path

from .review_api import create_review_api_app


artifact_root = Path(
    os.environ.get("PYDEXPI_REVIEW_ARTIFACT_ROOT", ".tmp/review-sessions")
)
app = create_review_api_app(artifact_root=artifact_root)
