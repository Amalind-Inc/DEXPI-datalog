"""Behavioural contract for the deployment profile switch.

ADR 0016 names feature skew as the expected failure mode of the hosted epic:
hosted grows capability, the local path rots into a demo, and the standalone
product becomes theatre. These tests are the guard rail. They pin three
things: the profile is chosen once and explicitly, nothing below the
composition root asks which profile it is running under, and the same suite
can be run end to end under either profile.
"""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pydexpi_datalog.web.deployment import (
    PROFILE_ENV_VAR,
    DeploymentProfile,
    DeploymentProfileError,
    bundle_for,
    resolve_profile,
)
from pydexpi_datalog.web.review_api import create_review_api_app

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "pydexpi_datalog"
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class ProfileResolutionTests(unittest.TestCase):
    """A deployment must say which profile it is. Guessing is the bug."""

    def test_unset_profile_is_refused_rather_than_defaulted(self) -> None:
        # Defaulting to local would be the dangerous direction: a hosted
        # deployment that forgot the setting would serve every user out of
        # one workspace with no sign-in.
        with self.assertRaises(DeploymentProfileError) as caught:
            resolve_profile({})
        message = str(caught.exception)
        self.assertIn(PROFILE_ENV_VAR, message)
        self.assertIn("local", message)
        self.assertIn("hosted", message)

    def test_unrecognised_profile_names_what_was_given_and_what_is_valid(self) -> None:
        with self.assertRaises(DeploymentProfileError) as caught:
            resolve_profile({PROFILE_ENV_VAR: "staging"})
        message = str(caught.exception)
        self.assertIn("staging", message)
        self.assertIn("local", message)
        self.assertIn("hosted", message)

    def test_empty_and_whitespace_values_are_refused(self) -> None:
        for value in ("", "   "):
            with self.subTest(value=value), self.assertRaises(DeploymentProfileError):
                resolve_profile({PROFILE_ENV_VAR: value})

    def test_each_profile_resolves(self) -> None:
        for value, expected in (
            ("local", DeploymentProfile.LOCAL),
            ("hosted", DeploymentProfile.HOSTED),
            ("  HOSTED  ", DeploymentProfile.HOSTED),
        ):
            with self.subTest(value=value):
                self.assertIs(resolve_profile({PROFILE_ENV_VAR: value}), expected)


class ProfileSelectionTests(unittest.TestCase):
    """The profile is chosen once, and the app remembers which one it is."""

    def test_app_records_the_profile_it_was_built_for(self) -> None:
        for profile in DeploymentProfile:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                app = create_review_api_app(
                    artifact_root=Path(tmp) / "sessions", profile=profile
                )
                self.assertIs(app.state.deployment_profile, profile)

    def test_environment_selects_the_profile_when_no_argument_is_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_review_api_app(
                artifact_root=Path(tmp) / "sessions",
                env={PROFILE_ENV_VAR: "hosted"},
            )
            self.assertIs(app.state.deployment_profile, DeploymentProfile.HOSTED)

    def test_explicit_argument_wins_over_the_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_review_api_app(
                artifact_root=Path(tmp) / "sessions",
                profile=DeploymentProfile.LOCAL,
                env={PROFILE_ENV_VAR: "hosted"},
            )
            self.assertIs(app.state.deployment_profile, DeploymentProfile.LOCAL)


class ProfileBundleTests(unittest.TestCase):
    """Every profile supplies an implementation for every seam.

    A seam that only one profile can build is exactly the skew ADR 0016 warns
    about, so the bundle is checked for completeness rather than trusted.
    """

    def test_every_profile_has_a_bundle_covering_every_seam(self) -> None:
        for profile in DeploymentProfile:
            with self.subTest(profile=profile):
                bundle = bundle_for(profile)
                self.assertIs(bundle.profile, profile)
                self.assertTrue(callable(bundle.build_store))
                self.assertTrue(callable(bundle.build_catalog))


class ProfileIsolationTests(unittest.TestCase):
    """Nothing below the composition root may ask which profile it is."""

    def _modules_under(self, *relative: str) -> list[Path]:
        found: list[Path] = []
        for name in relative:
            found.extend(sorted((PACKAGE_ROOT / name).rglob("*.py")))
        return found

    def test_no_workflow_verification_or_qa_module_reads_the_profile(self) -> None:
        # ADR 0016: the profile is invisible below the composition root. These
        # layers are checked by import graph rather than by review, because
        # the first branch on deployment mode is the one that gets copied.
        offenders: list[str] = []
        for path in self._modules_under("workflow", "verification", "qa", "semantics"):
            source = path.read_text(encoding="utf-8")
            if PROFILE_ENV_VAR in source or "web.deployment" in source:
                offenders.append(str(path.relative_to(REPO_ROOT)))
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if "deployment" in node.module:
                        offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [])

    def test_only_the_composition_root_reads_the_profile_environment(self) -> None:
        # review_api resolves the default for library callers; asgi is the
        # deployment entry point. A third reader means the choice is being
        # made twice, which is how the two profiles drift apart.
        allowed = {
            "pydexpi_datalog/web/asgi.py",
            "pydexpi_datalog/web/deployment.py",
            "pydexpi_datalog/web/review_api.py",
        }
        readers = {
            str(path.relative_to(REPO_ROOT))
            for path in PACKAGE_ROOT.rglob("*.py")
            if PROFILE_ENV_VAR in path.read_text(encoding="utf-8")
        }
        self.assertEqual(readers - allowed, set())


class BothProfilesServeTheSameReviewTests(unittest.TestCase):
    """The whole point: one review flow, observable identically either way.

    This is the assertion CI leans on when it runs the suite twice. When a
    hosted implementation replaces a local one, this test exercises it
    through the same public behaviour rather than through a hosted-only path.
    """

    def test_prepare_and_list_behave_identically_under_both_profiles(self) -> None:
        observed: dict[DeploymentProfile, object] = {}
        for profile in DeploymentProfile:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                client = TestClient(
                    create_review_api_app(
                        artifact_root=Path(tmp) / "sessions", profile=profile
                    )
                )
                prepared = client.post(
                    "/api/review/sessions/profile-parity/prepare",
                    json={
                        "filename": "E06.xml",
                        "content": E06_FIXTURE.read_text(encoding="utf-8"),
                    },
                )
                self.assertEqual(prepared.status_code, 200, prepared.text)
                payload = prepared.json()
                self.assertEqual(payload["status"], "ready")

                listed = client.get("/api/review/sessions")
                self.assertEqual(listed.status_code, 200, listed.text)
                # Only content-derived fields are compared. pyDEXPI mints
                # non-deterministic node ids, so the topology view differs
                # between any two runs of identical code and would make a
                # parity assertion over it flap for an unrelated reason.
                observed[profile] = {
                    "status": payload["status"],
                    "source_id": payload["source_id"],
                    "readiness": payload["readiness"]["state"],
                    "sessions": [
                        (record["session_id"], record["source_filename"])
                        for record in listed.json()["sessions"]
                    ],
                }

        self.assertEqual(
            observed[DeploymentProfile.LOCAL],
            observed[DeploymentProfile.HOSTED],
        )


if __name__ == "__main__":
    unittest.main()
