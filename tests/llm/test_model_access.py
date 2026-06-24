from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pydexpi_datalog


REPO_ROOT = Path(__file__).resolve().parents[2]
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

    def test_structured_topology_draft_records_datalog_and_restatement(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(
            response=json.dumps(
                {
                    "generated_datalog": ".decl answer(x:symbol)\n.output answer\nanswer(\"P-4713\").",
                    "formal_restatement": "Return each answer related to P-4713.",
                }
            )
        )

        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What equipment is reachable downstream of P-4713?",
            provider=provider,
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "drafted")
        self.assertEqual(
            artifact["draft"],
            {
                "provider": "fake",
                "model": "fake-model",
                "generated_datalog": ".decl answer(x:symbol)\n.output answer\nanswer(\"P-4713\").",
                "formal_restatement": "Return each answer related to P-4713.",
            },
        )

    def test_run_draft_logic_request_writes_generated_query_sidecar(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(
            response=json.dumps(
                {
                    "generated_datalog": ".decl answer(x:symbol)\n.output answer\nanswer(\"P-4713\").",
                    "formal_restatement": "Return each answer related to P-4713.",
                }
            )
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "logic-request"

            exit_code = pydexpi_datalog.run_draft_logic_request(
                logic_request="What equipment is reachable downstream of P-4713?",
                output_dir=output_dir,
                provider=provider,
                environ={"OPENAI_API_KEY": "test-key"},
            )

            self.assertEqual(exit_code, 0)
            artifact = json.loads(
                (output_dir / "logic_request.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                artifact["draft"]["formal_restatement"],
                "Return each answer related to P-4713.",
            )
            self.assertEqual(
                (output_dir / "generated_query.dl").read_text(encoding="utf-8"),
                ".decl answer(x:symbol)\n.output answer\nanswer(\"P-4713\").\n",
            )

    def test_documentation_request_routes_without_model_credentials(self) -> None:
        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="Explain direct process connections",
            environ={},
        )

        self.assertEqual(artifact["status"], "routed")
        self.assertEqual(artifact["route"], {"kind": "documentation_answer"})
        self.assertEqual(
            artifact["route_result"],
            {
                "kind": "documentation_answer",
                "message": "This request can be answered from project or predicate documentation without model access.",
            },
        )
        self.assertEqual(artifact["diagnostics"], [])

    def test_metadata_request_routes_without_model_credentials(self) -> None:
        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="Show the model and context policy used for this run",
            environ={},
        )

        self.assertEqual(artifact["status"], "routed")
        self.assertEqual(artifact["route"], {"kind": "metadata_lookup"})
        self.assertEqual(
            artifact["route_result"],
            {
                "kind": "metadata_lookup",
                "message": "This request can be answered from persisted logic-request artifacts without model access.",
            },
        )

    def test_unsupported_request_records_missing_capability_without_model_credentials(
        self,
    ) -> None:
        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="Calculate the pump hydraulic head margin",
            environ={},
        )

        self.assertEqual(artifact["status"], "unsupported")
        self.assertEqual(artifact["route"], {"kind": "missing_capability"})
        self.assertEqual(
            artifact["diagnostics"],
            [
                {
                    "code": "logic_request.missing_capability",
                    "message": "This request needs facts, predicates, policy, or external tools that are not available in the OSS topology QA workflow.",
                }
            ],
        )

    def test_clarification_request_routes_without_model_credentials(self) -> None:
        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="Check this thing",
            environ={},
        )

        self.assertEqual(artifact["status"], "needs_clarification")
        self.assertEqual(artifact["route"], {"kind": "clarification"})
        self.assertEqual(
            artifact["diagnostics"],
            [
                {
                    "code": "logic_request.needs_clarification",
                    "message": "The request is too vague to route safely. Clarify the object, relationship, and expected condition.",
                }
            ],
        )

    def test_raw_attribute_request_is_rejected_by_default(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(response="should not be used")

        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What raw attribute values are reachable downstream of P-4713?",
            provider=provider,
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "unsupported")
        self.assertEqual(artifact["route"], {"kind": "raw_attribute_rejected"})
        self.assertEqual(artifact["raw_attribute_mode"], {"enabled": False})
        self.assertEqual(provider.requests, [])
        self.assertEqual(
            artifact["diagnostics"],
            [
                {
                    "code": "logic_request.raw_attributes_disabled",
                    "message": (
                        "Generic raw attributes are disabled by default. Re-run with "
                        "advanced raw-attribute mode only when messy source attribute "
                        "names are intentional."
                    ),
                }
            ],
        )

    def test_raw_attribute_opt_in_reaches_provider_context(self) -> None:
        provider = pydexpi_datalog.FakeModelProvider(
            response="generated raw-attribute logic"
        )

        artifact = pydexpi_datalog.draft_logic_request(
            logic_request="What raw attribute values are reachable downstream of P-4713?",
            allow_raw_attributes=True,
            provider=provider,
            environ={"OPENAI_API_KEY": "test-key"},
        )

        self.assertEqual(artifact["status"], "drafted")
        self.assertEqual(artifact["route"], {"kind": "topology_logic"})
        self.assertEqual(artifact["raw_attribute_mode"], {"enabled": True})
        self.assertEqual(
            provider.requests[0]["context"]["raw_attribute_mode"], {"enabled": True}
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

    def test_model_access_uses_explicit_env_vars_for_supported_byok_providers(
        self,
    ) -> None:
        expected_env_vars = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }

        for provider, env_var in expected_env_vars.items():
            with self.subTest(provider=provider):
                config = pydexpi_datalog.resolve_model_access_config(
                    provider=provider,
                    model="test-model",
                    environ={env_var: "test-key"},
                )

                self.assertEqual(config.provider, provider)
                self.assertEqual(config.model, "test-model")
                self.assertEqual(config.api_key_env_var, env_var)
                self.assertEqual(config.has_credentials, True)

        with self.assertRaisesRegex(ValueError, "unsupported model provider"):
            pydexpi_datalog.resolve_model_access_config(
                provider="bedrock",
                model="test-model",
                environ={"BEDROCK_API_KEY": "test-key"},
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
            logic_request="What equipment is reachable downstream?",
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

    def test_cli_draft_logic_request_matches_library_model_access_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "logic-request"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pydexpi_datalog",
                    "draft-logic-request",
                    "What is downstream of P-4713?",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                env={},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Logic Request Draft", result.stdout)
            cli_artifact = json.loads(
                (output_dir / "logic_request.json").read_text(encoding="utf-8")
            )
            library_artifact = pydexpi_datalog.draft_logic_request(
                logic_request="What is downstream of P-4713?",
                environ={},
            )
            self.assertEqual(cli_artifact, library_artifact)


if __name__ == "__main__":
    unittest.main()
