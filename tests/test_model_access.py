from __future__ import annotations

from pathlib import Path
import unittest

import pydexpi_datalog


REPO_ROOT = Path(__file__).resolve().parents[1]
E06_DERIVED_GRAPH_SEMANTICS = (
    REPO_ROOT
    / "testdata"
    / "derived_graph_semantics"
    / "e06-pump-hex"
    / "derived_graph_semantics.dl"
)


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

    def test_logic_request_draft_records_selected_source_node_context(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(response="generated logic")

        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What equipment is reachable downstream of this pump?",
            derived_graph_semantics_path=E06_DERIVED_GRAPH_SEMANTICS,
            source_tag="P-4713",
            provider=provider,
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "drafted")
        source_context = artifact["source_node_context"]
        self.assertEqual(source_context["scope"], {"kind": "affected_connected_subgraph"})
        self.assertEqual(
            source_context["source_selection"],
            {
                "resolution_scope": {"kind": "single_dexpi_source_file"},
                "resolution_source": "derived_graph_semantics",
                "resolved_source_id": "16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb",
                "selectors": {"source_tag": "P-4713"},
            },
        )
        self.assertEqual(
            source_context["selected_node"],
            {
                "id": "16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb",
                "label": "CentrifugalPump",
                "proteus_id": "CentrifugalPump-1",
                "tag": "P-4713",
            },
        )
        self.assertTrue(source_context["affected_connected_subgraph"]["composition_edges"])
        self.assertEqual(
            provider.requests[0]["context"]["source_node_context"], source_context
        )

    def test_logic_request_without_source_selection_records_whole_pid_scope(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(response="generated logic")

        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="Explain direct process connections",
            derived_graph_semantics_path=E06_DERIVED_GRAPH_SEMANTICS,
            provider=provider,
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "drafted")
        self.assertEqual(
            artifact["source_node_context"],
            {
                "scope": {"kind": "whole_pid"},
                "diagnostics": [
                    {
                        "code": "source_selection.not_provided",
                        "message": "No source node selector was provided; the logic request has whole-P&ID scope.",
                    }
                ],
            },
        )

    def test_logic_request_stops_before_model_when_source_selector_fails(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(response="should not be used")

        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What is reachable downstream of this pump?",
            derived_graph_semantics_path=E06_DERIVED_GRAPH_SEMANTICS,
            source_tag="not-a-real-tag",
            provider=provider,
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "failed")
        self.assertEqual(provider.requests, [])
        self.assertEqual(
            artifact["source_node_context"]["diagnostics"],
            [
                {
                    "code": "source_selector_no_match",
                    "message": "Source selector did not resolve to a graph node",
                }
            ],
        )

    def test_logic_request_rejects_absent_source_id_before_model(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(response="should not be used")

        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What is reachable downstream of this source?",
            derived_graph_semantics_path=E06_DERIVED_GRAPH_SEMANTICS,
            source_id="not-a-real-node-id",
            provider=provider,
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "failed")
        self.assertEqual(provider.requests, [])
        self.assertEqual(
            artifact["source_node_context"]["diagnostics"],
            [
                {
                    "code": "source_selector_no_match",
                    "message": "Source selector did not resolve to a graph node",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
