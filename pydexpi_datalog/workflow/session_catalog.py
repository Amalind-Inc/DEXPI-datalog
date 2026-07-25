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
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

CATALOG_FILENAME = "catalog.sqlite3"

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
    """SQLite-backed index of prepared sessions, scoped by workspace."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = RLock()
        self._ensure_schema()

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
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO review_session (
                    workspace, session_id, source_filename,
                    artifact_prefix, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (workspace, session_id) DO UPDATE SET
                    source_filename = excluded.source_filename,
                    artifact_prefix = excluded.artifact_prefix
                """,
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

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, workspace, source_filename,
                       artifact_prefix, created_at
                FROM review_session
                WHERE workspace = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (workspace,),
            ).fetchall()
        return [SessionRecord(*row) for row in rows]

    def _ensure_schema(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


def _now() -> str:
    return datetime.now(UTC).isoformat()
