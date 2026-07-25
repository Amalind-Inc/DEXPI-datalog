"""The hosted profile's `ArtifactStore`, over S3-compatible object storage.

Bead 2afe.8, ADR 0016. Artifacts are the bulk of what a review produces --
prepared facts, topology views, turn records, traces, exports, uploads -- and
in a hosted deployment they cannot live on the instance: the next redeploy
throws that disk away, and a second instance never sees the first one's work.

Every key is written beneath the workspace prefix, so the prefix is the
isolation boundary rather than a naming convention. Keys are validated for
containment first (`validate_key`), which matters more here than locally: a
key that climbed out of the prefix would land in another user's artifacts
rather than merely outside a directory.

The store is S3-compatible rather than S3, configured by endpoint, so a
self-hoster can point it at MinIO, Cloudflare R2, or Backblaze B2 and a
managed deployment can point it at AWS. `boto3` is an optional dependency
imported by the factory, so a local install never pulls it in.

Two operations deserve their reasoning recorded, because object storage does
not offer them and the local implementation does:

`append_line` is read-modify-write. Objects are immutable, so there is no
append. This is honest about the cost -- the audit artifacts it serves are
small and written once per turn -- but it is not safe against two concurrent
writers, which is the same guarantee the local implementation documents.

`local_dir` downloads the prefix, yields a real directory, and uploads what
changed on exit. Third-party tools (the DEXPI export pipeline) take an output
directory and there is no way to hand them a bucket.
"""

from __future__ import annotations

import io
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any

from .artifact_store import ArtifactNotFound, validate_key

BOTO3_MISSING = (
    "The hosted profile stores artifacts in object storage, which needs the "
    "optional `boto3` dependency: install it with "
    "`pip install 'pydexpi-datalog[hosted]'`. The local profile does not "
    "need it."
)

# Read only by the composition root, and only in the hosted profile.
HOSTED_STORAGE_ENV_VARS = (
    "PYDEXPI_S3_BUCKET",
    "PYDEXPI_S3_ENDPOINT_URL",
    "PYDEXPI_S3_ACCESS_KEY_ID",
    "PYDEXPI_S3_SECRET_ACCESS_KEY",
    "PYDEXPI_S3_REGION",
)


@dataclass(frozen=True)
class S3Settings:
    """Which bucket the hosted profile writes artifacts to."""

    bucket: str
    endpoint_url: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    region: str = "us-east-1"


def build_s3_client(settings: S3Settings) -> Any:
    """An S3 client for `settings`.

    Path-style addressing is forced. Virtual-host addressing puts the bucket
    in the hostname, which needs DNS the deployment does not control, so a
    MinIO or R2 endpoint would resolve to nothing.
    """

    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError as error:  # pragma: no cover - install-shaped
        raise ModuleNotFoundError(BOTO3_MISSING) from error

    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url or None,
        aws_access_key_id=settings.access_key_id or None,
        aws_secret_access_key=settings.secret_access_key or None,
        region_name=settings.region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


class S3ArtifactStore:
    """An `ArtifactStore` over an S3-compatible bucket, scoped to a prefix."""

    def __init__(self, *, client: Any, bucket: str, prefix: str) -> None:
        self._client = client
        self._bucket = bucket
        # The workspace prefix. Normalised without a trailing slash so key
        # composition has exactly one form.
        self._prefix = prefix.strip("/")
        if not self._prefix:
            raise ValueError("an object-store workspace prefix must not be empty")

    def _object_key(self, key: str) -> str:
        return f"{self._prefix}/{validate_key(key)}"

    def _missing(self, error: Exception) -> bool:
        """Whether a botocore error means "no such object"."""

        response = getattr(error, "response", None)
        if not isinstance(response, dict):
            return False
        code = str(response.get("Error", {}).get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in {"NoSuchKey", "404", "NotFound"} or status == 404

    def write_text(self, key: str, text: str) -> None:
        """Write text.

        Atomic without staging: a PUT either replaces the object or does not,
        so a reader never observes a partial write. The local implementation
        needs a temporary file to promise the same thing.
        """

        self._client.put_object(
            Bucket=self._bucket,
            Key=self._object_key(key),
            Body=text.encode("utf-8"),
            ContentType="application/json"
            if key.endswith(".json")
            else "text/plain; charset=utf-8",
        )

    def write_json(self, key: str, value: object) -> None:
        self.write_text(key, json.dumps(value, indent=2, sort_keys=True))

    def read_bytes(self, key: str) -> bytes:
        object_key = self._object_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        except Exception as error:  # noqa: BLE001 - botocore raises dynamic classes
            if self._missing(error):
                raise ArtifactNotFound(key) from error
            raise
        return bytes(response["Body"].read())

    def read_text(self, key: str) -> str:
        return self.read_bytes(key).decode("utf-8")

    def read_json(self, key: str) -> object:
        return json.loads(self.read_text(key))

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._object_key(key))
        except Exception as error:  # noqa: BLE001
            if self._missing(error):
                return False
            raise
        return True

    def size(self, key: str) -> int:
        try:
            head = self._client.head_object(
                Bucket=self._bucket, Key=self._object_key(key)
            )
        except Exception as error:  # noqa: BLE001
            if self._missing(error):
                raise ArtifactNotFound(key) from error
            raise
        return int(head["ContentLength"])

    def list(self, prefix: str, *, suffix: str | None = None) -> list[str]:
        """Keys directly under `prefix`, sorted.

        The delimiter is what keeps this from recursing: without it a bucket
        listing is depth-first over the whole subtree, and a caller counting
        results in one directory would silently count the tree.
        """

        pure = validate_key(prefix)
        search = f"{self._prefix}/{pure}/"
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(
            Bucket=self._bucket, Prefix=search, Delimiter="/"
        ):
            for entry in page.get("Contents", []):
                name = str(entry["Key"]).removeprefix(search)
                if not name or "/" in name:
                    continue
                if suffix is None or name.endswith(suffix):
                    keys.append(str(pure / name))
        return sorted(keys)

    def copy(self, source_key: str, target_key: str) -> None:
        source = self._object_key(source_key)
        if not self.exists(source_key):
            raise ArtifactNotFound(source_key)
        self._client.copy_object(
            Bucket=self._bucket,
            Key=self._object_key(target_key),
            CopySource={"Bucket": self._bucket, "Key": source},
        )

    def append_line(self, key: str, line: str) -> None:
        """Append one newline-terminated record.

        Read-modify-write, because objects are immutable. Like the local
        implementation this promises ordering and durability for a completed
        append, not safety against two concurrent writers.
        """

        record = line if line.endswith("\n") else line + "\n"
        try:
            existing = self.read_text(key)
        except ArtifactNotFound:
            existing = ""
        self.write_text(key, existing + record)

    def open_bytes(self, key: str) -> IO[bytes]:
        """Open the artifact for streaming reads.

        The body is buffered rather than handed over as the raw HTTP stream:
        a botocore stream holds a connection open until it is closed, and
        callers here treat this as an ordinary file object.
        """

        return io.BytesIO(self.read_bytes(key))

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        """Materialise the artifact as a real file, and remove it on exit."""

        data = self.read_bytes(key)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / PurePosixPath(validate_key(key)).name
            path.write_bytes(data)
            yield path

    @contextmanager
    def local_dir(self, prefix: str) -> Iterator[Path]:
        """Yield a real directory, then upload what it contains.

        Third-party writers (the DEXPI export pipeline) take an output
        directory. Existing objects under the prefix are downloaded first so
        a tool that reads what is already there behaves as it does locally,
        and everything present on exit is uploaded.
        """

        pure = validate_key(prefix)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dir"
            root.mkdir(parents=True, exist_ok=True)
            for existing in self._all_keys_beneath(str(pure)):
                target = root / PurePosixPath(existing).relative_to(pure)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.read_bytes(existing))
            yield root
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(root).as_posix()
                    self._client.put_object(
                        Bucket=self._bucket,
                        Key=f"{self._prefix}/{pure}/{relative}",
                        Body=path.read_bytes(),
                    )

    def _all_keys_beneath(self, prefix: str) -> list[str]:
        """Every key under `prefix`, at any depth. Unlike `list`, recursive."""

        pure = validate_key(prefix)
        search = f"{self._prefix}/{pure}/"
        paginator = self._client.get_paginator("list_objects_v2")
        found: list[str] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=search):
            for entry in page.get("Contents", []):
                name = str(entry["Key"]).removeprefix(search)
                if name:
                    found.append(str(pure / name))
        return sorted(found)

    def download_url(self, key: str, *, expires_in: int = 3600) -> str:
        """A presigned URL for the artifact's bytes.

        The URL is a capability for exactly one object and it expires, so it
        can be handed to a browser without the bytes passing through the API.

        Existence is deliberately not checked. Presigning is a signing
        operation needing no round trip, and callers use this to advertise
        where an artifact will live as often as to fetch one already there --
        preparation announces its outputs while it is still writing them. A
        URL for an object that never appears answers 404 when it is used,
        which is what an absent local path does too.
        """

        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": self._object_key(key)},
                ExpiresIn=expires_in,
            )
        )


def copy_tree_into_bucket(store: S3ArtifactStore, source: Path) -> None:
    """Upload a directory tree into the store, preserving relative keys.

    Used by migration and by tests that stage a fixture tree; kept here so a
    caller does not have to know how a key is composed.
    """

    for path in sorted(source.rglob("*")):
        if path.is_file():
            store.write_text(
                path.relative_to(source).as_posix(),
                path.read_text(encoding="utf-8"),
            )
