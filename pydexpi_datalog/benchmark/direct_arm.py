"""Arm A-direct: the single-pass full-context benchmark adapter.

The product owner's 1M-token-context intuition made testable: the entire
DEXPI XML in context, one model call, no tools, no harness, emitting a
:class:`StructuredAnswer` through the benchmark seam.  Malformed or refused
model output degrades to a gradeable answer that can never earn credit — it
must not crash the run, and it must not accidentally match a trap question's
``unanswerable`` ground truth.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydexpi_datalog.benchmark.contract import (
    POSTURE_UNSPECIFIED,
    POSTURES,
    TRAP_EXPECTED_POSTURES,
    StructuredAnswer,
    VERDICTS,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.llm.byok_provider import create_byok_provider
from pydexpi_datalog.llm.model_access import ModelProvider, supported_byok_provider

# The never-creditable verdict a degraded episode carries.  Deliberately
# outside the contract VERDICTS vocabulary so it can never exact-match any
# pre-committed ground truth (a garbage answer must not pass a trap question
# whose ground truth is "unanswerable").
DEGRADED_VERDICT = "malformed_model_output"

# Friendly model keys -> (provider, model) through the existing provider
# layer.  All three route through openrouter: one credential, one gateway.
DIRECT_ARM_MODELS = {
    "sonnet": ("openrouter", "anthropic/claude-sonnet-4"),
    "gpt": ("openrouter", "openai/gpt-5.4"),
    "deepseek": ("openrouter", "deepseek/deepseek-v4-pro"),
}

_SYSTEM_PROMPT = f"""\
You are a P&ID (Piping and Instrumentation Diagram) review assistant.  You
will receive the complete DEXPI XML of one engineering drawing and one
question about it.  Answer from the drawing alone, in a single pass.

Return ONLY a JSON object with exactly these fields:
{{
  "verdict": one of {json.dumps(list(VERDICTS))},
  "witness_ids": a list of DEXPI object IDs from the drawing that are the
    evidence for your verdict (empty if none apply),
  "posture": one of {json.dumps(list(POSTURES))},
  "answer_text": a concise explanation of the result
}}

Rules:
- "violation_found" / "no_violation" assert a conclusion from the drawing
  and require posture "source_grounded".
- If the drawing lacks required data, use "unanswerable" with posture
  "source_data_unavailable". For an ambiguous request that needs a criterion
  or object, use "needs_clarification". For an off-domain request, use
  "out_of_scope". Do not invent witness IDs.
- For an unanswerable, ambiguous, or off-domain request, answer_text must name
  the source limitation or ambiguity and offer a concrete source-grounded next step.
- Every witness ID must be copied exactly from the XML; never invent IDs.
"""


def build_direct_prompt(*, question: BenchmarkQuestion, drawing_ref: Path) -> str:
    """One user message: the full DEXPI XML plus the question. No tools."""
    xml_text = _load_drawing_xml(drawing_ref)
    return (
        "DEXPI XML drawing (complete):\n"
        "```xml\n"
        f"{xml_text}\n"
        "```\n\n"
        f"Question: {question.question}\n\n"
        "Answer with the JSON object described in your instructions."
    )


@dataclass(frozen=True)
class DirectArm:
    """Single-pass full-context arm over any :class:`ModelProvider`."""

    provider: ModelProvider
    arm_label: str = "a-direct"

    @property
    def arm_id(self) -> str:
        return f"{self.arm_label}:{self.provider.provider}:{self.provider.model}"

    def answer(
        self, *, question: BenchmarkQuestion, drawing_ref: Path
    ) -> StructuredAnswer:
        prompt = build_direct_prompt(question=question, drawing_ref=drawing_ref)
        raw_text = self.provider.complete(
            request=prompt,
            context={
                "task": "benchmark_direct_answer",
                "system_prompt": _SYSTEM_PROMPT,
            },
        )
        parsed = parse_structured_answer(raw_text)
        return StructuredAnswer(
            verdict=parsed.verdict,
            witness_ids=parsed.witness_ids,
            posture=parsed.posture,
            answer_text=parsed.answer_text,
            transcript=(
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": raw_text},
            ),
            usage=dict(parsed.usage),
        )


def parse_structured_answer(raw_text: object) -> StructuredAnswer:
    """Parse model text into the answer contract; degrade, never crash.

    The verdict, witness_ids, and posture fields must ALL be present and
    valid — a verdict-only reply must not earn credit while silent on its
    evidence and grounding.  Anything else becomes a never-creditable
    ``DEGRADED_VERDICT`` answer.
    """
    if not isinstance(raw_text, str):
        return _degraded()
    payload = _extract_json_object(raw_text)
    if payload is None:
        return _degraded()

    if not {"verdict", "witness_ids", "posture"} <= payload.keys():
        return _degraded()

    verdict = payload.get("verdict")
    if verdict not in VERDICTS:
        return _degraded()

    witness_raw = payload.get("witness_ids")
    if not isinstance(witness_raw, list) or not all(
        isinstance(item, str) for item in witness_raw
    ):
        return _degraded()

    posture = payload.get("posture")
    if posture not in POSTURES:
        return _degraded()

    answer_text = payload.get("answer_text", "")
    if not isinstance(answer_text, str):
        return _degraded()
    if posture in TRAP_EXPECTED_POSTURES and not answer_text.strip():
        return _degraded()

    return StructuredAnswer(
        verdict=str(verdict),
        witness_ids=tuple(witness_raw),
        posture=str(posture),
        answer_text=answer_text,
    )


def create_direct_arm(
    model_key: str,
    *,
    environ: dict[str, str] | None = None,
) -> DirectArm:
    """Build a live DirectArm for a friendly model key (sonnet/gpt/deepseek).

    Credentials come from the provider layer's declared environment
    variable; a missing credential fails fast with the variable name.
    """
    try:
        provider_name, model = DIRECT_ARM_MODELS[model_key]
    except KeyError:
        choices = ", ".join(sorted(DIRECT_ARM_MODELS))
        raise ValueError(
            f"unknown direct-arm model key: {model_key!r}. Choices: {choices}"
        ) from None

    import os

    env = os.environ if environ is None else environ
    api_key_env_var = str(supported_byok_provider(provider_name)["api_key_env_var"])
    credential = env.get(api_key_env_var)
    if not credential:
        raise ValueError(
            f"direct arm {model_key!r} needs {api_key_env_var} set for "
            f"provider {provider_name!r}"
        )
    provider = create_byok_provider(
        provider=provider_name, model=model, credential=credential
    )
    return DirectArm(provider=provider, arm_label=f"a-direct-{model_key}")


def _degraded() -> StructuredAnswer:
    return StructuredAnswer(
        verdict=DEGRADED_VERDICT,
        witness_ids=(),
        posture=POSTURE_UNSPECIFIED,
    )


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_object(raw_text: str) -> dict[str, object] | None:
    """Find the answer JSON object in plain or fenced model output."""
    candidates: list[str] = []
    fenced = _FENCED_JSON.search(raw_text)
    if fenced:
        candidates.append(fenced.group(1))
    stripped = raw_text.strip()
    if stripped:
        candidates.append(stripped)
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last > first:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _load_drawing_xml(drawing_ref: Path) -> str:
    """Resolve the DEXPI XML for a bundle directory or graph_facts.json ref."""
    if drawing_ref.is_dir():
        xml_path = drawing_ref / "drawing.xml"
        if not xml_path.is_file():
            raise FileNotFoundError(
                f"drawing bundle {drawing_ref} has no drawing.xml"
            )
        return xml_path.read_text(encoding="utf-8")

    artifact = json.loads(drawing_ref.read_text(encoding="utf-8"))
    source_path = artifact.get("source_path")
    if not isinstance(source_path, str) or not source_path:
        raise FileNotFoundError(
            f"graph facts {drawing_ref} carries no source_path to the DEXPI XML"
        )
    xml_path = Path(source_path)
    if not xml_path.is_absolute():
        artifact_relative = (drawing_ref.parent / xml_path).resolve()
        cwd_relative = (Path.cwd() / xml_path).resolve()
        xml_path = (
            artifact_relative if artifact_relative.is_file() else cwd_relative
        )
    if not xml_path.is_file():
        raise FileNotFoundError(
            f"DEXPI XML for {drawing_ref} does not exist: {xml_path}"
        )
    return xml_path.read_text(encoding="utf-8")
