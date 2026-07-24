"""Preregistered hybrid product holdout (bead 3qo.9.10).

Materializes an unseen SME-certified slice, runs it through a benchmark arm
(typically the released incumbent / grounded-QA hybrid), and builds a holdout
report with metrics plus a fail-closed generalization gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from pydexpi_datalog.benchmark.dataset import DATASET_SCHEMA_VERSION
from pydexpi_datalog.benchmark.runner import ArmAdapter, run_benchmark


HYBRID_HOLDOUT_SCHEMA_VERSION = 1
HYBRID_HOLDOUT_PROTOCOL_BEAD = "pydexpi-datalog-1-3qo.9.10"
HYBRID_HOLDOUT_REVISION = "hybrid-product-holdout-v1"
HYBRID_HOLDOUT_CERTIFICATION_BEAD = "pydexpi-datalog-1-rmso.7"
HYBRID_HOLDOUT_CERTIFICATION_STATUS = "product_owner_sme_approved"
HYBRID_HOLDOUT_REPORT_FILENAME = "hybrid_holdout_report.json"

FROZEN_V3_DEVELOPMENT_IDS = frozenset(
    {
        "ha-e03-pump-p4713-retrieval",
        "hq-nozzle-piping-attachment-small",
        "hq-nozzle-piping-attachment-large",
        "hq-valve-monitoring-reachability-small",
        "hq-valve-monitoring-reachability-large",
        "hq-equipment-pump-connectivity-small",
        "hq-equipment-pump-connectivity-large",
        "hq-permission-defeasible-control-small",
        "hq-permission-defeasible-control-large",
    }
)

HYBRID_HOLDOUT_REQUIRED_CASE_TAGS = frozenset(
    {
        "template_fit",
        "explicit_class",
        "implicit_class",
        "piping_scope",
        "instrumentation_scope",
        "directed",
    }
)

_ACCOUNTING_CONTRACT = {
    "provider_ledger": "required",
    "unknown_cost": "run_incomplete",
    "policy_violation": "run_incomplete",
}

_EPISODE_BUDGETS = {
    "max_turns": 64,
    "max_commands": 128,
    "max_output_tokens": 8192,
    "agent_timeout_sec": 300.0,
    "verifier_timeout_sec": 60.0,
}

HYBRID_HOLDOUT_MODELS = {
    "deepseek-flash": ("openrouter", "deepseek/deepseek-v4-flash"),
    "deepseek-pro": ("openrouter", "deepseek/deepseek-v4-pro"),
}


class HybridHoldoutError(ValueError):
    """The preregistered hybrid holdout lock cannot be trusted."""


def create_hybrid_holdout_live_arm(
    model_key: str = "deepseek-flash",
    *,
    environ: Mapping[str, str] | None = None,
):
    """Build the released hybrid incumbent arm for a live OpenRouter model."""
    import os

    from pydexpi_datalog.benchmark.incumbent_arm import IncumbentArm
    from pydexpi_datalog.llm.byok_provider import OPENAI_COMPATIBLE_BASE_URLS
    from pydexpi_datalog.qa.openai_compatible_qa_provider import (
        OpenAICompatibleQATurnProvider,
    )

    env = os.environ if environ is None else environ
    if model_key not in HYBRID_HOLDOUT_MODELS:
        raise ValueError(
            f"unknown hybrid holdout model key: {model_key!r} "
            f"(expected one of {sorted(HYBRID_HOLDOUT_MODELS)})"
        )
    provider_name, model_name = HYBRID_HOLDOUT_MODELS[model_key]
    credential = env.get("OPENROUTER_API_KEY", "")
    if not credential:
        raise ValueError(
            "OPENROUTER_API_KEY is required to run the live hybrid holdout"
        )
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


def materialize_hybrid_holdout_manifest(
    lock_path: Path, output_path: Path
) -> Path:
    """Materialize the locked unseen hybrid holdout from certified sources."""
    lock_path = lock_path.resolve()
    output_path = output_path.resolve()
    lock = _read_object(lock_path, "hybrid holdout lock")
    _validate_lock_header(lock, lock_path)

    source_questions: dict[str, dict[str, dict[str, Any]]] = {}
    source_paths: dict[str, Path] = {}
    frozen_sources: list[dict[str, str]] = []
    raw_sources = lock.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise HybridHoldoutError("Hybrid holdout lock requires non-empty sources.")
    for raw_source in raw_sources:
        source_key, source_path, expected_hash = _load_source_spec(
            raw_source, lock_path
        )
        if source_key in source_questions:
            raise HybridHoldoutError(
                f"Hybrid holdout lock has duplicate source key {source_key!r}."
            )
        actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise HybridHoldoutError(
                f"Source manifest {source_path} failed SHA-256 validation: "
                f"expected {expected_hash}, got {actual_hash}."
            )
        source_manifest = _read_object(source_path, f"Source manifest {source_path}")
        if source_manifest.get("schema_version") != DATASET_SCHEMA_VERSION:
            raise HybridHoldoutError(
                f"Source manifest {source_path} has unsupported schema_version."
            )
        source_questions[source_key] = _index_questions(source_manifest, source_path)
        source_paths[source_key] = source_path
        frozen_sources.append(
            {"key": source_key, "path": str(source_path), "sha256": expected_hash}
        )

    entry_specs = _load_entry_specs(lock.get("entries"))
    excluded = lock.get("excluded_development_matrix_ids")
    if not isinstance(excluded, list) or set(excluded) != FROZEN_V3_DEVELOPMENT_IDS:
        raise HybridHoldoutError(
            "Hybrid holdout lock must exclude the frozen v3 development matrix ids."
        )

    selected: list[dict[str, Any]] = []
    entry_metadata: list[dict[str, Any]] = []
    covered_tags: set[str] = set()
    for question_id, source_key, case_tags in entry_specs:
        if question_id in FROZEN_V3_DEVELOPMENT_IDS:
            raise HybridHoldoutError(
                f"Hybrid holdout entry {question_id!r} reuses the frozen "
                "development matrix."
            )
        try:
            raw_question = source_questions[source_key][question_id]
        except KeyError as error:
            raise HybridHoldoutError(
                f"Locked entry {question_id!r} is absent from source {source_key!r}."
            ) from error
        question = dict(raw_question)
        source_path = source_paths[source_key]
        drawing = question.get("drawing")
        if not isinstance(drawing, str) or not drawing:
            raise HybridHoldoutError(
                f"Locked entry {question_id!r} has an invalid drawing reference."
            )
        question["drawing"] = str((source_path.parent / drawing).resolve())
        selected.append(question)
        covered_tags.update(case_tags)
        entry_metadata.append(
            {
                "id": question_id,
                "source": source_key,
                "case_tags": list(case_tags),
            }
        )

    required_tags = {
        str(tag) for tag in lock.get("required_case_tags", []) if isinstance(tag, str)
    }
    if required_tags != HYBRID_HOLDOUT_REQUIRED_CASE_TAGS:
        raise HybridHoldoutError(
            "Hybrid holdout lock required_case_tags do not match the protocol."
        )
    if not HYBRID_HOLDOUT_REQUIRED_CASE_TAGS.issubset(covered_tags):
        missing = sorted(HYBRID_HOLDOUT_REQUIRED_CASE_TAGS - covered_tags)
        raise HybridHoldoutError(
            f"Hybrid holdout entries miss required case tags: {missing}."
        )

    frozen_protocol = dict(lock["protocol"])
    frozen_protocol["document"] = str(
        (lock_path.parent / frozen_protocol["document"]).resolve()
        if not Path(str(frozen_protocol["document"])).is_absolute()
        else frozen_protocol["document"]
    )
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "hybrid_holdout_lock": {
            "schema_version": HYBRID_HOLDOUT_SCHEMA_VERSION,
            "path": str(lock_path),
            "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
            "design_revision": lock["design_revision"],
            "protocol_bead": frozen_protocol["bead"],
            "protocol": frozen_protocol,
            "protocol_approval": lock["protocol_approval"],
            "certification": lock["certification"],
            "accounting_contract": lock["accounting_contract"],
            "generalization_gate": lock["generalization_gate"],
            "required_case_tags": sorted(required_tags),
            "excluded_development_matrix_ids": sorted(FROZEN_V3_DEVELOPMENT_IDS),
            "sources": frozen_sources,
            "entries": entry_metadata,
        },
        "episode_budgets": lock["episode_budgets"],
        "questions": selected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = output_path.with_name(f".{output_path.name}.tmp")
    staging_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    staging_path.replace(output_path)
    return output_path


def run_hybrid_holdout(
    *,
    lock_path: Path,
    arm: ArmAdapter,
    output_dir: Path,
    manifest_output_path: Path | None = None,
) -> dict[str, object]:
    """Materialize, run, and report the hybrid holdout for one arm."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = (
        manifest_output_path.resolve()
        if manifest_output_path is not None
        else output_dir / "hybrid_holdout_manifest.json"
    )
    if manifest_output_path is None or not manifest_path.is_file():
        materialize_hybrid_holdout_manifest(lock_path, manifest_path)
    lock = _read_object(lock_path.resolve(), "hybrid holdout lock")
    benchmark_report = run_benchmark(
        manifest_path=manifest_path,
        arm=arm,
        output_dir=output_dir / "benchmark",
    )
    report = build_hybrid_holdout_report(
        lock=lock,
        manifest_path=manifest_path,
        benchmark_report=benchmark_report,
    )
    artifact_path = output_dir / HYBRID_HOLDOUT_REPORT_FILENAME
    staging_path = output_dir / f".{HYBRID_HOLDOUT_REPORT_FILENAME}.tmp"
    staging_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    staging_path.replace(artifact_path)
    return report


def build_hybrid_holdout_report(
    *,
    lock: Mapping[str, object],
    manifest_path: Path,
    benchmark_report: Mapping[str, object],
) -> dict[str, object]:
    """Aggregate holdout metrics and the fail-closed generalization gate."""
    episodes = list(benchmark_report.get("episodes") or [])
    gating = [episode for episode in episodes if episode.get("gating")]
    if not gating:
        gating = episodes

    grounded_credit = sum(
        1 for episode in gating if bool((episode.get("grade") or {}).get("passed"))
    )
    questions = len(gating)
    grounded_credit_rate = (
        grounded_credit / questions if questions else 0.0
    )
    total_cost = 0.0
    cost_complete = True
    for episode in gating:
        usage = episode.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        cost_value = episode.get("cost_usd")
        if cost_value is None:
            cost_value = usage.get("cost_usd")
        if not isinstance(cost_value, (int, float)) or isinstance(cost_value, bool):
            cost_complete = False
            continue
        total_cost += float(cost_value)

    cost_per_credit = (
        total_cost / grounded_credit if grounded_credit and cost_complete else None
    )

    route_stats = _route_metrics(gating)
    latency_seconds = [
        float(episode.get("wall_time_seconds") or 0.0) for episode in gating
    ]
    interruptions = _interruption_metrics(gating)

    gate_config = lock.get("generalization_gate")
    if not isinstance(gate_config, dict):
        raise HybridHoldoutError("Hybrid holdout lock lacks generalization_gate.")
    minimum_rate = float(gate_config.get("minimum_grounded_credit_rate", 1.0))
    deferred = [
        str(tag)
        for tag in gate_config.get("deferred_case_tags", [])
        if isinstance(tag, str)
    ]
    covered_tags = {
        str(tag)
        for entry in lock.get("entries", [])
        if isinstance(entry, dict)
        for tag in entry.get("case_tags", [])
        if isinstance(tag, str)
    }
    required_tags = {
        str(tag)
        for tag in lock.get("required_case_tags", [])
        if isinstance(tag, str)
    }
    case_coverage_ok = required_tags.issubset(covered_tags)
    accounting_ok = cost_complete
    artifacts_ok = all(_episode_has_required_artifacts(episode) for episode in gating)
    credit_ok = grounded_credit_rate + 1e-12 >= minimum_rate
    gate_passed = case_coverage_ok and accounting_ok and artifacts_ok and credit_ok

    return {
        "schema_version": 1,
        "protocol_bead": HYBRID_HOLDOUT_PROTOCOL_BEAD,
        "design_revision": lock.get("design_revision"),
        "manifest_path": str(manifest_path.resolve()),
        "arm_id": benchmark_report.get("arm_id"),
        "certification": lock.get("certification"),
        "metrics": {
            "questions": questions,
            "grounded_credit": grounded_credit,
            "grounded_credit_rate": grounded_credit_rate,
            "total_provider_cost_usd": total_cost if cost_complete else None,
            "cost_per_grounded_credit": cost_per_credit,
            "template_coverage_excluding_policy_abstentions": route_stats[
                "template_coverage_excluding_policy_abstentions"
            ],
            "conditional_template_correctness": route_stats[
                "conditional_template_correctness"
            ],
            "false_route_rate": route_stats["false_route_rate"],
            "fallback_correctness": route_stats["fallback_correctness"],
            "generated_authoring_avoided": route_stats["generated_authoring_avoided"],
            "latency_seconds_total": sum(latency_seconds),
            "latency_seconds_mean": (
                sum(latency_seconds) / len(latency_seconds) if latency_seconds else 0.0
            ),
            "answer_now_or_operational_interruptions": interruptions,
        },
        "gate": {
            "passed": gate_passed,
            "production_generalization_claim_allowed": False,
            "minimum_grounded_credit_rate": minimum_rate,
            "case_coverage_ok": case_coverage_ok,
            "accounting_ok": accounting_ok,
            "artifacts_ok": artifacts_ok,
            "credit_ok": credit_ok,
            "deferred_case_tags": deferred,
            "reason": (
                "mechanical gate passed; production generalization still requires "
                "explicit human promotion after reviewing the holdout report"
                if gate_passed
                else "holdout gate failed; no production generalization claim"
            ),
        },
        "benchmark_report": benchmark_report,
    }


def _route_metrics(episodes: list[dict[str, object]]) -> dict[str, object]:
    template_routes = 0
    template_correct = 0
    policy_abstentions = 0
    generated_routes = 0
    false_routes = 0
    fallback_correct = 0
    fallback_total = 0
    for episode in episodes:
        route = _episode_route(episode)
        passed = bool((episode.get("grade") or {}).get("passed"))
        if route == "policy_abstention":
            policy_abstentions += 1
            continue
        if route == "bundled_template":
            template_routes += 1
            if passed:
                template_correct += 1
            else:
                false_routes += 1
            continue
        if route == "generated_temporary_datalog":
            generated_routes += 1
            fallback_total += 1
            if passed:
                fallback_correct += 1
            continue
        # Unknown / retrieval-only routes: count neither as template nor false route.
        if route == "fallback" or route == "generated":
            fallback_total += 1
            if passed:
                fallback_correct += 1

    eligible_for_coverage = max(len(episodes) - policy_abstentions, 0)
    template_coverage = (
        template_routes / eligible_for_coverage if eligible_for_coverage else None
    )
    conditional_correctness = (
        template_correct / template_routes if template_routes else None
    )
    false_route_rate = (
        false_routes / template_routes if template_routes else 0.0
    )
    fallback_correctness = (
        fallback_correct / fallback_total if fallback_total else None
    )
    authoring_avoided = (
        1.0 - (generated_routes / eligible_for_coverage)
        if eligible_for_coverage
        else None
    )
    return {
        "template_coverage_excluding_policy_abstentions": template_coverage,
        "conditional_template_correctness": conditional_correctness,
        "false_route_rate": false_route_rate,
        "fallback_correctness": fallback_correctness,
        "generated_authoring_avoided": authoring_avoided,
    }


def _episode_route(episode: Mapping[str, object]) -> str | None:
    transcript = episode.get("transcript")
    if not isinstance(transcript, (list, tuple)):
        answer = episode.get("answer")
        if isinstance(answer, dict):
            transcript = answer.get("transcript")
    if not isinstance(transcript, (list, tuple)):
        return None
    saw_generated = False
    saw_template = False
    saw_policy = False
    for message in transcript:
        if not isinstance(message, dict):
            continue
        tool_name = message.get("tool_name")
        tool_result = message.get("tool_result")
        if tool_name == "execute_bundled_query_template":
            saw_template = True
        if tool_name == "propose_temporary_datalog":
            saw_generated = True
        if isinstance(tool_result, dict):
            if tool_result.get("status") == "policy_abstention":
                saw_policy = True
            route_artifact = tool_result.get("route_artifact")
            if isinstance(route_artifact, dict):
                route = route_artifact.get("route")
                if isinstance(route, str) and route:
                    return route
    if saw_policy:
        return "policy_abstention"
    if saw_template:
        return "bundled_template"
    if saw_generated:
        return "generated_temporary_datalog"
    return None


def _interruption_metrics(episodes: list[dict[str, object]]) -> dict[str, int]:
    answer_now = 0
    stop = 0
    for episode in episodes:
        transcript = episode.get("transcript")
        if not isinstance(transcript, (list, tuple)):
            answer = episode.get("answer")
            if isinstance(answer, dict):
                transcript = answer.get("transcript")
        if not isinstance(transcript, (list, tuple)):
            continue
        blob = json.dumps(transcript)
        if "answer_now" in blob.lower():
            answer_now += 1
        if '"stop"' in blob.lower() or "steering_stop" in blob.lower():
            stop += 1
    return {"answer_now": answer_now, "stop": stop}


def _episode_has_required_artifacts(episode: Mapping[str, object]) -> bool:
    answer = episode.get("answer")
    grade = episode.get("grade")
    if not isinstance(answer, dict) or not isinstance(grade, dict):
        return False
    if "passed" not in grade:
        return False
    # Benchmark runner lifts usage to the episode; cost_usd may be 0.0.
    if "usage" not in episode and "cost_usd" not in episode:
        return False
    cost_value = episode.get("cost_usd")
    usage = episode.get("usage")
    if cost_value is None and isinstance(usage, dict):
        cost_value = usage.get("cost_usd")
    return isinstance(cost_value, (int, float)) and not isinstance(cost_value, bool)


def _validate_lock_header(lock: dict[str, Any], lock_path: Path) -> None:
    if lock.get("schema_version") != HYBRID_HOLDOUT_SCHEMA_VERSION:
        raise HybridHoldoutError("Hybrid holdout lock has an invalid schema_version.")
    if lock.get("design_revision") != HYBRID_HOLDOUT_REVISION:
        raise HybridHoldoutError("Hybrid holdout lock has an invalid design revision.")
    protocol = lock.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("bead") != HYBRID_HOLDOUT_PROTOCOL_BEAD:
        raise HybridHoldoutError("Hybrid holdout lock has an invalid protocol bead.")
    protocol_document = protocol.get("document")
    protocol_hash = protocol.get("sha256")
    if not isinstance(protocol_document, str) or not isinstance(protocol_hash, str):
        raise HybridHoldoutError("Hybrid holdout lock must hash its protocol document.")
    protocol_path = Path(protocol_document)
    if not protocol_path.is_absolute():
        protocol_path = (lock_path.parent / protocol_document).resolve()
    try:
        actual_protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    except OSError as error:
        raise HybridHoldoutError(
            f"Hybrid holdout protocol document is unreadable: {protocol_path}."
        ) from error
    if actual_protocol_hash != protocol_hash:
        raise HybridHoldoutError(
            f"Hybrid holdout protocol document failed SHA-256 validation: expected "
            f"{protocol_hash}, got {actual_protocol_hash}."
        )
    approval = lock.get("protocol_approval")
    if (
        not isinstance(approval, dict)
        or approval.get("status") != "product_owner_approved"
        or not isinstance(approval.get("approved_on"), str)
        or not approval["approved_on"]
    ):
        raise HybridHoldoutError(
            "Hybrid holdout lock lacks product-owner protocol approval."
        )
    certification = lock.get("certification")
    if (
        not isinstance(certification, dict)
        or certification.get("bead") != HYBRID_HOLDOUT_CERTIFICATION_BEAD
        or certification.get("status") != HYBRID_HOLDOUT_CERTIFICATION_STATUS
        or not isinstance(certification.get("approved_on"), str)
        or not certification["approved_on"]
    ):
        raise HybridHoldoutError(
            "Hybrid holdout lock lacks required product-owner SME certification."
        )
    if lock.get("accounting_contract") != _ACCOUNTING_CONTRACT:
        raise HybridHoldoutError(
            "Hybrid holdout lock has an invalid accounting contract."
        )
    if lock.get("episode_budgets") != _EPISODE_BUDGETS:
        raise HybridHoldoutError(
            "Hybrid holdout lock episode_budgets do not match the preregistered limits."
        )


def _load_source_spec(
    raw_source: object, lock_path: Path
) -> tuple[str, Path, str]:
    if not isinstance(raw_source, dict):
        raise HybridHoldoutError("Each hybrid holdout source must be an object.")
    source_key = raw_source.get("key")
    path_value = raw_source.get("path")
    expected_hash = raw_source.get("sha256")
    if not isinstance(source_key, str) or not source_key:
        raise HybridHoldoutError("Hybrid holdout source requires a key.")
    if not isinstance(path_value, str) or not path_value:
        raise HybridHoldoutError("Hybrid holdout source requires a path.")
    if not isinstance(expected_hash, str) or not expected_hash:
        raise HybridHoldoutError("Hybrid holdout source requires a sha256.")
    source_path = Path(path_value)
    if not source_path.is_absolute():
        source_path = (lock_path.parent / path_value).resolve()
    return source_key, source_path, expected_hash


def _load_entry_specs(
    raw_entries: object,
) -> list[tuple[str, str, tuple[str, ...]]]:
    if not isinstance(raw_entries, list) or not raw_entries:
        raise HybridHoldoutError("Hybrid holdout lock requires non-empty entries.")
    specs: list[tuple[str, str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise HybridHoldoutError("Each hybrid holdout entry must be an object.")
        question_id = raw_entry.get("id")
        source_key = raw_entry.get("source")
        case_tags = raw_entry.get("case_tags")
        if not isinstance(question_id, str) or not question_id:
            raise HybridHoldoutError("Hybrid holdout entry requires an id.")
        if not isinstance(source_key, str) or not source_key:
            raise HybridHoldoutError(
                f"Hybrid holdout entry {question_id!r} requires a source."
            )
        if not isinstance(case_tags, list) or not case_tags:
            raise HybridHoldoutError(
                f"Hybrid holdout entry {question_id!r} requires case_tags."
            )
        tags = tuple(str(tag) for tag in case_tags if isinstance(tag, str))
        if len(tags) != len(case_tags):
            raise HybridHoldoutError(
                f"Hybrid holdout entry {question_id!r} has invalid case_tags."
            )
        if question_id in seen:
            raise HybridHoldoutError(
                f"Hybrid holdout lock has duplicate entry id {question_id!r}."
            )
        seen.add(question_id)
        specs.append((question_id, source_key, tags))
    return specs


def _index_questions(
    source_manifest: dict[str, Any], source_path: Path
) -> dict[str, dict[str, Any]]:
    questions = source_manifest.get("questions")
    if not isinstance(questions, list) or not questions:
        raise HybridHoldoutError(f"Source manifest {source_path} has no questions.")
    indexed: dict[str, dict[str, Any]] = {}
    for question in questions:
        if not isinstance(question, dict):
            raise HybridHoldoutError(
                f"Source manifest {source_path} contains a non-object question."
            )
        question_id = question.get("id")
        if not isinstance(question_id, str) or not question_id:
            raise HybridHoldoutError(
                f"Source manifest {source_path} has a question without an id."
            )
        if question_id in indexed:
            raise HybridHoldoutError(
                f"Source manifest {source_path} has duplicate question id "
                f"{question_id!r}."
            )
        indexed[question_id] = question
    return indexed


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HybridHoldoutError(f"{label} is unreadable: {path}.") from error
    if not isinstance(payload, dict):
        raise HybridHoldoutError(f"{label} must be a JSON object: {path}.")
    return payload
