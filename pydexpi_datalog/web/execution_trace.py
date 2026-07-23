from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
import re

from pydexpi_datalog.qa.grounded_qa_harness import MAX_TRACE_REASONING_LENGTH

TRACE_SCHEMA_VERSION = 1
TRACE_EVENT_ID_LENGTH = 16
MAX_TRACE_EVENTS = 64
MAX_GROUP_OCCURRENCES = 20
MAX_SUMMARY_LENGTH = 160
MAX_EVIDENCE_REFERENCES = 25
MAX_SAFE_VALUE_LENGTH = 128

_EVENT_KINDS = {
    "template_proposed": "grounded_qa.routing.template_proposed",
    "template_validated": "grounded_qa.validation.template",
    "template_executed": "grounded_qa.execution.template",
    "template_execution_failed": "grounded_qa.execution.template_failed",
    "result_observed": "grounded_qa.evidence.result_observed",
    "route_outcome": "grounded_qa.routing.outcome",
}
_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_SAFE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")
_TRACE_STATUSES = {
    "blocked",
    "canceled",
    "completed",
    "failed",
    "pending",
    "running",
}
_SAFE_DETAIL_FIELDS = (
    "template_id",
    "template_version",
    "outcome",
    "engine",
    "verdict",
    "status",
    "route",
    "code",
)

# Live progress channel bounds (bead 3qo.9.12): the same redaction discipline
# as trace details, applied to per-round tool arguments and model reasoning.
# Single source of truth: the harness bounds reasoning at capture time and the
# progress channel applies the identical bound when persisting.
MAX_REASONING_LENGTH = MAX_TRACE_REASONING_LENGTH
MAX_PROGRESS_STRING_LENGTH = 400
MAX_PROGRESS_DETAIL_KEYS = 16
MAX_PROGRESS_LIST_ITEMS = 10
_BLOCKED_PROGRESS_KEY_PARTS = (
    "api_key",
    "authorization",
    "chain_of_thought",
    "credential",
    "password",
    "private",
    "secret",
    "system_prompt",
    "token",
)


def sanitize_progress_tool_input(value: object) -> dict[str, object]:
    """Bounded, redacted projection of a tool call's arguments for the live
    progress channel. Keys matching credential/prompt-like names are dropped;
    strings, lists, and nesting are truncated."""
    sanitized = _sanitize_progress_value(value, depth=0)
    return sanitized if isinstance(sanitized, dict) else {}


def bound_reasoning_text(value: object) -> str | None:
    """Bounded model reasoning excerpt; None for anything that is not a
    non-empty string -- absent reasoning is never fabricated."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:MAX_REASONING_LENGTH]


def _sanitize_progress_value(value: object, *, depth: int) -> object | None:
    if depth >= 3:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_PROGRESS_STRING_LENGTH]
    if isinstance(value, list):
        items = [
            item
            for raw in value[:MAX_PROGRESS_LIST_ITEMS]
            if (item := _sanitize_progress_value(raw, depth=depth + 1)) is not None
        ]
        return items
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for raw_key, raw_value in list(value.items())[:MAX_PROGRESS_DETAIL_KEYS]:
            key = str(raw_key)
            lowered = key.lower()
            if any(part in lowered for part in _BLOCKED_PROGRESS_KEY_PARTS):
                continue
            item = _sanitize_progress_value(raw_value, depth=depth + 1)
            if item is not None:
                sanitized[key] = item
        return sanitized
    return None


def render_execution_trace(
    *,
    artifact_root: Path,
    session_id: str,
    turn_id: str,
    raw_events: object,
    fallback_evidence_references: object,
) -> list[dict[str, object]]:
    """Project backend activity into bounded, user-visible trace envelopes."""
    if not isinstance(raw_events, list):
        return []

    fallback_evidence = _string_list(fallback_evidence_references)
    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    ordered_keys: list[tuple[str, str, str]] = []
    omitted = max(0, len(raw_events) - MAX_TRACE_EVENTS)
    for raw in raw_events[:MAX_TRACE_EVENTS]:
        if not isinstance(raw, Mapping):
            continue
        legacy_name = str(raw.get("event", "activity"))
        kind = _event_kind(legacy_name)
        template_id = _safe_value(raw.get("template_id"))
        outcome = _safe_value(raw.get("outcome"))
        key = (kind, template_id, outcome)
        sanitized = _sanitize_event_detail(raw)
        if key not in grouped:
            grouped[key] = {
                "kind": kind,
                "raw_name": legacy_name,
                "occurrences": [],
                "evidence_references": [],
                "count": 0,
                "template_id": template_id,
                "outcome": outcome,
                "first": sanitized,
                "status": _status(kind, sanitized),
            }
            ordered_keys.append(key)
        group = grouped[key]
        group["status"] = _status(kind, sanitized)
        raw_count = group["count"]
        assert isinstance(raw_count, int)
        group["count"] = raw_count + 1
        group_evidence = group["evidence_references"]
        assert isinstance(group_evidence, list)
        for reference in _string_list(raw.get("evidence_references")):
            if reference not in group_evidence:
                group_evidence.append(reference)
        occurrences = group["occurrences"]
        assert isinstance(occurrences, list)
        if len(occurrences) < MAX_GROUP_OCCURRENCES:
            occurrences.append(sanitized)

    rendered = [
        _render_group(
            artifact_root=artifact_root,
            session_id=session_id,
            turn_id=turn_id,
            group=grouped[key],
            fallback_evidence=fallback_evidence,
        )
        for key in ordered_keys
    ]
    if omitted:
        rendered.append(
            _render_omitted_group(
                artifact_root=artifact_root,
                session_id=session_id,
                turn_id=turn_id,
                omitted=omitted,
            )
        )
    return rendered


def _render_group(
    *,
    artifact_root: Path,
    session_id: str,
    turn_id: str,
    group: dict[str, object],
    fallback_evidence: list[str],
) -> dict[str, object]:
    kind = str(group["kind"])
    raw_count = group["count"]
    assert isinstance(raw_count, int)
    count = raw_count
    first = group["first"]
    assert isinstance(first, dict)
    raw_evidence = group["evidence_references"]
    assert isinstance(raw_evidence, list)
    evidence = sorted(str(reference) for reference in raw_evidence)[
        :MAX_EVIDENCE_REFERENCES
    ]
    if kind == "grounded_qa.evidence.result_observed" and not evidence:
        evidence = fallback_evidence[:MAX_EVIDENCE_REFERENCES]
    template_id = str(group["template_id"])
    outcome = str(group["outcome"])
    event_id = hashlib.sha256(
        f"{turn_id}\n{kind}\n{template_id}\n{outcome}".encode("utf-8")
    ).hexdigest()[:TRACE_EVENT_ID_LENGTH]
    relative_path = Path("turns") / f"{turn_id}.trace" / f"{event_id}.json"
    occurrences = group["occurrences"]
    assert isinstance(occurrences, list)
    detail = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "kind": kind,
        "occurrences": occurrences,
        "omitted_occurrence_count": max(0, count - len(occurrences)),
    }
    _write_artifact(artifact_root / session_id / relative_path, detail)
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "event_id": event_id,
        "kind": kind,
        "category": _category(kind),
        "status": str(group["status"]),
        "summary": _summary(kind, first, count),
        "occurrence_count": count,
        "evidence_references": evidence,
        "detail": {
            "display": "artifact",
            "artifact": {
                "kind": "execution_trace_detail",
                "path": relative_path.as_posix(),
                "media_type": "application/json",
            },
        },
    }


def _render_omitted_group(
    *,
    artifact_root: Path,
    session_id: str,
    turn_id: str,
    omitted: int,
) -> dict[str, object]:
    return _render_group(
        artifact_root=artifact_root,
        session_id=session_id,
        turn_id=turn_id,
        group={
            "kind": "grounded_qa.activity.omitted",
            "raw_name": "omitted",
            "occurrences": [{"omitted_count": omitted}],
            "evidence_references": [],
            "count": 1,
            "template_id": "",
            "outcome": "",
            "first": {"omitted_count": omitted},
        },
        fallback_evidence=[],
    )


def _event_kind(name: str) -> str:
    if name in _EVENT_KINDS:
        return _EVENT_KINDS[name]
    normalized = name[:128].strip().lower()
    if _KIND_PATTERN.fullmatch(normalized):
        return normalized
    safe_name = re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")[:80] or "unknown"
    return f"grounded_qa.activity.{safe_name}"


def _category(kind: str) -> str:
    for category in ("routing", "validation", "execution", "evidence"):
        if f".{category}." in kind:
            return category
    return "activity"


def _status(kind: str, detail: Mapping[str, object]) -> str:
    status = _safe_value(detail.get("status")).lower()
    if status in _TRACE_STATUSES:
        return status
    outcome = _safe_value(detail.get("outcome")).lower()
    if kind.endswith("_failed") or outcome in {"rejected", "failed"}:
        return "failed"
    return "completed"


def _summary(kind: str, detail: Mapping[str, object], count: int) -> str:
    template_id = _safe_value(detail.get("template_id")) or "bundled template"
    if kind == "grounded_qa.routing.template_proposed":
        summary = f"Routed to template {template_id}."
    elif kind == "grounded_qa.validation.template":
        outcome = _safe_value(detail.get("outcome")) or "completed"
        summary = f"Validated template {template_id}: {outcome}."
    elif kind == "grounded_qa.execution.template":
        engine = _safe_value(detail.get("engine")) or "reasoning engine"
        summary = f"Executed template {template_id} with {engine}."
    elif kind == "grounded_qa.execution.template_failed":
        summary = f"Template execution failed for {template_id}."
    elif kind == "grounded_qa.evidence.result_observed":
        verdict = _safe_value(detail.get("verdict")) or "result observed"
        witness_count = detail.get("witness_count")
        suffix = (
            f" with {witness_count} witness(es)"
            if isinstance(witness_count, int)
            else ""
        )
        summary = f"Observed deterministic result: {verdict}{suffix}."
    elif kind == "grounded_qa.routing.outcome":
        route = _safe_value(detail.get("route"))
        outcome = _safe_value(detail.get("status")) or _safe_value(
            detail.get("outcome")
        )
        route_detail = ": ".join(item for item in (route, outcome) if item)
        summary = (
            f"Recorded routing outcome: {route_detail}."
            if route_detail
            else "Recorded routing outcome."
        )
    elif kind == "grounded_qa.activity.omitted":
        summary = f"Omitted {detail.get('omitted_count', 0)} additional trace event(s)."
    else:
        summary = f"Recorded extension activity: {kind}."
    if count > 1:
        summary = f"{summary.rstrip('.')} ({count} occurrences)."
    return summary[:MAX_SUMMARY_LENGTH]


def _sanitize_event_detail(raw: Mapping[object, object]) -> dict[str, object]:
    detail: dict[str, object] = {}
    for field in _SAFE_DETAIL_FIELDS:
        value = _safe_value(raw.get(field))
        if value:
            detail[field] = value
    witness_count = raw.get("witness_count")
    if isinstance(witness_count, int) and 0 <= witness_count <= 1_000_000:
        detail["witness_count"] = witness_count
    evidence_references = _string_list(raw.get("evidence_references"))
    if evidence_references:
        detail["evidence_references"] = evidence_references
    return detail


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({safe for item in value if (safe := _safe_value(item))})[
        :MAX_EVIDENCE_REFERENCES
    ]


def _safe_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    bounded = value[:MAX_SAFE_VALUE_LENGTH]
    return bounded if _SAFE_VALUE_PATTERN.fullmatch(bounded) else ""


def _write_artifact(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
