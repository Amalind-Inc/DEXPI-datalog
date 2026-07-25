"""Arm B: the incumbent grounded-QA pipeline adapter, measured as-is.

The incumbent is exercised at its existing public boundary — a fresh
:class:`QATurnProvider` per episode drives ``run_grounded_qa_turn`` over
``TopologyTools`` built from the drawing's canonical base fact layer. Validated
temporary Datalog executes automatically, and the adapter maps that execution
result directly without replaying it through the retired confirmation path.

Mapping the pipeline's grounded outcome to the benchmark verdict vocabulary
is deterministic and documented here, never narrated:

- automatic Datalog execution with matched objects -> ``violation_found``
  with the matches (translated stable -> raw node ids) as witnesses;
- automatic execution with no matches -> ``no_violation``;
- failed automatic execution -> ``unanswerable`` / ``source_data_unavailable``;
- a non-gated ``source_grounded`` final answer -> ``violation_found`` when it
  carries validated evidence, else ``no_violation``;
- refusal postures (``source_data_unavailable``, ``out_of_scope``,
  ``general_knowledge``) -> ``unanswerable`` with that posture;
- a harness failure (round exhaustion) degrades to the never-creditable
  :data:`DEGRADED_VERDICT` instead of crashing the run.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydexpi_datalog.benchmark.contract import (
    POSTURE_GENERAL_KNOWLEDGE,
    POSTURE_NEEDS_CLARIFICATION,
    POSTURE_OUT_OF_SCOPE,
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    POSTURE_UNSPECIFIED,
    VERDICT_NO_VIOLATION,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
    StructuredAnswer,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.direct_arm import DEGRADED_VERDICT, DIRECT_ARM_MODELS
from pydexpi_datalog.llm.byok_provider import OPENAI_COMPATIBLE_BASE_URLS
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_GENERAL_KNOWLEDGE as HARNESS_GENERAL_KNOWLEDGE,
)
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_NEEDS_CLARIFICATION as HARNESS_NEEDS_CLARIFICATION,
)
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_OUT_OF_SCOPE as HARNESS_OUT_OF_SCOPE,
)
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_SOURCE_DATA_UNAVAILABLE as HARNESS_SOURCE_DATA_UNAVAILABLE,
)
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_SOURCE_GROUNDED as HARNESS_SOURCE_GROUNDED,
)
from pydexpi_datalog.qa.grounded_qa_harness import (
    QATurnProvider,
    QATurnResult,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.openai_compatible_qa_provider import (
    OpenAICompatibleQATurnProvider,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools
from pydexpi_datalog.workflow.review_session import build_topology_view_model

# Same friendly keys, same provider layer, same gateway as the other arms.
INCUMBENT_ARM_MODELS = DIRECT_ARM_MODELS

_HARNESS_TO_CONTRACT_POSTURE = {
    HARNESS_SOURCE_GROUNDED: POSTURE_SOURCE_GROUNDED,
    HARNESS_SOURCE_DATA_UNAVAILABLE: POSTURE_SOURCE_DATA_UNAVAILABLE,
    HARNESS_OUT_OF_SCOPE: POSTURE_OUT_OF_SCOPE,
    HARNESS_NEEDS_CLARIFICATION: POSTURE_NEEDS_CLARIFICATION,
    HARNESS_GENERAL_KNOWLEDGE: POSTURE_GENERAL_KNOWLEDGE,
}


def _graph_facts_path(drawing_ref: Path) -> Path:
    return drawing_ref / "graph_facts.json" if drawing_ref.is_dir() else drawing_ref


def _load_graph_facts(drawing_ref: Path) -> dict[str, object]:
    path = _graph_facts_path(drawing_ref)
    if not path.is_file():
        raise FileNotFoundError(f"graph facts for {drawing_ref} do not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_tools(
    graph_facts: dict[str, object], session_id: str
) -> tuple[TopologyTools, dict[str, object]]:
    source_id = graph_facts.get("source_id")
    topology_view = build_topology_view_model(
        graph_facts=graph_facts,
        session_id=session_id,
        source_id=source_id if isinstance(source_id, str) else None,
    )
    tools = TopologyTools(
        topology_view=topology_view,
        graph_facts=graph_facts,
        session_id=session_id,
    )
    return tools, topology_view


def _raw_witnesses(
    stable_ids: list[str], topology_view: Mapping[str, object]
) -> tuple[str, ...]:
    """Translate the engine's stable evidence ids back to the raw ``node_id``
    space the grader validates against; drop anything untranslatable."""
    evidence_map = topology_view.get("evidence_map")
    if not isinstance(evidence_map, Mapping):
        return ()
    raw: list[str] = []
    for stable_id in stable_ids:
        entry = evidence_map.get(stable_id)
        if not isinstance(entry, Mapping):
            continue
        fact = entry.get("canonical_fact")
        if not isinstance(fact, Mapping):
            continue
        node_id = fact.get("node_id")
        if isinstance(node_id, str) and node_id not in raw:
            raw.append(node_id)
    return tuple(raw)


def _temporary_datalog_execution(
    trace: list[dict[str, object]],
) -> dict[str, object] | None:
    for entry in trace:
        if entry.get("tool_name") != "propose_temporary_datalog":
            continue
        result = entry.get("tool_result")
        if isinstance(result, dict) and result.get("status") in {
            "answered",
            "execution_failed",
        }:
            return result
    return None


@dataclass(frozen=True)
class IncumbentArm:
    """Arm B adapter: incumbent pipeline at its public boundary."""

    provider_factory: Callable[[], QATurnProvider]
    provider_name: str = "scripted"
    model_name: str = "scripted"

    @property
    def arm_id(self) -> str:
        return f"b-incumbent:{self.provider_name}:{self.model_name}"

    def answer(
        self, *, question: BenchmarkQuestion, drawing_ref: Path
    ) -> StructuredAnswer:
        graph_facts = _load_graph_facts(drawing_ref)
        tools, topology_view = _build_tools(
            graph_facts, session_id=f"benchmark-{question.question_id}"
        )
        provider = self.provider_factory()
        try:
            result = run_grounded_qa_turn(
                question=question.question,
                topology_tools=tools,
                provider=provider,
            )
        except RuntimeError as error:
            return StructuredAnswer(
                verdict=DEGRADED_VERDICT,
                witness_ids=(),
                posture=POSTURE_UNSPECIFIED,
                transcript=(
                    {"role": "user", "content": question.question},
                    {"role": "system", "content": f"harness failure: {error}"},
                ),
                usage=_provider_usage(provider),
            )
        trace = list(result.tool_call_trace)
        execution = _temporary_datalog_execution(trace)
        if execution is not None:
            verdict, posture, witnesses, answer_text = self._map_datalog_execution(
                topology_view, execution
            )
        else:
            verdict, posture, witnesses = self._map_final(result, topology_view)
            answer_text = result.answer_text
        return StructuredAnswer(
            verdict=verdict,
            witness_ids=witnesses,
            posture=posture,
            answer_text=answer_text,
            transcript=self._transcript(question.question, trace, answer_text),
            usage=_provider_usage(provider),
        )

    def _map_datalog_execution(
        self,
        topology_view: Mapping[str, object],
        execution: dict[str, object],
    ) -> tuple[str, str, tuple[str, ...], str]:
        """Map the result produced by automatic temporary-Datalog execution."""
        if execution.get("status") != "answered":
            return (
                VERDICT_UNANSWERABLE,
                POSTURE_SOURCE_DATA_UNAVAILABLE,
                (),
                "The automatic Datalog query failed to execute.",
            )
        evidence = execution.get("evidence")
        items = evidence.get("items", []) if isinstance(evidence, dict) else []
        stable_ids = [str(item.get("id")) for item in items if isinstance(item, dict)]
        witnesses = _raw_witnesses(stable_ids, topology_view)
        if witnesses:
            return (
                VERDICT_VIOLATION_FOUND,
                POSTURE_SOURCE_GROUNDED,
                witnesses,
                "Automatic Datalog execution matched objects.",
            )
        return (
            VERDICT_NO_VIOLATION,
            POSTURE_SOURCE_GROUNDED,
            (),
            "Automatic Datalog execution matched no objects.",
        )

    def _map_final(
        self, result: QATurnResult, topology_view: Mapping[str, object]
    ) -> tuple[str, str, tuple[str, ...]]:
        posture = _HARNESS_TO_CONTRACT_POSTURE.get(
            result.grounding_posture, POSTURE_UNSPECIFIED
        )
        if result.grounding_posture == HARNESS_SOURCE_GROUNDED:
            witnesses = _raw_witnesses(list(result.evidence_references), topology_view)
            if witnesses:
                return VERDICT_VIOLATION_FOUND, POSTURE_SOURCE_GROUNDED, witnesses
            return VERDICT_NO_VIOLATION, POSTURE_SOURCE_GROUNDED, ()
        return VERDICT_UNANSWERABLE, posture, ()

    @staticmethod
    def _transcript(
        question: str, trace: list[dict[str, object]], answer_text: str
    ) -> tuple[dict[str, object], ...]:
        messages: list[dict[str, object]] = [{"role": "user", "content": question}]
        for entry in trace:
            messages.append(
                {
                    "role": "tool",
                    "tool_name": entry.get("tool_name"),
                    "tool_input": entry.get("tool_input"),
                    "tool_result": entry.get("tool_result"),
                }
            )
        messages.append({"role": "assistant", "content": answer_text})
        return tuple(messages)


def _provider_usage(provider: object) -> dict[str, object]:
    usage = getattr(provider, "usage", {})
    return dict(usage) if isinstance(usage, Mapping) else {}


def create_incumbent_arm(
    model_key: str, *, environ: Mapping[str, str] | None = None
) -> IncumbentArm:
    """Live Arm B over the existing provider layer (OpenRouter gateway)."""
    env = os.environ if environ is None else environ
    if model_key not in INCUMBENT_ARM_MODELS:
        raise ValueError(
            f"unknown incumbent arm model key: {model_key!r} "
            f"(expected one of {sorted(INCUMBENT_ARM_MODELS)})"
        )
    provider_name, model_name = INCUMBENT_ARM_MODELS[model_key]
    credential = env.get("OPENROUTER_API_KEY", "")
    if not credential:
        raise ValueError("OPENROUTER_API_KEY is required to run the live incumbent arm")
    base_url = OPENAI_COMPATIBLE_BASE_URLS[provider_name]
    return IncumbentArm(
        provider_factory=lambda: OpenAICompatibleQATurnProvider(
            provider=provider_name,
            model=model_name,
            base_url=base_url,
            credential=credential,
        ),
        provider_name=provider_name,
        model_name=model_name,
    )
