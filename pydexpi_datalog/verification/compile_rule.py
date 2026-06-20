from __future__ import annotations

import json
from pathlib import Path

import yaml


def run_compile_rule(*, rule_yaml_path: Path, output_dir: Path) -> int:
    rule = yaml.safe_load(rule_yaml_path.read_text(encoding="utf-8"))
    rule_id = rule["rule_id"]
    artifact_dir = output_dir / rule_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    (artifact_dir / rule_yaml_path.name).write_text(
        rule_yaml_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    diagnostics = validate_rule(rule)
    if diagnostics:
        (artifact_dir / "rule_compilation.json").write_text(
            json.dumps(
                {
                    "diagnostics": diagnostics,
                    "rule_id": rule_id,
                    "status": "invalid",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(render_console_report(rule_id, status="invalid"))
        return 1

    datalog = compile_rule_to_datalog(rule)
    (artifact_dir / "rule.dl").write_text(datalog, encoding="utf-8")
    (artifact_dir / "rule_compilation.json").write_text(
        json.dumps({"rule_id": rule_id, "status": "ok"}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(render_console_report(rule_id, status="ok"))
    return 0


def compile_rule_to_datalog(rule: dict[str, object]) -> str:
    applies_to = rule["applies_to"]
    require = rule["require"]
    lines = [
        '.decl rule_subject_class(rule:symbol, class:symbol)',
        '.decl rule_required_component_class(rule:symbol, class:symbol)',
        "",
        f'rule_subject_class("{rule["rule_id"]}", "{applies_to["subject_class"]}").',
        f'rule_required_component_class("{rule["rule_id"]}", "{require["component_class"]}").',
    ]
    return "\n".join(lines) + "\n"


def validate_rule(rule: dict[str, object]) -> list[dict[str, str]]:
    required_paths = [
        ("rule_id", ["rule_id"]),
        ("applies_to.subject_class", ["applies_to", "subject_class"]),
        ("require.component_class", ["require", "component_class"]),
    ]
    diagnostics: list[dict[str, str]] = []
    for dotted_path, path_parts in required_paths:
        current: object = rule
        missing = False
        for part in path_parts:
            if not isinstance(current, dict) or part not in current:
                missing = True
                break
            current = current[part]
        if missing:
            diagnostics.append(
                {
                    "code": "rule.missing_required_field",
                    "message": f"Missing required field: {dotted_path}",
                    "path": dotted_path,
                    "severity": "error",
                }
            )
    return diagnostics


def render_console_report(rule_id: str, *, status: str) -> str:
    return "\n".join(
        [
            "Compiled Rule",
            f"Rule ID: {rule_id}",
            f"Status: {status}",
        ]
    )
