from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from .workflow_policy import OSS_POLICY, count_manifest_source_files


SCHEMA_VERSION = 1
ALLOWED_EXECUTION_MODES = {"dry-run", "normal"}
ALLOWED_LIFECYCLE_STATES = {"draft", "active", "deprecated", "retired"}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    dexpi_xml: Path
    rule_pack_name: str
    rule_pack_path: Path | None
    rule_pack_version: int
    rule_pack_lifecycle_state: str
    execution_mode: str
    run_id: str
    artifact_dir: Path


def default_artifact_dir() -> Path:
    return Path.cwd() / "artifacts"


def load_manifest_file(path: Path) -> tuple[object | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []

    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        diagnostics.append(
            Diagnostic(
                code="manifest.missing_file",
                severity="error",
                message=f"Manifest file does not exist: {path}",
                path="manifest",
            )
        )
        return None, diagnostics

    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                Diagnostic(
                    code="manifest.invalid_json",
                    severity="error",
                    message=f"Manifest is not valid JSON: {exc.msg}",
                    path=f"manifest:{exc.lineno}:{exc.colno}",
                )
            )
            return None, diagnostics
        return raw, diagnostics

    if suffix in {".yaml", ".yml"}:
        try:
            raw = parse_simple_yaml(raw_text)
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    code="manifest.invalid_yaml",
                    severity="error",
                    message=f"Manifest is not valid YAML: {exc}",
                    path="manifest",
                )
            )
            return None, diagnostics
        return raw, diagnostics

    diagnostics.append(
        Diagnostic(
            code="manifest.unsupported_format",
            severity="error",
            message="Manifest must use .json, .yaml, or .yml.",
            path="manifest",
        )
    )
    return None, diagnostics


def parse_simple_yaml(raw_text: str) -> dict[str, object]:
    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]

    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError(f"line {line_number} uses odd indentation")

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        current = stack[-1][1]
        line = raw_line.strip()
        if ":" not in line:
            raise ValueError(f"line {line_number} is missing ':'")

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            raise ValueError(f"line {line_number} has an empty key")

        if not value:
            child: dict[str, object] = {}
            current[key] = child
            stack.append((indent, child))
            continue

        current[key] = parse_yaml_scalar(value)

    return root


def parse_yaml_scalar(value: str) -> object:
    if value.isdigit():
        return int(value)
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    return value


def best_effort_output_context(
    raw: object, manifest_path: Path
) -> tuple[Path, str]:
    fallback_dir = default_artifact_dir()
    fallback_run_id = f"{manifest_path.stem}-validation-failed"

    if not isinstance(raw, dict):
        return fallback_dir, fallback_run_id

    output = raw.get("output")
    if not isinstance(output, dict):
        return fallback_dir, fallback_run_id

    run_id = output.get("run_id")

    resolved_dir = fallback_dir
    resolved_run_id = run_id if isinstance(run_id, str) and run_id else fallback_run_id
    return resolved_dir, resolved_run_id


def validate_manifest(raw: object) -> tuple[Manifest | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if not isinstance(raw, dict):
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_type",
                severity="error",
                message="Manifest root must be a JSON object.",
                path="manifest",
            )
        )
        return None, diagnostics

    allowed_top_level = {"schema_version", "input", "rule_pack", "execution", "output"}
    for key in sorted(raw):
        if key not in allowed_top_level:
            diagnostics.append(
                Diagnostic(
                    code="manifest.unknown_field",
                    severity="error",
                    message=f"Unknown top-level field: {key}",
                    path=key,
                )
            )

    schema_version = raw.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_schema_version",
                severity="error",
                message=f"schema_version must be {SCHEMA_VERSION}.",
                path="schema_version",
            )
        )

    input_block = raw.get("input")
    source_file_count = count_manifest_source_files(input_block)
    if source_file_count > OSS_POLICY.max_source_files:
        diagnostics.append(
            Diagnostic(
                code="workflow_policy.too_many_source_files",
                severity="error",
                message=(
                    "OSS workflow policy supports one DEXPI source file per run. "
                    f"Received {source_file_count}."
                ),
                path="input",
            )
        )
    dexpi_xml = _require_string_field(input_block, "dexpi_xml", "input", diagnostics)

    rule_pack = raw.get("rule_pack")
    rule_pack_name = _require_string_field(rule_pack, "name", "rule_pack", diagnostics)
    rule_pack_path = _optional_string_field(rule_pack, "path", "rule_pack", diagnostics)
    rule_pack_version = _require_int_field(
        rule_pack, "version", "rule_pack", diagnostics
    )
    lifecycle_state = _require_string_field(
        rule_pack, "lifecycle_state", "rule_pack", diagnostics
    )
    if lifecycle_state and lifecycle_state not in ALLOWED_LIFECYCLE_STATES:
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_lifecycle_state",
                severity="error",
                message=(
                    "rule_pack.lifecycle_state must be one of "
                    f"{sorted(ALLOWED_LIFECYCLE_STATES)}."
                ),
                path="rule_pack.lifecycle_state",
            )
        )

    execution = raw.get("execution")
    execution_mode = _require_string_field(
        execution, "mode", "execution", diagnostics
    )
    if execution_mode and execution_mode not in ALLOWED_EXECUTION_MODES:
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_execution_mode",
                severity="error",
                message=(
                    "execution.mode must be one of "
                    f"{sorted(ALLOWED_EXECUTION_MODES)}."
                ),
                path="execution.mode",
            )
        )

    output = raw.get("output")
    run_id = _require_string_field(output, "run_id", "output", diagnostics)
    if not isinstance(output, dict):
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_section",
                severity="error",
                message="output must be an object.",
                path="output",
            )
        )
        output = None

    if diagnostics:
        return None, diagnostics

    manifest = Manifest(
        schema_version=schema_version,
        dexpi_xml=Path(dexpi_xml).expanduser(),
        rule_pack_name=rule_pack_name,
        rule_pack_path=Path(rule_pack_path).expanduser() if rule_pack_path else None,
        rule_pack_version=rule_pack_version,
        rule_pack_lifecycle_state=lifecycle_state,
        execution_mode=execution_mode,
        run_id=run_id,
        artifact_dir=default_artifact_dir(),
    )
    return manifest, diagnostics


def _require_string_field(
    block: object, field: str, parent: str, diagnostics: list[Diagnostic]
) -> str | None:
    if not isinstance(block, dict):
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_section",
                severity="error",
                message=f"{parent} must be an object.",
                path=parent,
            )
        )
        return None

    value = block.get(field)
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_string",
                severity="error",
                message=f"{parent}.{field} must be a non-empty string.",
                path=f"{parent}.{field}",
            )
        )
        return None
    return value


def _require_int_field(
    block: object, field: str, parent: str, diagnostics: list[Diagnostic]
) -> int | None:
    if not isinstance(block, dict):
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_section",
                severity="error",
                message=f"{parent} must be an object.",
                path=parent,
            )
        )
        return None

    value = block.get(field)
    if not isinstance(value, int):
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_integer",
                severity="error",
                message=f"{parent}.{field} must be an integer.",
                path=f"{parent}.{field}",
            )
        )
        return None
    return value


def _optional_string_field(
    block: object, field: str, parent: str, diagnostics: list[Diagnostic]
) -> str | None:
    if not isinstance(block, dict):
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_section",
                severity="error",
                message=f"{parent} must be an object.",
                path=parent,
            )
        )
        return None

    value = block.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(
            Diagnostic(
                code="manifest.invalid_string",
                severity="error",
                message=f"{parent}.{field} must be a non-empty string when provided.",
                path=f"{parent}.{field}",
            )
        )
        return None
    return value
