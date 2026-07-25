"""Suite-wide preconditions for the deployment profile under test.

The hosted profile keeps its session index in a shared libSQL database
(ADR 0016, bead 2afe.7). That is a real service, not a file, so running the
suite under `PYDEXPI_DEPLOYMENT_PROFILE=hosted` needs one to talk to:

    docker run -d -p 8099:8080 ghcr.io/tursodatabase/libsql-server:latest
    export PYDEXPI_LIBSQL_URL=http://127.0.0.1:8099

Without it, every hosted test fails identically on a missing setting. That is
correct behaviour and useless output, so a developer gets one clear skip
instead of several dozen copies of the same traceback.

CI is deliberately excluded from that mercy. There the server is a service
container and the variable is always set, so a missing database means the
workflow is broken -- and a broken workflow has to look different from a
passing one. Skipping there would turn the hosted leg back into the thing
ADR 0016 set out to prevent: a profile that reads green without running.
"""

from __future__ import annotations

import os

import pytest

_LIBSQL_URL_ENV_VAR = "PYDEXPI_LIBSQL_URL"
_PROFILE_ENV_VAR = "PYDEXPI_DEPLOYMENT_PROFILE"

_MISSING_DATABASE = (
    "The hosted profile needs a libSQL database and none is configured.\n\n"
    "    docker run -d -p 8099:8080 "
    "ghcr.io/tursodatabase/libsql-server:latest\n"
    "    export PYDEXPI_LIBSQL_URL=http://127.0.0.1:8099\n\n"
    "Or run the suite under the local profile, which needs no service:\n"
    "    PYDEXPI_DEPLOYMENT_PROFILE=local pytest -m 'not slow'"
)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip the hosted suite when its database is absent, outside CI."""

    del config
    profile = os.environ.get(_PROFILE_ENV_VAR, "").strip().lower()
    if profile != "hosted":
        return
    if os.environ.get(_LIBSQL_URL_ENV_VAR, "").strip():
        return
    if os.environ.get("CI", "").strip():
        # Fail loudly instead: in CI the database is supposed to be there.
        return

    skip = pytest.mark.skip(reason=_MISSING_DATABASE)
    for item in items:
        item.add_marker(skip)
