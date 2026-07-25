"""Where a hosted user's model-provider credentials live (bead 2afe.9).

ADR 0014 keeps bring-your-own-key credentials in the reviewer's own browser,
and for the local profile it still does: a single operator on their own
machine has nowhere better to put a key, and a server-side store there would
be a key table protecting nothing. This module is the hosted answer to the
same question. A signed-in user who saved a key on their laptop expects it on
their phone, and "expects it" is the whole feature.

The credential is encrypted before it reaches the database and decrypted only
to serve a request, so a database dump -- a backup, a snapshot, a support
query, a breach -- yields ciphertext. Encryption is AES-256-GCM with the
owning user and provider bound in as associated data, which means a row
copied to another user's name does not decrypt: the isolation rule survives
someone with write access to the table, not merely someone reading the API.

The store is one class over either driver, for the reason the session catalog
is one class over either driver: a second implementation is a second place
for the two profiles to drift apart.
"""

from __future__ import annotations

import base64
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PROVIDER_KEYS_FILENAME = "provider-keys.sqlite3"

SECRET_BYTES = 32
"""AES-256. Chosen over 128 because the cost is nil and the key is generated."""

_NONCE_BYTES = 12
"""What AES-GCM is specified for; a random nonce is safe at this key's volume."""

LIBSQL_MISSING = (
    "The hosted profile stores provider keys in libSQL, which is an optional "
    "dependency: install it with `pip install 'pydexpi-datalog[hosted]'`. "
    "The local profile does not need it."
)

# One schema, run by every driver. Idempotent: applying it is what a boot
# does, and a redeploy boots against a database that already exists.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_key (
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    hint TEXT NOT NULL,
    ciphertext TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    PRIMARY KEY (user_id, provider)
);
"""

_SAVE = """
INSERT INTO provider_key (user_id, provider, model, hint, ciphertext, saved_at)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (user_id, provider) DO UPDATE SET
    model = excluded.model,
    hint = excluded.hint,
    ciphertext = excluded.ciphertext,
    saved_at = excluded.saved_at
"""

_READ = """
SELECT ciphertext FROM provider_key WHERE user_id = ? AND provider = ?
"""

_LIST = """
SELECT provider, model, hint, saved_at
FROM provider_key
WHERE user_id = ?
ORDER BY provider
"""

_DELETE = "DELETE FROM provider_key WHERE user_id = ? AND provider = ?"


class ProviderKeyError(RuntimeError):
    """A stored credential could not be produced."""


class CorruptProviderKey(ProviderKeyError):
    """A row exists but does not decrypt under this deployment's secret.

    Separate from "absent" on purpose. A missing key means the user never
    saved one and should be asked to; a key that will not decrypt means the
    secret was rotated or the row was tampered with, and telling the user to
    re-enter their key would hide that.
    """


class KeyStoreConnection(Protocol):
    """The small part of DB-API this store depends on."""

    def execute(self, sql: str, parameters: Sequence[object] = ..., /) -> Any: ...

    def executescript(self, script: str, /) -> Any: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SavedProviderKey:
    """A saved credential as a settings page may see it.

    Deliberately carries no key material. Everything a caller needs to render
    a row -- which provider, which model, a recognisable fragment, when --
    without anything that could be used to make a request.
    """

    provider: str
    model: str
    hint: str
    saved_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "hint": self.hint,
            "saved_at": self.saved_at,
        }


def credential_hint(credential: str) -> str:
    """Enough of a key to recognise it, never enough to use it.

    Matches the browser's `maskCredential`, so the same key reads the same
    way whether it came from `localStorage` or from this store.
    """

    trimmed = credential.strip()
    if len(trimmed) <= 8:
        return "…"
    return f"{trimmed[:4]}…{trimmed[-4:]}"


class ProviderKeyStore:
    """Per-user provider credentials, encrypted at rest, over any driver."""

    def __init__(self, connect, secret: bytes) -> None:
        if len(secret) != SECRET_BYTES:
            raise ValueError(
                f"provider-key secret must be exactly {SECRET_BYTES} bytes, "
                f"got {len(secret)}"
            )
        self._connect = connect
        self._cipher = AESGCM(secret)
        self._lock = RLock()
        self.apply_schema()

    def apply_schema(self) -> None:
        """Bring the database up to the current schema."""

        with self._connection() as connection:
            connection.executescript(_SCHEMA)

    def save(
        self,
        *,
        user_id: str,
        provider: str,
        model: str,
        credential: str,
        saved_at: str | None = None,
    ) -> SavedProviderKey:
        """Store `credential` for this user and provider, replacing any prior one."""

        record = SavedProviderKey(
            provider=provider,
            model=model,
            hint=credential_hint(credential),
            saved_at=saved_at or _now(),
        )
        sealed = self._seal(user_id=user_id, provider=provider, credential=credential)
        with self._connection() as connection:
            connection.execute(
                _SAVE,
                (
                    user_id,
                    record.provider,
                    record.model,
                    record.hint,
                    sealed,
                    record.saved_at,
                ),
            )
        return record

    def credential(self, *, user_id: str, provider: str) -> str | None:
        """The usable key, or None when this user saved none for this provider."""

        with self._connection() as connection:
            row = connection.execute(_READ, (user_id, provider)).fetchone()
        if row is None:
            return None
        return self._open(user_id=user_id, provider=provider, sealed=row[0])

    def list_saved(self, *, user_id: str) -> list[SavedProviderKey]:
        """Every provider this user has a key for, with no key material."""

        with self._connection() as connection:
            rows = connection.execute(_LIST, (user_id,)).fetchall()
        return [SavedProviderKey(*row) for row in rows]

    def delete(self, *, user_id: str, provider: str) -> bool:
        """Forget this user's key for `provider`. True when one was there."""

        with self._connection() as connection:
            existed = connection.execute(_READ, (user_id, provider)).fetchone() is not None
            connection.execute(_DELETE, (user_id, provider))
        return existed

    def _seal(self, *, user_id: str, provider: str, credential: str) -> str:
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._cipher.encrypt(
            nonce, credential.encode("utf-8"), _associated_data(user_id, provider)
        )
        return base64.b64encode(nonce + sealed).decode("ascii")

    def _open(self, *, user_id: str, provider: str, sealed: str) -> str:
        try:
            raw = base64.b64decode(sealed.encode("ascii"), validate=True)
            return self._cipher.decrypt(
                raw[:_NONCE_BYTES],
                raw[_NONCE_BYTES:],
                _associated_data(user_id, provider),
            ).decode("utf-8")
        except (InvalidTag, ValueError, UnicodeDecodeError) as error:
            # The message names no user and quotes no bytes: this lands in a
            # log, and a log is one of the places this key must never be.
            raise CorruptProviderKey(
                f"a stored {provider} credential did not decrypt under this "
                f"deployment's PYDEXPI_BYOK_SECRET. The secret was rotated, or "
                f"the row was written by another deployment."
            ) from error

    @contextmanager
    def _connection(self) -> Iterator[KeyStoreConnection]:
        """A connection that commits on success and always closes."""

        with self._lock, closing(self._connect()) as connection:
            yield connection
            connection.commit()


def _associated_data(user_id: str, provider: str) -> bytes:
    """Bind the ciphertext to its owner and provider.

    AES-GCM authenticates this alongside the ciphertext without storing it,
    so a row copied into another user's name -- by someone with write access
    to the database, or by a bug in a query -- fails to decrypt rather than
    handing that user a working key.
    """

    return f"{user_id}\x00{provider}".encode()


def local_provider_keys(database_path: Path, *, secret: bytes) -> ProviderKeyStore:
    """A store in a SQLite file on this machine, using the standard library."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    return ProviderKeyStore(lambda: sqlite3.connect(database_path), secret=secret)


def libsql_provider_keys(*, url: str, auth_token: str, secret: bytes) -> ProviderKeyStore:
    """A store in a remote libSQL database, shared by every instance."""

    try:
        import libsql
    except ModuleNotFoundError as error:  # pragma: no cover - import guard
        raise ModuleNotFoundError(LIBSQL_MISSING) from error
    return ProviderKeyStore(
        lambda: libsql.connect(url, auth_token=auth_token), secret=secret
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
