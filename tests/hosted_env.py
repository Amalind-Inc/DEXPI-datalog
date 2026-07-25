"""The environment a hosted app needs before it will construct.

Shared by every test that builds a hosted `create_review_api_app`, whatever
ambient profile the suite is running under. The hosted profile refuses to
start without a shared libSQL catalog (bead 2afe.7, ADR 0016), so a real
server is a precondition of those tests rather than a detail inside them.

See `tests/conftest.py` for how to start one.
"""

from __future__ import annotations

import os
import unittest

LIBSQL_URL_ENV_VAR = "PYDEXPI_LIBSQL_URL"
LIBSQL_TOKEN_ENV_VAR = "PYDEXPI_LIBSQL_AUTH_TOKEN"


def hosted_catalog_env() -> dict[str, str]:
    """libSQL settings for a hosted app, or skip for want of a server."""

    url = os.environ.get(LIBSQL_URL_ENV_VAR, "").strip()
    if not url:
        raise unittest.SkipTest(
            f"the hosted profile needs {LIBSQL_URL_ENV_VAR}; see tests/conftest.py"
        )
    return {
        LIBSQL_URL_ENV_VAR: url,
        LIBSQL_TOKEN_ENV_VAR: os.environ.get(LIBSQL_TOKEN_ENV_VAR, ""),
    }
