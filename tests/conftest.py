"""Suite-wide preconditions for the deployment profile under test.

The hosted profile keeps its session index in a shared libSQL database
(bead 2afe.7) and its artifacts in object storage (bead 2afe.8). Those are
real services, not files, so running the suite under
`HARBORFIELD_DEPLOYMENT_PROFILE=hosted` needs both:

    docker run -d -p 8099:8080 ghcr.io/tursodatabase/libsql-server:latest
    docker run -d -p 9100:9000 -e MINIO_ROOT_USER=minioadmin \\
        -e MINIO_ROOT_PASSWORD=minioadmin \\
        quay.io/minio/minio:latest server /data

    export HARBORFIELD_LIBSQL_URL=http://127.0.0.1:8099
    export HARBORFIELD_S3_ENDPOINT_URL=http://127.0.0.1:9100
    export HARBORFIELD_S3_BUCKET=pydexpi-test
    export HARBORFIELD_S3_ACCESS_KEY_ID=minioadmin
    export HARBORFIELD_S3_SECRET_ACCESS_KEY=minioadmin
    export HARBORFIELD_S3_TEST_ENDPOINT=$HARBORFIELD_S3_ENDPOINT_URL

Without them every hosted test fails identically on a missing setting. That
is correct behaviour and useless output, so a developer gets one clear skip
instead of several hundred copies of the same traceback.

CI is deliberately excluded from that mercy. There the services are
containers and the variables are always set, so a missing backend means the
workflow is broken -- and a broken workflow has to look different from a
passing run. Skipping there would turn the hosted leg back into the thing
ADR 0016 set out to prevent: a profile that reads green without running.
"""

from __future__ import annotations

import base64
import os

import pytest

_PROFILE_ENV_VAR = "HARBORFIELD_DEPLOYMENT_PROFILE"
_REQUIRED_HOSTED_ENV_VARS = ("HARBORFIELD_LIBSQL_URL", "HARBORFIELD_S3_BUCKET")
_BYOK_SECRET_ENV_VAR = "HARBORFIELD_BYOK_SECRET"
_TEST_BYOK_SECRET = base64.b64encode(b"pydexpi-test-secret-32-bytes!!!!").decode("ascii")

_MISSING_BACKENDS = (
    "The hosted profile needs a libSQL database and an object store, and at "
    "least one is not configured.\n\n"
    "    docker run -d -p 8099:8080 "
    "ghcr.io/tursodatabase/libsql-server:latest\n"
    "    docker run -d -p 9100:9000 -e MINIO_ROOT_USER=minioadmin \\\n"
    "        -e MINIO_ROOT_PASSWORD=minioadmin \\\n"
    "        quay.io/minio/minio:latest server /data\n\n"
    "    export HARBORFIELD_LIBSQL_URL=http://127.0.0.1:8099\n"
    "    export HARBORFIELD_S3_ENDPOINT_URL=http://127.0.0.1:9100\n"
    "    export HARBORFIELD_S3_BUCKET=pydexpi-test\n"
    "    export HARBORFIELD_S3_ACCESS_KEY_ID=minioadmin\n"
    "    export HARBORFIELD_S3_SECRET_ACCESS_KEY=minioadmin\n"
    "    export HARBORFIELD_S3_TEST_ENDPOINT=$HARBORFIELD_S3_ENDPOINT_URL\n\n"
    "Or run the suite under the local profile, which needs no service:\n"
    "    HARBORFIELD_DEPLOYMENT_PROFILE=local pytest -m 'not slow'"
)


def pytest_configure(config: pytest.Config) -> None:
    """Give the ambient hosted profile a key-encryption secret.

    A hosted app refuses to construct without `HARBORFIELD_BYOK_SECRET` (bead
    2afe.9), and unlike the databases it is configuration rather than a
    service: asking a developer to invent one before they can run the suite
    would be ceremony, and inventing a *different* one per run would make a
    saved credential unreadable on the next.

    Supplied, never defaulted in product code. That the refusal happens is
    itself under test, in `tests/web/test_provider_key_profiles.py`, so
    filling it in here cannot hide it.
    """

    del config
    os.environ.setdefault(_BYOK_SECRET_ENV_VAR, _TEST_BYOK_SECRET)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip the hosted suite when its backends are absent, outside CI."""

    del config
    profile = os.environ.get(_PROFILE_ENV_VAR, "").strip().lower()
    if profile != "hosted":
        return
    if all(os.environ.get(name, "").strip() for name in _REQUIRED_HOSTED_ENV_VARS):
        return
    if os.environ.get("CI", "").strip():
        # Fail loudly instead: in CI the backends are supposed to be there.
        return

    skip = pytest.mark.skip(reason=_MISSING_BACKENDS)
    for item in items:
        item.add_marker(skip)
