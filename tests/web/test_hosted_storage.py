"""The hosted profile's artifacts are in a bucket, and it says so when they can't be.

Bead 2afe.8, ADR 0016. The `S3ArtifactStore` contract is checked against a
real server in `tests/workflow/test_artifact_store.py`; these tests check the
thing above it, which is easy to leave untested and quietly wrong: that the
hosted profile is actually composed from that store.

This file exists because it caught its own absence. With the hosted bundle
edited to name the local filesystem store -- the exact regression this bead
removes -- the entire hosted suite still passed. Every test asked whether the
review flow worked, and it does work on a local disk. None asked where the
bytes went. A guard nobody can fail is not a guard.
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from hosted_env import hosted_catalog_env

from pydexpi_datalog.web.deployment import (
    DeploymentProfile,
    HostedStorageNotConfigured,
    bundle_for,
    hosted_storage_settings_from_env,
)
from pydexpi_datalog.workflow.principal import Principal


def _principal() -> Principal:
    name = f"store-{uuid.uuid4().hex[:12]}"
    return Principal(user_id=name, workspace=name)


class HostedStorageConfigurationTests(unittest.TestCase):
    """Missing settings are named, not guessed around."""

    def test_an_empty_environment_names_the_missing_bucket(self) -> None:
        with self.assertRaises(HostedStorageNotConfigured) as caught:
            hosted_storage_settings_from_env({})
        self.assertIn("PYDEXPI_S3_BUCKET", str(caught.exception))

    def test_a_blank_bucket_is_treated_as_missing(self) -> None:
        with self.assertRaises(HostedStorageNotConfigured):
            hosted_storage_settings_from_env({"PYDEXPI_S3_BUCKET": "   "})

    def test_an_empty_endpoint_means_aws_rather_than_a_refusal(self) -> None:
        """A managed deployment on AWS proper configures no endpoint."""

        settings = hosted_storage_settings_from_env({"PYDEXPI_S3_BUCKET": "reviews"})
        self.assertEqual("reviews", settings.bucket)
        self.assertIsNone(settings.endpoint_url)

    def test_credentials_are_optional_so_instance_roles_still_work(self) -> None:
        """A deployment with an instance role or IRSA has no keys to give.

        boto3's own credential chain finds those; refusing to start without
        explicit keys would reject a deployment AWS is happy to authorise.
        """

        settings = hosted_storage_settings_from_env(
            {"PYDEXPI_S3_BUCKET": "reviews", "PYDEXPI_S3_ENDPOINT_URL": ""}
        )
        self.assertIsNone(settings.access_key_id)
        self.assertIsNone(settings.secret_access_key)

    def test_the_endpoint_makes_a_self_hosted_bucket_work(self) -> None:
        settings = hosted_storage_settings_from_env(
            {
                "PYDEXPI_S3_BUCKET": "reviews",
                "PYDEXPI_S3_ENDPOINT_URL": "https://minio.internal:9000",
                "PYDEXPI_S3_ACCESS_KEY_ID": "key",
                "PYDEXPI_S3_SECRET_ACCESS_KEY": "secret",
                "PYDEXPI_S3_REGION": "eu-west-2",
            }
        )
        self.assertEqual("https://minio.internal:9000", settings.endpoint_url)
        self.assertEqual("eu-west-2", settings.region)


class HostedBundleUsesObjectStorageTests(unittest.TestCase):
    """The guard whose absence let a local-disk hosted profile pass."""

    def test_the_hosted_profile_refuses_to_build_a_store_unconfigured(self) -> None:
        bundle = bundle_for(DeploymentProfile.HOSTED)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HostedStorageNotConfigured):
                bundle.build_store(Path(tmp), _principal(), {})

    def test_hosted_artifacts_do_not_land_on_the_instance_disk(self) -> None:
        """The whole bead in one assertion.

        An instance disk looks fine until the instance is replaced. If this
        passes while the bundle names the local store, the bundle is not
        being tested -- which is precisely what happened before this test
        existed.
        """

        env = hosted_catalog_env()
        bundle = bundle_for(DeploymentProfile.HOSTED)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = bundle.build_store(root, _principal(), env)
            store.write_json("s1/topology_view.json", {"nodes": [1, 2]})
            self.assertEqual({"nodes": [1, 2]}, store.read_json("s1/topology_view.json"))
            self.assertEqual(
                [],
                [str(p) for p in root.rglob("*") if p.is_file()],
                "hosted artifacts must not be written to the local filesystem",
            )

    def test_a_second_instance_reads_the_first_instances_artifacts(self) -> None:
        """Why object storage at all: two instances, one set of artifacts."""

        env = hosted_catalog_env()
        bundle = bundle_for(DeploymentProfile.HOSTED)
        owner = _principal()
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first = bundle.build_store(Path(one), owner, env)
            first.write_text("s1/graph_facts.dl", 'node("a").\n')
            # A different instance, a different disk, the same owner.
            second = bundle.build_store(Path(two), owner, env)
            self.assertEqual('node("a").\n', second.read_text("s1/graph_facts.dl"))

    def test_hosted_artifacts_are_reachable_by_a_presigned_url(self) -> None:
        env = hosted_catalog_env()
        bundle = bundle_for(DeploymentProfile.HOSTED)
        with tempfile.TemporaryDirectory() as tmp:
            store = bundle.build_store(Path(tmp), _principal(), env)
            store.write_text("s1/export.json", '{"ok": true}')
            url = store.download_url("s1/export.json")
            self.assertTrue(url.startswith("http"), url)
            self.assertIn("X-Amz-Signature", url, "must be presigned")

    def test_two_hosted_users_cannot_reach_each_other(self) -> None:
        env = hosted_catalog_env()
        bundle = bundle_for(DeploymentProfile.HOSTED)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mine = bundle.build_store(root, _principal(), env)
            theirs = bundle.build_store(root, _principal(), env)
            theirs.write_text("s1/private.json", '{"owner": "theirs"}')
            self.assertFalse(mine.exists("s1/private.json"))


class LocalProfileKeepsItsFilesystemTests(unittest.TestCase):
    """The local profile gained no dependency and no configuration."""

    def test_the_local_store_ignores_object_storage_settings(self) -> None:
        bundle = bundle_for(DeploymentProfile.LOCAL)
        owner = _principal()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = bundle.build_store(
                root, owner, {"PYDEXPI_S3_BUCKET": "should-be-ignored"}
            )
            store.write_text("s1/local.json", "{}")
            self.assertTrue(
                (root / owner.workspace / "s1" / "local.json").is_file(),
                "the local profile writes a real file under the workspace",
            )

    def test_the_local_store_needs_no_boto3(self) -> None:
        """`import boto3` must not be on the local profile's path.

        boto3 is large and the local profile has no bucket to talk to. A
        module-scope import would make a standalone install pay for it.
        """

        import pydexpi_datalog.workflow.s3_artifact_store as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        top_level = [
            line
            for line in source.splitlines()
            if line.startswith(("import boto3", "from boto3", "import botocore"))
        ]
        self.assertEqual([], top_level, "boto3 must be imported lazily")


if __name__ == "__main__":
    unittest.main()
