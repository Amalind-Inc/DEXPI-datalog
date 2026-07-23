"""Mechanical validation for generated-query semantic intent contracts."""

from __future__ import annotations
import base64
import binascii
import json
import re

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


def encode_structured_intent_program(
    program: str, structured_intent: Mapping[str, object]
) -> str:
    """Embed a canonical intent fact and require it in every answer rule."""
    normalized, diagnostics = normalize_structured_intent(structured_intent)
    if diagnostics or normalized is None:
        raise ValueError("Cannot encode an invalid structured intent.")
    payload = _intent_payload(normalized)
    guard = f'query_intent_contract("{payload}")'
    guarded_lines: list[str] = []
    answer_count = 0
    for line in program.splitlines():
        stripped = line.strip()
        if stripped.startswith("answer("):
            answer_count += 1
            if ":-" in line:
                line = line.replace(":-", f":- {guard},", 1)
            elif line.rstrip().endswith("."):
                line = line.rstrip()[:-1] + f" :- {guard}."
        guarded_lines.append(line)
    if answer_count == 0:
        raise ValueError("Structured intent programs require an answer rule.")
    contract = f".decl query_intent_contract(payload:symbol)\n{guard}."
    return contract + "\n" + "\n".join(guarded_lines)


def compare_program_structured_intent(
    requested: Mapping[str, object], program: str
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Extract the intent contract from executable Datalog and compare it."""
    encoded, diagnostics = _extract_program_intent(program)
    if diagnostics or encoded is None:
        return None, diagnostics
    return compare_structured_intents(requested, encoded)


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


def _without_datalog_comments(program: str) -> str:
    """Remove line/block comments without treating comment markers in strings as syntax."""
    cleaned: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(program):
        character = program[index]
        following = program[index + 1] if index + 1 < len(program) else ""
        if in_string:
            cleaned.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            cleaned.append(character)
            index += 1
            continue
        if character == "/" and following == "/":
            newline = program.find("\n", index + 2)
            if newline == -1:
                break
            cleaned.append("\n")
            index = newline + 1
            continue
        if character == "/" and following == "*":
            closing = program.find("*/", index + 2)
            if closing == -1:
                break
            cleaned.extend(
                "\n" for char in program[index : closing + 2] if char == "\n"
            )
            index = closing + 2
            continue
        cleaned.append(character)
        index += 1
    return "".join(cleaned)


def _extract_program_intent(
    program: str,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    executable_program = _without_datalog_comments(program)
    declaration = ".decl query_intent_contract(payload:symbol)"
    if executable_program.count(declaration) != 1:
        return None, [
            _contract_invalid(
                "contract",
                "Generated query must declare exactly one query_intent_contract.",
            )
        ]
    payloads = set(
        re.findall(
            r'query_intent_contract\("([A-Za-z0-9_-]+)"\)',
            executable_program,
        )
    )
    if len(payloads) != 1:
        return None, [
            _contract_invalid(
                "contract",
                "Generated query must use exactly one structured intent payload.",
            )
        ]
    payload = next(iter(payloads))
    guard = f'query_intent_contract("{payload}")'
    if f"{guard}." not in {line.strip() for line in executable_program.splitlines()}:
        return None, [
            _contract_invalid(
                "contract",
                "Generated query must define its structured intent contract fact.",
            )
        ]
    answer_rules = [
        line.strip()
        for line in executable_program.splitlines()
        if line.strip().startswith("answer(")
    ]
    guard_atom = re.compile(rf"(?:^|,)\s*{re.escape(guard)}\s*(?:,|\.|$)")
    if not answer_rules or any(
        ":-" not in rule or guard_atom.search(rule.split(":-", 1)[1]) is None
        for rule in answer_rules
    ):
        return None, [
            _contract_invalid(
                "output_obligations",
                "Every answer rule must be guarded by the structured intent contract.",
            )
        ]
    try:
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
        raw_intent = json.loads(decoded)
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None, [
            _contract_invalid(
                "contract",
                "Generated query structured intent payload is invalid.",
            )
        ]
    normalized, diagnostics = normalize_structured_intent(raw_intent)
    if diagnostics or normalized is None:
        return None, diagnostics
    if payload != _intent_payload(normalized):
        return None, [
            _contract_invalid(
                "contract",
                "Generated query structured intent payload must use canonical encoding.",
            )
        ]
    return normalized, []


def _intent_payload(intent: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(intent),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(canonical).decode("ascii").rstrip("=")


def _contract_invalid(field: str, message: str) -> dict[str, object]:
    return {
        "code": "structured_intent.program_contract_invalid",
        "field": field,
        "message": message,
    }


def _invalid(field: str, requirement: str, encoded: object) -> dict[str, object]:
    return {
        "code": "structured_intent.invalid",
        "field": field,
        "encoded": encoded,
        "message": f"Structured intent field {field!r} {requirement}.",
    }
