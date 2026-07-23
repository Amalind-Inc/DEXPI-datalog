"""Mechanical validation for generated-query semantic intent contracts."""

from __future__ import annotations

from collections.abc import Mapping


_INTENT_FIELDS = (
    "source_classes",
    "target_classes",
    "source_role",
    "target_role",
    "graph_scope",
    "direction",
    "quantifier",
    "negated",
    "output_obligations",
)
_LIST_FIELDS = {"source_classes", "target_classes", "output_obligations"}
_ALLOWED_VALUES = {
    "graph_scope": {"all_topology", "instrumentation_inclusive", "piping_only"},
    "direction": {"directed", "undirected"},
    "quantifier": {"all", "any"},
}

STRUCTURED_INTENT_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "source_classes": {"type": "array", "items": {"type": "string"}},
        "target_classes": {"type": "array", "items": {"type": "string"}},
        "source_role": {"type": "string"},
        "target_role": {"type": "string"},
        "graph_scope": {
            "type": "string",
            "enum": ["all_topology", "instrumentation_inclusive", "piping_only"],
        },
        "direction": {"type": "string", "enum": ["directed", "undirected"]},
        "quantifier": {"type": "string", "enum": ["all", "any"]},
        "negated": {"type": "boolean"},
        "output_obligations": {"type": "array", "items": {"type": "string"}},
    },
    "required": list(_INTENT_FIELDS),
    "additionalProperties": False,
}


def normalize_structured_intent(
    value: object,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Return a canonical closed intent contract or structured diagnostics."""
    diagnostics: list[dict[str, object]] = []
    if not isinstance(value, Mapping):
        return None, [_invalid("structured_intent", "must be an object", value)]

    keys = {str(key) for key in value}
    expected_keys = set(_INTENT_FIELDS)
    for field in sorted(expected_keys - keys):
        diagnostics.append(_invalid(field, "is required", None))
    for field in sorted(keys - expected_keys):
        diagnostics.append(_invalid(field, "is not supported", value.get(field)))

    normalized: dict[str, object] = {}
    for field in _INTENT_FIELDS:
        raw = value.get(field)
        if field in _LIST_FIELDS:
            if (
                not isinstance(raw, list)
                or not raw
                or any(not isinstance(item, str) or not item.strip() for item in raw)
            ):
                diagnostics.append(
                    _invalid(field, "must be a non-empty list of strings", raw)
                )
                continue
            items = [item.strip() for item in raw]
            if len(set(items)) != len(items):
                diagnostics.append(_invalid(field, "must not contain duplicates", raw))
                continue
            normalized[field] = sorted(items)
            continue
        if field == "negated":
            if not isinstance(raw, bool):
                diagnostics.append(_invalid(field, "must be a boolean", raw))
                continue
            normalized[field] = raw
            continue
        if not isinstance(raw, str) or not raw.strip():
            diagnostics.append(_invalid(field, "must be a non-empty string", raw))
            continue
        candidate = raw.strip()
        allowed = _ALLOWED_VALUES.get(field)
        if allowed is not None and candidate not in allowed:
            diagnostics.append(
                _invalid(field, "must be one of " + ", ".join(sorted(allowed)), raw)
            )
            continue
        normalized[field] = candidate

    if diagnostics:
        return None, diagnostics
    return normalized, []


def compare_structured_intents(
    requested: Mapping[str, object], encoded: object
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Compare every semantic obligation in the encoded query contract."""
    normalized_encoded, diagnostics = normalize_structured_intent(encoded)
    if diagnostics or normalized_encoded is None:
        return None, diagnostics

    mismatches: list[dict[str, object]] = []
    for field in _INTENT_FIELDS:
        requested_value = requested[field]
        encoded_value = normalized_encoded[field]
        if requested_value != encoded_value:
            mismatches.append(
                {
                    "code": f"structured_intent.{field}_mismatch",
                    "field": field,
                    "requested": requested_value,
                    "encoded": encoded_value,
                    "message": (
                        f"Generated query changed {field}: requested "
                        f"{requested_value!r}, encoded {encoded_value!r}."
                    ),
                }
            )
    return normalized_encoded, mismatches


def _invalid(field: str, requirement: str, encoded: object) -> dict[str, object]:
    return {
        "code": "structured_intent.invalid",
        "field": field,
        "encoded": encoded,
        "message": f"Structured intent field {field!r} {requirement}.",
    }
