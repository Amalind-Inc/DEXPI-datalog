"""The environment a hosted app needs before it will construct.

Shared by every test that builds a hosted `create_review_api_app`, whatever
ambient profile the suite is running under. The hosted profile refuses to
start without a shared libSQL catalog (bead 2afe.7) and an object-storage
bucket (bead 2afe.8), so real services are a precondition of those tests
rather than a detail inside them.

See `tests/conftest.py` for how to start both.
"""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydexpi_datalog.workflow.principal import Principal

LIBSQL_URL_ENV_VAR = "PYDEXPI_LIBSQL_URL"
LIBSQL_TOKEN_ENV_VAR = "PYDEXPI_LIBSQL_AUTH_TOKEN"
S3_ENDPOINT_ENV_VAR = "PYDEXPI_S3_ENDPOINT_URL"
S3_BUCKET_ENV_VAR = "PYDEXPI_S3_BUCKET"


def hosted_catalog_env() -> dict[str, str]:
    """Everything a hosted app reads from the environment, or skip.

    Both backing services or neither: a test that got one and not the other
    would fail somewhere unrelated to what it is checking.
    """

    url = os.environ.get(LIBSQL_URL_ENV_VAR, "").strip()
    bucket = os.environ.get(S3_BUCKET_ENV_VAR, "").strip()
    if not url or not bucket:
        raise unittest.SkipTest(
            "the hosted profile needs a libSQL server and an object store; "
            "see tests/conftest.py"
        )
    return {
        LIBSQL_URL_ENV_VAR: url,
        LIBSQL_TOKEN_ENV_VAR: os.environ.get(LIBSQL_TOKEN_ENV_VAR, ""),
        S3_BUCKET_ENV_VAR: bucket,
        S3_ENDPOINT_ENV_VAR: os.environ.get(S3_ENDPOINT_ENV_VAR, ""),
        "PYDEXPI_S3_ACCESS_KEY_ID": os.environ.get("PYDEXPI_S3_ACCESS_KEY_ID", ""),
        "PYDEXPI_S3_SECRET_ACCESS_KEY": os.environ.get(
            "PYDEXPI_S3_SECRET_ACCESS_KEY", ""
        ),
        "PYDEXPI_S3_REGION": os.environ.get("PYDEXPI_S3_REGION", ""),
    }


def unique_workspace(kind: str = "ws") -> str:
    """A workspace nothing else in this run will touch.

    Locally a test gets isolation for free from a temporary directory. The
    hosted backends are shared and long-lived -- which is what a real
    deployment looks like -- so isolation has to come from the workspace, the
    same mechanism the product relies on to keep two users apart.
    """

    return f"{kind}-{uuid.uuid4().hex[:12]}"


def path_from_download_url(url: str) -> Path:
    """The local file a `file://` download URL names.

    Artifact locations are URLs in both profiles (bead 2afe.8). A local test
    that wants to look at the bytes on disk converts back here rather than
    treating the URL as a path, which silently yields `file:/...` as a
    relative filename.
    """

    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    if parsed.scheme != "file":
        raise AssertionError(f"expected a local file:// artifact URL, got {url!r}")
    return Path(unquote(parsed.path))


def fetch_download_url(url: str) -> str:
    """Read an artifact through the URL the API advertised.

    Works in both profiles, which is the point: locally the URL is
    `file://`, hosted it is a presigned object-store URL, and either way the
    bytes arrive without going through the application. A test that asserts
    the artifact is *reachable* says something true under both, where one
    asserting a filesystem path only ever describes local.
    """

    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        return response.read().decode("utf-8")


def fresh_principal(kind: str = "test") -> Principal:
    """A principal nothing else has used.

    Tests that go through the API get their isolation from the artifact root
    locally, and the hosted profile ignores that root by design: artifacts
    and authored packs live in a bucket that outlives the run. Without a
    fresh workspace, a second run of the suite meets what the first one left
    -- an authored pack that already exists, a session already listed.

    This is not a hosted-only concern dressed up as one. It is the product's
    real isolation mechanism, and using it here means the tests exercise the
    same boundary that keeps two signed-in users apart.
    """

    from pydexpi_datalog.workflow.principal import Principal

    name = unique_workspace(kind)
    return Principal(user_id=name, workspace=name)
