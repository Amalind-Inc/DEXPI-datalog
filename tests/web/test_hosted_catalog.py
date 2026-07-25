"""The hosted profile's catalog is remote, and says so when it isn't configured.

Bead 2afe.7, ADR 0016. Two claims are worth pinning separately: that the
hosted profile actually reaches libSQL rather than quietly writing a local
file, and that the local profile is untouched by any of it.

The failure mode this guards is specific. A hosted deployment that silently
falls back to a SQLite file on the container's disk looks completely healthy
-- until the container is replaced and every session index disappears. So a
hosted profile without catalog settings refuses to start, in the same way and
for the same reason as one without identity settings.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path

from pydexpi_datalog.web.deployment import (
    HOSTED_CATALOG_ENV_VARS,
    DeploymentProfile,
    HostedCatalogNotConfigured,
    bundle_for,
    hosted_catalog_settings_from_env,
)

LIBSQL_URL_ENV_VAR = "PYDEXPI_LIBSQL_TEST_URL"


def _server_url() -> str:
    url = os.environ.get(LIBSQL_URL_ENV_VAR, "").strip()
    if not url:
        raise unittest.SkipTest(
            f"no libSQL server: set {LIBSQL_URL_ENV_VAR} to run this test"
        )
    return url


class HostedCatalogConfigurationTests(unittest.TestCase):
    """Missing settings are named, not guessed around."""

    def test_an_empty_environment_names_the_missing_setting(self) -> None:
        with self.assertRaises(HostedCatalogNotConfigured) as caught:
            hosted_catalog_settings_from_env({})
        self.assertIn("PYDEXPI_LIBSQL_URL", str(caught.exception))

    def test_a_blank_url_is_treated_as_missing(self) -> None:
        with self.assertRaises(HostedCatalogNotConfigured):
            hosted_catalog_settings_from_env({"PYDEXPI_LIBSQL_URL": "   "})

    def test_the_auth_token_is_optional(self) -> None:
        """A self-hosted libSQL server may legitimately run without one.

        Turso issues tokens; a `libsql-server` container on a private network
        need not. Requiring a token here would refuse a deployment the server
        itself accepts, so the server stays the authority on its own auth.
        """

        settings = hosted_catalog_settings_from_env(
            {"PYDEXPI_LIBSQL_URL": "libsql://example.invalid"}
        )
        self.assertEqual("libsql://example.invalid", settings.url)
        self.assertEqual("", settings.auth_token)

    def test_the_url_and_token_are_read_from_the_environment(self) -> None:
        settings = hosted_catalog_settings_from_env(
            {
                "PYDEXPI_LIBSQL_URL": "libsql://db.example.invalid",
                "PYDEXPI_LIBSQL_AUTH_TOKEN": "secret-token",
            }
        )
        self.assertEqual("libsql://db.example.invalid", settings.url)
        self.assertEqual("secret-token", settings.auth_token)

    def test_every_hosted_catalog_variable_is_documented_in_one_place(self) -> None:
        self.assertIn("PYDEXPI_LIBSQL_URL", HOSTED_CATALOG_ENV_VARS)


class HostedBundleTests(unittest.TestCase):
    """What the hosted profile is actually composed from."""

    def test_the_hosted_profile_refuses_to_build_a_catalog_unconfigured(self) -> None:
        bundle = bundle_for(DeploymentProfile.HOSTED)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HostedCatalogNotConfigured):
                bundle.build_catalog(Path(tmp), {})

    def test_the_hosted_profile_writes_to_libsql_not_to_disk(self) -> None:
        """The point of the bead: hosted rows leave the container."""

        url = _server_url()
        bundle = bundle_for(DeploymentProfile.HOSTED)
        workspace = f"ws-{uuid.uuid4().hex[:12]}"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = bundle.build_catalog(
                root, {"PYDEXPI_LIBSQL_URL": url, "PYDEXPI_LIBSQL_AUTH_TOKEN": ""}
            )
            catalog.record_preparation(
                workspace=workspace,
                session_id="s1",
                source_filename="hosted.xml",
                artifact_prefix=f"{workspace}/s1",
            )
            listed = catalog.list_sessions(workspace=workspace)
            self.assertEqual(["hosted.xml"], [r.source_filename for r in listed])
            # The row is on the server, so nothing was written under the root.
            self.assertEqual(
                [], sorted(p.name for p in root.rglob("*.sqlite3")),
                "hosted catalog must not leave a SQLite file on local disk",
            )

    def test_a_second_process_sees_the_first_process_rows(self) -> None:
        """Why remote at all: two app instances share one index."""

        url = _server_url()
        bundle = bundle_for(DeploymentProfile.HOSTED)
        env = {"PYDEXPI_LIBSQL_URL": url, "PYDEXPI_LIBSQL_AUTH_TOKEN": ""}
        workspace = f"ws-{uuid.uuid4().hex[:12]}"
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first = bundle.build_catalog(Path(one), env)
            first.record_preparation(
                workspace=workspace,
                session_id="shared",
                source_filename="shared.xml",
                artifact_prefix=f"{workspace}/shared",
            )
            # A different instance, a different disk, the same catalog.
            second = bundle.build_catalog(Path(two), env)
            listed = second.list_sessions(workspace=workspace)
            self.assertEqual(["shared.xml"], [r.source_filename for r in listed])


class LocalProfileIsUntouchedTests(unittest.TestCase):
    """The local profile gained no dependency and no configuration."""

    def test_the_local_catalog_ignores_libsql_settings_entirely(self) -> None:
        bundle = bundle_for(DeploymentProfile.LOCAL)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = bundle.build_catalog(
                root, {"PYDEXPI_LIBSQL_URL": "libsql://should.be.ignored.invalid"}
            )
            catalog.record_preparation(
                workspace="solo",
                session_id="s1",
                source_filename="local.xml",
                artifact_prefix="solo/s1",
            )
            self.assertEqual(
                ["local.xml"],
                [r.source_filename for r in catalog.list_sessions(workspace="solo")],
            )
            self.assertTrue(
                sorted(root.rglob("*.sqlite3")),
                "the local catalog is a file on this machine",
            )

    def test_the_local_catalog_needs_no_libsql_package(self) -> None:
        """`import libsql` must not be on the local profile's path.

        The package is a native extension that some platforms compile from
        source. A local install that dragged it in would make a standalone
        run cost a Rust toolchain.
        """

        import pydexpi_datalog.workflow.session_catalog as catalog_module

        source = Path(catalog_module.__file__).read_text(encoding="utf-8")
        top_level = [
            line
            for line in source.splitlines()
            if line.startswith(("import libsql", "from libsql"))
        ]
        self.assertEqual([], top_level, "libsql must be imported lazily")


if __name__ == "__main__":
    unittest.main()
