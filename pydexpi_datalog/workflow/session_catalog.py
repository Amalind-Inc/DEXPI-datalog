"""Durable index of prepared review sessions.

A session's artifacts are stored under a session id the client mints and keeps
in browser storage. Losing that id orphans the artifacts: they remain on disk
but nothing can name them. The catalog is the index that keeps a session
findable, so "where did my review go?" has an answer in both deployment
profiles (ADR 0016).

The catalog is deliberately one database holding every workspace's rows behind
a ``workspace`` column, rather than one database per workspace: that is the
shape the hosted profile needs, and keeping it identical locally means one
schema and one migration path for both.

Two drivers reach that one schema. The local profile opens a SQLite file with
the standard library and needs nothing installed; the hosted profile opens a
remote libSQL database, which is SQLite's own dialect spoken over a network
(ADR 0016 chose it over PostgreSQL for exactly that reason). The SQL below is
written once and both drivers run it unchanged -- there is no dialect branch
to drift, because there is no second copy of the SQL to drift from.

``libsql`` is an optional dependency, imported inside the hosted factory. A
local install stays standard-library only, which matters because the wheel is
a native Rust extension that some platforms still have to compile.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

CATALOG_FILENAME = "catalog.sqlite3"

LIBSQL_MISSING = (
    "The hosted profile stores its catalog in libSQL, which is an optional "
    "dependency: install it with `pip install 'pydexpi-datalog[hosted]'`. "
    "The local profile does not need it."
)

# One schema, run by every driver. Idempotent on purpose: applying it is what
# a boot does, and a redeploy boots against a database that already exists.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_session (
    workspace TEXT NOT NULL,
    session_id TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    artifact_prefix TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace, session_id)
);
CREATE INDEX IF NOT EXISTS review_session_by_workspace
    ON review_session (workspace, created_at DESC);
"""

_RECORD_PREPARATION = """
INSERT INTO review_session (
    workspace, session_id, source_filename, artifact_prefix, created_at
)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (workspace, session_id) DO UPDATE SET
    source_filename = excluded.source_filename,
    artifact_prefix = excluded.artifact_prefix
"""

_LIST_SESSIONS = """
SELECT session_id, workspace, source_filename, artifact_prefix, created_at
FROM review_session
WHERE workspace = ?
ORDER BY created_at DESC, rowid DESC
"""


class CatalogConnection(Protocol):
    """The small part of DB-API this catalog depends on.

    Both drivers offer far more than this. Naming only what is used is what
    keeps a third driver a possibility rather than a rewrite.
    """

    def execute(self, sql: str, parameters: Sequence[object] = ..., /) -> Any: ...

    def executescript(self, script: str, /) -> Any: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


ConnectToCatalog = Callable[[], CatalogConnection]


@dataclass(frozen=True)
class SessionRecord:
    """One prepared review session, as the catalog remembers it."""

    session_id: str
    workspace: str
    source_filename: str
    artifact_prefix: str
    created_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "workspace": self.workspace,
            "source_filename": self.source_filename,
            "artifact_prefix": self.artifact_prefix,
            "created_at": self.created_at,
        }


class SessionCatalog:
    """Index of prepared sessions, scoped by workspace, over any driver."""

    def __init__(self, connect: ConnectToCatalog) -> None:
        self._connect = connect
        self._lock = RLock()
        self.apply_schema()

    def apply_schema(self) -> None:
        """Bring the database up to the current schema.

        Safe to run against a database that is already current, because that
        is the common case: every boot applies it.
        """

        with self._connection() as connection:
            connection.executescript(_SCHEMA)

    def record_preparation(
        self,
        *,
        workspace: str,
        session_id: str,
        source_filename: str,
        artifact_prefix: str,
        created_at: str | None = None,
    ) -> SessionRecord:
        """Remember a session that prepared successfully.

        Re-preparing the same session updates it in place rather than listing
        it twice, and keeps the original ``created_at`` so the recorded time
        stays the time the session first existed.
        """

        record = SessionRecord(
            session_id=session_id,
            workspace=workspace,
            source_filename=source_filename,
            artifact_prefix=artifact_prefix,
            created_at=created_at or _now(),
        )
        with self._connection() as connection:
            connection.execute(
                _RECORD_PREPARATION,
                (
                    record.workspace,
                    record.session_id,
                    record.source_filename,
                    record.artifact_prefix,
                    record.created_at,
                ),
            )
        return record

    def list_sessions(self, *, workspace: str) -> list[SessionRecord]:
        """Every session this workspace prepared, newest first."""

        with self._connection() as connection:
            rows = connection.execute(_LIST_SESSIONS, (workspace,)).fetchall()
        return [SessionRecord(*row) for row in rows]

    @contextmanager
    def _connection(self) -> Iterator[CatalogConnection]:
        """A connection that commits on success and always closes.

        Closing matters more here than it did for a local file: a hosted
        catalog is reached over the network, and a leaked connection there is
        a leaked socket.
        """

        with self._lock, closing(self._connect()) as connection:
            yield connection
            connection.commit()


def local_catalog(database_path: Path) -> SessionCatalog:
    """A catalog in a SQLite file on this machine, using the standard library."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    return SessionCatalog(lambda: sqlite3.connect(database_path))


def libsql_catalog(*, url: str, auth_token: str) -> SessionCatalog:
    """A catalog in a remote libSQL database.

    The import is deliberately inside the factory. A local deployment never
    calls this, and so never needs the package installed.
    """

    try:
        import libsql
    except ModuleNotFoundError as error:  # pragma: no cover - install-shaped
        raise ModuleNotFoundError(LIBSQL_MISSING) from error

    return SessionCatalog(lambda: libsql.connect(url, auth_token=auth_token))


def _now() -> str:
    return datetime.now(UTC).isoformat()
