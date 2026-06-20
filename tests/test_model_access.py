from __future__ import annotations

import unittest

import pydexpi_datalog


class ModelAccessTests(unittest.TestCase):
    def test_oss_model_access_reports_missing_byok_credentials(self) -> None:
        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What is downstream of P-4713?",
            environ={},
        )

        self.assertEqual(artifact["status"], "failed")
        self.assertEqual(artifact["route"], {"kind": "topology_logic"})
        self.assertEqual(artifact["model_access"]["access_mode"], "byok")
        self.assertEqual(artifact["model_access"]["provider"], "openai")
        self.assertFalse(artifact["model_access"]["has_credentials"])
        self.assertEqual(
            artifact["diagnostics"],
            [
                {
                    "code": "model_access.missing_byok_credentials",
                    "message": "OSS logic requests require user-supplied model provider credentials. Set OPENAI_API_KEY to use openai.",
                }
            ],
        )

    def test_logic_request_drafting_uses_configured_fake_provider(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(
            response="generated Datalog and engineer-readable restatement"
        )

        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What equipment is reachable downstream of P-4713?",
            provider=provider,
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "drafted")
        self.assertEqual(artifact["route"], {"kind": "topology_logic"})
        self.assertEqual(artifact["diagnostics"], [])
        self.assertEqual(
            artifact["draft"],
            {
                "provider": "fake",
                "model": "fake-model",
                "text": "generated Datalog and engineer-readable restatement",
            },
        )
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            provider.requests[0]["context"]["model_access"]["access_mode"],
            "byok",
        )

    def test_model_access_metadata_uses_neutral_capability_language(self) -> None:
        config = pydexpi_datalog.resolve_model_access_config(
            environ={"OPENAI_API_KEY": "test-key"}
        )

        self.assertEqual(
            config.metadata(),
            {
                "access_mode": "byok",
                "provider": "openai",
                "model": "gpt-4.1",
                "api_key_env_var": "OPENAI_API_KEY",
                "has_credentials": True,
            },
        )

    def test_logic_request_reports_missing_provider_adapter_after_credentials(self) -> None:
        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What is downstream of P-4713?",
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "failed")
        self.assertEqual(
            artifact["diagnostics"],
            [
                {
                    "code": "model_access.provider_not_configured",
                    "message": "No model provider adapter was configured for this logic request.",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
