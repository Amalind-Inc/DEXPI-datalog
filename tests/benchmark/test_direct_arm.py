"""Behavior tests for the Arm A-direct single-pass full-context adapter.

The adapter puts the entire DEXPI XML in context, makes one model call with
no tools, and emits a StructuredAnswer through the benchmark seam.  Tests use
FakeModelProvider — zero live LLM calls.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydexpi_datalog.benchmark import (
    DEGRADED_VERDICT,
    DirectArm,
    create_direct_arm,
)
from pydexpi_datalog.benchmark.contract import (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    POSTURE_UNSPECIFIED,
    VERDICT_VIOLATION_FOUND,
    GroundTruth,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.grader import grade
from pydexpi_datalog.llm.model_access import FakeModelProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = (
    REPO_ROOT
    / "testdata"
    / "graph_contract"
    / "e06-pump-hex"
    / "graph_facts.json"
)

XML_BODY = '<?xml version="1.0"?><PlantModel><Equipment ID="P-100"/></PlantModel>'


def make_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "drawing.xml").write_text(XML_BODY, encoding="utf-8")
    (bundle / "graph_facts.json").write_text(
        E06_GRAPH_FACTS.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return bundle


def make_question(drawing_ref: Path) -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question_id="q1",
        question="Does the pump discharge lack a check valve?",
        slice="hand_authored",
        drawing_ref=drawing_ref,
        ground_truth=GroundTruth(
            verdict=VERDICT_VIOLATION_FOUND, witness_ids=("node-1",)
        ),
    )


class DirectArmPromptTests(unittest.TestCase):
    def test_single_pass_prompt_contains_full_xml_question_and_vocab(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = make_bundle(Path(tmp_dir))
            question = make_question(bundle)
            provider = FakeModelProvider(
                json.dumps(
                    {
                        "verdict": "violation_found",
                        "witness_ids": ["node-1"],
                        "posture": "source_grounded",
                    }
                )
            )
            arm = DirectArm(provider=provider)

            arm.answer(question=question, drawing_ref=bundle)

            self.assertEqual(len(provider.requests), 1)
            request = str(provider.requests[0]["request"])
            self.assertIn(XML_BODY, request)
            self.assertIn(question.question, request)
            context = provider.requests[0]["context"]
            instructions = str(context)
            for term in (
                "violation_found",
                "no_violation",
                "unanswerable",
                "source_grounded",
                "witness_ids",
            ):
                self.assertIn(term, request + instructions)

    def test_answer_parses_structured_answer_from_model_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = make_bundle(Path(tmp_dir))
            question = make_question(bundle)
            provider = FakeModelProvider(
                json.dumps(
                    {
                        "verdict": "violation_found",
                        "witness_ids": ["node-1", "node-2"],
                        "posture": "source_grounded",
                    }
                )
            )
            arm = DirectArm(provider=provider)

            answer = arm.answer(question=question, drawing_ref=bundle)

            self.assertEqual(answer.verdict, VERDICT_VIOLATION_FOUND)
            self.assertEqual(answer.witness_ids, ("node-1", "node-2"))
            self.assertEqual(answer.posture, POSTURE_SOURCE_GROUNDED)
            roles = [m.get("role") for m in answer.transcript]
            self.assertIn("assistant", roles)

    def test_answer_parses_fenced_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = make_bundle(Path(tmp_dir))
            question = make_question(bundle)
            provider = FakeModelProvider(
                "Here is my analysis.\n```json\n"
                + json.dumps(
                    {
                        "verdict": "unanswerable",
                        "witness_ids": [],
                        "posture": "source_data_unavailable",
                    }
                )
                + "\n```\nHope that helps."
            )
            arm = DirectArm(provider=provider)

            answer = arm.answer(question=question, drawing_ref=bundle)

            self.assertEqual(answer.verdict, "unanswerable")
            self.assertEqual(answer.witness_ids, ())
            self.assertEqual(answer.posture, POSTURE_SOURCE_DATA_UNAVAILABLE)

    def test_graph_facts_drawing_ref_resolves_source_xml(self) -> None:
        question = make_question(E06_GRAPH_FACTS)
        provider = FakeModelProvider(
            json.dumps({"verdict": "no_violation", "posture": "source_grounded"})
        )
        arm = DirectArm(provider=provider)

        arm.answer(question=question, drawing_ref=E06_GRAPH_FACTS)

        request = str(provider.requests[0]["request"])
        self.assertIn("<?xml", request)
        self.assertIn("PlantModel", request)


class DirectArmDegradationTests(unittest.TestCase):
    def test_prose_refusal_degrades_to_gradeable_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = make_bundle(Path(tmp_dir))
            question = make_question(bundle)
            provider = FakeModelProvider(
                "I cannot analyze this diagram, sorry."
            )
            arm = DirectArm(provider=provider)

            answer = arm.answer(question=question, drawing_ref=bundle)

            self.assertEqual(answer.verdict, DEGRADED_VERDICT)
            self.assertEqual(answer.witness_ids, ())
            self.assertEqual(answer.posture, POSTURE_UNSPECIFIED)
            graph_facts = json.loads(
                E06_GRAPH_FACTS.read_text(encoding="utf-8")
            )
            episode_grade = grade(
                answer=answer,
                ground_truth=question.ground_truth,
                graph_facts=graph_facts,
            )
            self.assertFalse(episode_grade.passed)
            self.assertFalse(episode_grade.verdict_match)

    def test_degraded_verdict_never_credits_trap_questions(self) -> None:
        """Garbage output must not earn an exact-match on 'unanswerable'."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = make_bundle(Path(tmp_dir))
            provider = FakeModelProvider("```json\n{not valid json\n```")
            arm = DirectArm(provider=provider)
            trap_question = BenchmarkQuestion(
                question_id="trap-1",
                question="When was this drawing approved?",
                slice="trap",
                drawing_ref=bundle,
                ground_truth=GroundTruth(verdict="unanswerable"),
            )

            answer = arm.answer(question=trap_question, drawing_ref=bundle)

            self.assertEqual(answer.verdict, DEGRADED_VERDICT)
            graph_facts = json.loads(
                E06_GRAPH_FACTS.read_text(encoding="utf-8")
            )
            episode_grade = grade(
                answer=answer,
                ground_truth=trap_question.ground_truth,
                graph_facts=graph_facts,
            )
            self.assertFalse(episode_grade.verdict_match)

    def test_invalid_vocab_values_degrade_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = make_bundle(Path(tmp_dir))
            question = make_question(bundle)
            provider = FakeModelProvider(
                json.dumps(
                    {
                        "verdict": "maybe_violation",
                        "witness_ids": "node-1",
                        "posture": "confident",
                    }
                )
            )
            arm = DirectArm(provider=provider)

            answer = arm.answer(question=question, drawing_ref=bundle)

            self.assertEqual(answer.verdict, DEGRADED_VERDICT)
            self.assertEqual(answer.posture, POSTURE_UNSPECIFIED)

    def test_missing_required_fields_degrade(self) -> None:
        """verdict alone must not be creditable: posture and witness_ids
        are part of the contract and must be explicit."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = make_bundle(Path(tmp_dir))
            question = make_question(bundle)
            for payload in (
                {"verdict": "unanswerable"},
                {"verdict": "unanswerable", "posture": "out_of_scope"},
                {"verdict": "unanswerable", "witness_ids": []},
            ):
                provider = FakeModelProvider(json.dumps(payload))
                arm = DirectArm(provider=provider)
                answer = arm.answer(question=question, drawing_ref=bundle)
                self.assertEqual(
                    answer.verdict, DEGRADED_VERDICT, msg=str(payload)
                )

    def test_non_string_model_output_degrades_not_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = make_bundle(Path(tmp_dir))
            question = make_question(bundle)

            class NoneProvider:
                provider = "fake"
                model = "fake-none"

                def complete(
                    self, *, request: str, context: dict[str, object]
                ) -> str:
                    return None  # type: ignore[return-value]

            arm = DirectArm(provider=NoneProvider())
            answer = arm.answer(question=question, drawing_ref=bundle)
            self.assertEqual(answer.verdict, DEGRADED_VERDICT)


class DirectArmModelSelectionTests(unittest.TestCase):
    def test_sonnet_gpt_deepseek_selectable_via_provider_layer(self) -> None:
        environ = {"OPENROUTER_API_KEY": "test-key"}
        expected = {
            "sonnet": "anthropic/claude-sonnet-4",
            "gpt": "openai/gpt-5.4",
            "deepseek": "deepseek/deepseek-v4-pro",
        }
        for key, model in expected.items():
            arm = create_direct_arm(key, environ=environ)
            self.assertEqual(arm.provider.provider, "openrouter")
            self.assertEqual(arm.provider.model, model)
            self.assertIn(key, arm.arm_id)
            self.assertIn("a-direct", arm.arm_id)

    def test_missing_credential_fails_fast_with_env_var_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY"):
            create_direct_arm("sonnet", environ={})

    def test_unknown_model_key_lists_choices(self) -> None:
        with self.assertRaisesRegex(ValueError, "sonnet"):
            create_direct_arm("claude", environ={"OPENROUTER_API_KEY": "x"})


if __name__ == "__main__":
    unittest.main()
