"""One catalog contract, proven against both drivers (bead 2afe.7, ADR 0016).

The local profile talks to a SQLite file through the standard library; the
hosted profile talks to a remote libSQL server. ADR 0016 chose libSQL over
PostgreSQL precisely so that stays one dialect and one schema, but "same
dialect" is a claim, and an unchecked claim is how one profile quietly becomes
the only tested one.

So the tests below are written once and run against every driver. A driver
that needs different SQL, applies the schema differently, or orders rows
differently fails here rather than in the profile nobody runs locally.

The libSQL leg needs a real server; there is no in-process libSQL. Set
``PYDEXPI_LIBSQL_TEST_URL`` to one:

    docker run -d -p 8099:8080 ghcr.io/tursodatabase/libsql-server:latest
    PYDEXPI_LIBSQL_TEST_URL=http://127.0.0.1:8099 pytest tests/workflow/test_catalog_drivers.py

Unset, the libSQL leg skips and says so. In CI the variable is always set, and
a set-but-unreachable URL is an error rather than a skip -- a broken service
container has to look different from a passing run.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydexpi_datalog.workflow.session_catalog import (
    CATALOG_FILENAME,
    SessionCatalog,
    libsql_catalog,
    local_catalog,
)

LIBSQL_URL_ENV_VAR = "PYDEXPI_LIBSQL_TEST_URL"


@contextmanager
def _local_driver() -> Iterator[SessionCatalog]:
    with tempfile.TemporaryDirectory() as tmp:
        yield local_catalog(Path(tmp) / CATALOG_FILENAME)


@contextmanager
def _libsql_driver() -> Iterator[SessionCatalog]:
    """A catalog on the real libSQL server, isolated by a per-test workspace.

    One server is shared by the whole run, so tests cannot assume an empty
    table. Every test here scopes its rows to a fresh workspace instead, which
    is the isolation the catalog claims to provide anyway.
    """

    url = os.environ.get(LIBSQL_URL_ENV_VAR, "").strip()
    if not url:
        raise unittest.SkipTest(
            f"no libSQL server: set {LIBSQL_URL_ENV_VAR} to run this leg"
        )
    yield libsql_catalog(url=url, auth_token="")


DRIVERS = {"local-sqlite": _local_driver, "hosted-libsql": _libsql_driver}


def _workspace() -> str:
    return f"ws-{uuid.uuid4().hex[:12]}"


class CatalogContractTests(unittest.TestCase):
    """Behaviour every driver owes, whatever it talks to."""

    def _for_each_driver(self, check) -> None:
        ran = 0
        for name, driver in DRIVERS.items():
            with self.subTest(driver=name):
                with driver() as catalog:
                    check(catalog)
                ran += 1
        self.assertGreater(ran, 0, "no driver ran")

    def test_a_recorded_session_is_listed_back(self) -> None:
        def check(catalog: SessionCatalog) -> None:
            workspace = _workspace()
            recorded = catalog.record_preparation(
                workspace=workspace,
                session_id="s1",
                source_filename="E06.xml",
                artifact_prefix="alice/s1",
            )
            listed = catalog.list_sessions(workspace=workspace)
            self.assertEqual([recorded], listed)

        self._for_each_driver(check)

    def test_re_preparing_updates_in_place_and_keeps_the_first_time(self) -> None:
        """The listed time is when the session first existed, not last touched."""

        def check(catalog: SessionCatalog) -> None:
            workspace = _workspace()
            first = catalog.record_preparation(
                workspace=workspace,
                session_id="s1",
                source_filename="first.xml",
                artifact_prefix="p/s1",
                created_at="2026-01-01T00:00:00+00:00",
            )
            catalog.record_preparation(
                workspace=workspace,
                session_id="s1",
                source_filename="second.xml",
                artifact_prefix="p/s1",
                created_at="2026-06-06T00:00:00+00:00",
            )
            listed = catalog.list_sessions(workspace=workspace)
            self.assertEqual(1, len(listed), "re-preparing must not list twice")
            self.assertEqual("second.xml", listed[0].source_filename)
            self.assertEqual(first.created_at, listed[0].created_at)

        self._for_each_driver(check)

    def test_a_workspace_never_sees_another_workspace(self) -> None:
        def check(catalog: SessionCatalog) -> None:
            mine, theirs = _workspace(), _workspace()
            catalog.record_preparation(
                workspace=mine,
                session_id="shared-id",
                source_filename="mine.xml",
                artifact_prefix=f"{mine}/shared-id",
            )
            catalog.record_preparation(
                workspace=theirs,
                session_id="shared-id",
                source_filename="theirs.xml",
                artifact_prefix=f"{theirs}/shared-id",
            )
            listed = catalog.list_sessions(workspace=mine)
            self.assertEqual(["mine.xml"], [r.source_filename for r in listed])
            self.assertEqual([mine], [r.workspace for r in listed])

        self._for_each_driver(check)

    def test_sessions_are_listed_newest_first(self) -> None:
        def check(catalog: SessionCatalog) -> None:
            workspace = _workspace()
            for index, stamp in enumerate(
                ["2026-01-01T00:00:00+00:00", "2026-03-03T00:00:00+00:00"]
            ):
                catalog.record_preparation(
                    workspace=workspace,
                    session_id=f"s{index}",
                    source_filename=f"{index}.xml",
                    artifact_prefix=f"p/s{index}",
                    created_at=stamp,
                )
            listed = catalog.list_sessions(workspace=workspace)
            self.assertEqual(["1.xml", "0.xml"], [r.source_filename for r in listed])

        self._for_each_driver(check)

    def test_an_unknown_workspace_lists_nothing(self) -> None:
        def check(catalog: SessionCatalog) -> None:
            self.assertEqual([], catalog.list_sessions(workspace=_workspace()))

        self._for_each_driver(check)

    def test_the_schema_applies_twice_without_complaint(self) -> None:
        """Re-running migrations is what a redeploy does on every boot."""

        def check(catalog: SessionCatalog) -> None:
            workspace = _workspace()
            catalog.record_preparation(
                workspace=workspace,
                session_id="s1",
                source_filename="kept.xml",
                artifact_prefix="p/s1",
            )
            catalog.apply_schema()
            listed = catalog.list_sessions(workspace=workspace)
            self.assertEqual(["kept.xml"], [r.source_filename for r in listed])

        self._for_each_driver(check)


class LibsqlLegIsNotSilentlySkippedTests(unittest.TestCase):
    """A configured-but-broken server must not read as a pass.

    Skips are invisible in a green run. CI always sets the URL, so if it is
    set the leg has to actually execute; only an unset variable may skip.
    """

    def test_a_configured_server_is_reachable(self) -> None:
        url = os.environ.get(LIBSQL_URL_ENV_VAR, "").strip()
        if not url:
            self.skipTest(f"{LIBSQL_URL_ENV_VAR} unset: nothing claimed")
        catalog = libsql_catalog(url=url, auth_token="")
        workspace = _workspace()
        catalog.record_preparation(
            workspace=workspace,
            session_id="reachable",
            source_filename="reachable.xml",
            artifact_prefix=f"{workspace}/reachable",
        )
        self.assertEqual(1, len(catalog.list_sessions(workspace=workspace)))


if __name__ == "__main__":
    unittest.main()
