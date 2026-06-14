from __future__ import annotations


def validate_result_schema(result: dict[str, object]) -> list[dict[str, str]]:
    required_paths = [
        ("schema_version", ["schema_version"]),
        ("result_type", ["result_type"]),
        ("rule_id", ["rule_id"]),
        ("message", ["message"]),
        ("subject.pump_id", ["subject", "pump_id"]),
        ("subject.discharge_nozzle_id", ["subject", "discharge_nozzle_id"]),
        ("evidence.traversed_objects", ["evidence", "traversed_objects"]),
        ("evidence.traversed_edges", ["evidence", "traversed_edges"]),
        ("evidence.boundary.kind", ["evidence", "boundary", "kind"]),
        ("evidence.boundary.object_id", ["evidence", "boundary", "object_id"]),
    ]
    diagnostics: list[dict[str, str]] = []
    for dotted_path, path_parts in required_paths:
        current: object = result
        missing = False
        for part in path_parts:
            if not isinstance(current, dict) or part not in current:
                missing = True
                break
            current = current[part]
        if missing:
            diagnostics.append(
                {
                    "code": "result.missing_required_field",
                    "message": f"Missing required field: {dotted_path}",
                    "path": dotted_path,
                    "severity": "error",
                }
            )
    return diagnostics
