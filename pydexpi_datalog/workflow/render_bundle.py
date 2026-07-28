"""Immutable, source-versioned data required to render a prepared P&ID."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

RENDER_BUNDLE_SCHEMA_VERSION = "render-bundle.v1"

# These are the only topology fields whose values are immutable for a source
# revision. Session-specific selection and evidence overlays stay outside a
# digest-keyed bundle, so they cannot cross review-session boundaries.
_RENDER_DATA_FIELDS = (
    "nodes",
    "edges",
    "pid_view",
    "schematic_scene",
    "schematic_scene_kind",
    "geometry_report",
)


def build_render_bundle(*, source_bytes: bytes, topology: Mapping[str, Any]) -> dict[str, object]:
    """Return the stable rendering payload for one source revision.

    The caller owns storage and session overlays. Keeping this transformation
    pure makes it safe to reuse the resulting payload for every session with
    identical source bytes and renderer schema.
    """
    return {
        "schema_version": RENDER_BUNDLE_SCHEMA_VERSION,
        "source_digest": hashlib.sha256(source_bytes).hexdigest(),
        "render_data": {
            field: topology.get(field)
            for field in _RENDER_DATA_FIELDS
        },
    }
