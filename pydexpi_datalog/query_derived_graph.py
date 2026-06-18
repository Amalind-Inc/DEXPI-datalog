from __future__ import annotations

from pathlib import Path
import csv
import json
import shutil
import subprocess
import tempfile

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
QUERY_CORPUS_DIR = REPO_ROOT / "queries" / "corpus"


def run_query_derived_graph(
    *,
    query_id: str,
    derived_graph_semantics_path: Path,
    source_id: str,
    output_dir: Path | None = None,
) -> int:
    query_entry = load_query_entry(query_id)
    if query_entry["status"] != "supported_deterministic":
        print(render_unsupported_report(query_entry))
        return 0

    if query_id != "compare_known_object_reachability":
        print(f"Unsupported query implementation: {query_id}")
        return 2

    generated_query_datalog = build_compare_reachability_query_datalog(source_id)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        artifact_dir = output_dir or tmp_path
        artifact_dir.mkdir(parents=True, exist_ok=True)
        raw_output_dir = artifact_dir / "internal" / "souffle-output"
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        combined_program_path = artifact_dir / "combined_query.dl"
        combined_program = build_compare_reachability_program(
            derived_graph_semantics_path=derived_graph_semantics_path,
            generated_query_datalog=generated_query_datalog,
        )
        combined_program_path.write_text(combined_program, encoding="utf-8")

        souffle_path = shutil.which("souffle")
        if souffle_path is None:
            diagnostic = {
                "code": "missing_souffle",
                "message": "Missing required deterministic engine: souffle",
            }
            if output_dir is not None:
                persist_query_result(
                    output_dir=artifact_dir,
                    query_entry=query_entry,
                    source_id=source_id,
                    generated_query_datalog=generated_query_datalog,
                    combined_program_path=combined_program_path,
                    raw_output_dir=raw_output_dir,
                    reachable_targets=[],
                    downstream_reference_targets=[],
                    diagnostics=[diagnostic],
                    status="failed",
                )
            print(diagnostic["message"])
            return 1

        result = subprocess.run(
            [souffle_path, str(combined_program_path), "-D", str(raw_output_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            diagnostic = {
                "code": "souffle_execution_failed",
                "message": "Souffle query execution failed",
            }
            if result.stderr:
                diagnostic["stderr"] = result.stderr
            if output_dir is not None:
                persist_query_result(
                    output_dir=artifact_dir,
                    query_entry=query_entry,
                    source_id=source_id,
                    generated_query_datalog=generated_query_datalog,
                    combined_program_path=combined_program_path,
                    raw_output_dir=raw_output_dir,
                    reachable_targets=[],
                    downstream_reference_targets=[],
                    diagnostics=[diagnostic],
                    status="failed",
                )
            print("Souffle query execution failed")
            if result.stderr:
                print(result.stderr)
            return result.returncode

        reachable_targets = read_symbol_pairs(raw_output_dir / "query_reachable.csv")
        downstream_reference_targets = read_symbol_pairs(
            raw_output_dir / "query_downstream_reference.csv"
        )
        diagnostics = source_presence_diagnostics(
            raw_output_dir / "query_source_exists.csv"
        )

        if output_dir is not None:
            persist_query_result(
                output_dir=artifact_dir,
                query_entry=query_entry,
                source_id=source_id,
                generated_query_datalog=generated_query_datalog,
                combined_program_path=combined_program_path,
                raw_output_dir=raw_output_dir,
                reachable_targets=reachable_targets,
                downstream_reference_targets=downstream_reference_targets,
                diagnostics=diagnostics,
                status="success",
            )

    print(
        render_compare_reachability_report(
            query_entry=query_entry,
            source_id=source_id,
            reachable_targets=reachable_targets,
            downstream_reference_targets=downstream_reference_targets,
            diagnostics=diagnostics,
        )
    )
    return 0


def load_query_entry(query_id: str) -> dict[str, object]:
    entry_path = QUERY_CORPUS_DIR / f"{query_id}.yaml"
    return yaml.safe_load(entry_path.read_text(encoding="utf-8"))


def build_compare_reachability_program(
    *, derived_graph_semantics_path: Path, generated_query_datalog: str
) -> str:
    derived_program = derived_graph_semantics_path.read_text(encoding="utf-8")
    return derived_program + "\n" + generated_query_datalog


def build_compare_reachability_query_datalog(source_id: str) -> str:
    source = souffle_symbol(source_id)
    return "\n".join(
        [
            ".decl query_reachable(target:symbol, label:symbol)",
            ".decl query_downstream_reference(target:symbol, label:symbol)",
            ".decl query_source_exists(source:symbol)",
            ".output query_reachable",
            ".output query_downstream_reference",
            ".output query_source_exists",
            f"query_reachable(target, label) :- reachable({source}, target), node_label(target, label).",
            f"query_downstream_reference(target, label) :- downstream_reference({source}, target), node_label(target, label).",
            f"query_source_exists({source}) :- node({source}).",
            "",
        ]
    )


def source_presence_diagnostics(path: Path) -> list[dict[str, str]]:
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return []
    return [
        {
            "code": "source_id_absent",
            "message": "Warning: source ID is absent from node facts",
        }
    ]


def persist_query_result(
    *,
    output_dir: Path,
    query_entry: dict[str, object],
    source_id: str,
    generated_query_datalog: str,
    combined_program_path: Path,
    raw_output_dir: Path,
    reachable_targets: list[tuple[str, str]],
    downstream_reference_targets: list[tuple[str, str]],
    diagnostics: list[dict[str, str]],
    status: str,
) -> None:
    artifact = {
        "status": status,
        "query": {
            "id": query_entry["id"],
            "status": query_entry["status"],
            "question": query_entry["question"],
        },
        "source_id": source_id,
        "generated_query_datalog": generated_query_datalog,
        "combined_program_path": str(combined_program_path),
        "raw_output_dir": str(raw_output_dir),
        "diagnostics": diagnostics,
        "result_sets": {
            "reachable_targets": render_result_set(reachable_targets),
            "downstream_reference_targets": render_result_set(
                downstream_reference_targets
            ),
        },
    }
    (output_dir / "query_result.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
    )


def render_result_set(targets: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"target_id": target_id, "label": label} for target_id, label in targets]


def souffle_symbol(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def read_symbol_pairs(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.reader(file, delimiter="\t")
        return sorted((row[0], row[1]) for row in reader if len(row) >= 2)


def render_compare_reachability_report(
    *,
    query_entry: dict[str, object],
    source_id: str,
    reachable_targets: list[tuple[str, str]],
    downstream_reference_targets: list[tuple[str, str]],
    diagnostics: list[dict[str, str]],
) -> str:
    diagnostic_lines = [diagnostic["message"] for diagnostic in diagnostics]
    return "\n".join(
        [
            "P&ID QA Query",
            f"Query ID: {query_entry['id']}",
            f"Question: {query_entry['question']}",
            f"Source ID: {source_id}",
            *diagnostic_lines,
            "",
            render_side_by_side_targets(
                reachable_targets=reachable_targets,
                downstream_reference_targets=downstream_reference_targets,
            ),
        ]
    )


def render_side_by_side_targets(
    *,
    reachable_targets: list[tuple[str, str]],
    downstream_reference_targets: list[tuple[str, str]],
) -> str:
    rows = [
        "Reachable targets                                 | Downstream reference targets"
    ]
    row_count = max(len(reachable_targets), len(downstream_reference_targets), 1)
    for index in range(row_count):
        reachable = target_text(reachable_targets, index)
        downstream_reference = target_text(downstream_reference_targets, index)
        rows.append(f"{reachable:<49} | {downstream_reference}")
    return "\n".join(rows)


def target_text(targets: list[tuple[str, str]], index: int) -> str:
    if not targets:
        return "(none)" if index == 0 else ""
    if index >= len(targets):
        return ""
    target_id, label = targets[index]
    return f"{target_id}  {label}"


def render_unsupported_report(query_entry: dict[str, object]) -> str:
    return "\n".join(
        [
            "P&ID QA Query",
            f"Query ID: {query_entry['id']}",
            f"Status: {query_entry['status']}",
        ]
    )
