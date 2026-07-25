"""Where review artifacts live, behind one interface.

Every artifact the review flow reads or writes -- prepared facts, topology
views, turn records, execution traces, exports, uploads, authored rule packs --
goes through an `ArtifactStore`. Callers name artifacts with a *key*: a
POSIX-style relative path such as ``"session-1/topology_view.json"``. They
never build an absolute path, never call `mkdir`, and never know whether the
bytes land on a disk or in a bucket.

The local implementation maps a key straight onto ``root / key``, preserving
the on-disk layout the filesystem-era code established, so an existing artifact
tree stays readable. The hosted profile (ADR 0016) adds an object-store
implementation later without touching a caller.

Keys are frequently derived from request data -- a session id from a URL --
so every key is validated for containment before it is resolved. A key that
tries to leave the workspace is rejected rather than clamped: silently
rewriting an escaping key would hide the attempt.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path, PurePosixPath
from typing import IO, Protocol, runtime_checkable


class ArtifactStoreError(Exception):
    """Base class for artifact store failures."""


class ArtifactNotFound(ArtifactStoreError):
    """A key was read that the store does not hold."""


class InvalidArtifactKey(ArtifactStoreError):
    """A key was absolute, empty, or tried to leave the workspace."""


def validate_key(key: str) -> PurePosixPath:
    """Return the key as a contained relative path, or refuse it.

    Rejects absolute keys, empty keys, and any key containing a `..` segment.
    `..` is refused even when it happens to resolve back inside the workspace
    (``a/../b``): the containment rule is easier to trust when it is about the
    key's shape rather than where it lands.
    """
    if not isinstance(key, str) or key.strip() == "":
        raise InvalidArtifactKey("artifact key must be a non-empty string")
    if key.startswith(("/", "\\")):
        raise InvalidArtifactKey(f"artifact key must be relative: {key!r}")
    pure = PurePosixPath(key)
    if pure.is_absolute():
        raise InvalidArtifactKey(f"artifact key must be relative: {key!r}")
    parts = pure.parts
    if any(part == ".." for part in parts):
        raise InvalidArtifactKey(f"artifact key must not traverse upwards: {key!r}")
    if not parts:
        raise InvalidArtifactKey("artifact key must be a non-empty string")
    return pure


@runtime_checkable
class ArtifactStore(Protocol):
    """The artifact operations the review flow needs."""

    def write_text(self, key: str, text: str) -> None:
        """Write text, creating any missing parents. Atomic."""

    def write_json(self, key: str, value: object) -> None:
        """Write a JSON artifact with the project's stable formatting. Atomic."""

    def read_text(self, key: str) -> str:
        """Read text. Raises `ArtifactNotFound` when the key is absent."""

    def read_json(self, key: str) -> object:
        """Read and parse a JSON artifact."""

    def read_bytes(self, key: str) -> bytes:
        """Read raw bytes."""

    def exists(self, key: str) -> bool:
        """Whether the store holds an artifact at this key."""

    def size(self, key: str) -> int:
        """Size of the artifact in bytes."""

    def list(self, prefix: str, *, suffix: str | None = None) -> list[str]:
        """Keys held directly under `prefix`, sorted, optionally suffix-filtered."""

    def copy(self, source_key: str, target_key: str) -> None:
        """Copy one artifact to another key, streaming rather than slurping."""

    def append_line(self, key: str, line: str) -> None:
        """Append one newline-terminated record to an append-only artifact."""

    def open_bytes(self, key: str) -> IO[bytes]:
        """Open the artifact for streaming reads."""

    def local_path(self, key: str) -> AbstractContextManager[Path]:
        """Yield a real filesystem path for third-party tools that demand one."""

    def local_dir(self, prefix: str) -> AbstractContextManager[Path]:
        """Yield a real directory for third-party tools that write into one."""


class LocalArtifactStore:
    """An `ArtifactStore` over a directory tree.

    A key maps to ``root / key``. The root is created lazily on first write, so
    a fresh workspace needs no setup step.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """The directory this store writes into.

        Exposed for composition and diagnostics. Callers that resolve keys
        through this instead of the key API are reintroducing the path
        arithmetic this class exists to remove.
        """
        return self._root

    def _resolve(self, key: str) -> Path:
        return self._root / validate_key(key)

    def write_text(self, key: str, text: str) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stage beside the target so the rename stays on one filesystem, then
        # replace: a reader either sees the previous artifact or the new one.
        handle, staging_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        staging = Path(staging_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
            staging.replace(path)
        except BaseException:
            staging.unlink(missing_ok=True)
            raise

    def write_json(self, key: str, value: object) -> None:
        self.write_text(key, json.dumps(value, indent=2, sort_keys=True))

    def read_text(self, key: str) -> str:
        path = self._resolve(key)
        try:
            return path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError) as error:
            raise ArtifactNotFound(key) from error

    def read_json(self, key: str) -> object:
        return json.loads(self.read_text(key))

    def read_bytes(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except (FileNotFoundError, IsADirectoryError) as error:
            raise ArtifactNotFound(key) from error

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def size(self, key: str) -> int:
        path = self._resolve(key)
        try:
            return path.stat().st_size
        except FileNotFoundError as error:
            raise ArtifactNotFound(key) from error

    def list(self, prefix: str, *, suffix: str | None = None) -> list[str]:
        base = self._resolve(prefix)
        if not base.is_dir():
            return []
        pure = validate_key(prefix)
        keys = [
            str(pure / entry.name)
            for entry in base.iterdir()
            if entry.is_file() and (suffix is None or entry.name.endswith(suffix))
        ]
        return sorted(keys)

    def copy(self, source_key: str, target_key: str) -> None:
        source = self._resolve(source_key)
        target = self._resolve(target_key)
        if not source.is_file():
            raise ArtifactNotFound(source_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def open_bytes(self, key: str) -> IO[bytes]:
        path = self._resolve(key)
        try:
            return path.open("rb")
        except (FileNotFoundError, IsADirectoryError) as error:
            raise ArtifactNotFound(key) from error

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        """Yield the artifact as a real file.

        pyDEXPI and Souffle are third-party and take filesystem paths, so this
        is the one place the storage abstraction is allowed to leak. Locally it
        is the artifact itself and costs nothing; an object-store
        implementation materialises a temporary copy and removes it on exit.
        Callers must treat the path as read-only and must not retain it.
        """
        path = self._resolve(key)
        if not path.is_file():
            raise ArtifactNotFound(key)
        yield path

    @contextmanager
    def local_dir(self, prefix: str) -> Iterator[Path]:
        """Yield a real directory a third-party writer can populate.

        The counterpart to `local_path`, for tools that take an output
        directory rather than a file (the DEXPI export pipeline). Locally this
        is the directory itself, so writes land exactly where the pre-store
        layout put them. An object-store implementation yields a temporary
        directory and uploads its contents on exit.
        """
        path = self._root / validate_key(prefix)
        path.mkdir(parents=True, exist_ok=True)
        yield path

    def append_line(self, key: str, line: str) -> None:
        """Append one newline-terminated record.

        Audit logs are append-only rather than rewritten, so a record cannot
        be lost to a concurrent overwrite. This is deliberately not atomic in
        the way `write_text` is: the guarantee is that a completed append is
        durable and ordered, not that the file has a single writer.
        """
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line if line.endswith("\n") else line + "\n")
