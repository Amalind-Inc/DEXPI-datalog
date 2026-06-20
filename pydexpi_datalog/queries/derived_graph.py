from __future__ import annotations

from pathlib import Path
import csv
import json
import shutil
import subprocess
import tempfile

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
QUERY_CORPUS_DIR = REPO_ROOT / "queries" / "corpus"


def run_query_derived_graph(
    *,
    query_id: str,
    derived_graph_semantics_path: Path,
    source_id: str | None,
    source_tag: str | None = None,
    source_proteus_id: str | None = None,
    output_dir: Path | None = None,
) -> int:
    query_entry = load_query_entry(query_id)
    source_selection = build_source_selection(
        source_id=source_id,
        source_tag=source_tag,
        source_proteus_id=source_proteus_id,
    )
    query_scope = query_entry.get("query_scope", {"kind": "source_rooted"})
    if query_scope == {"kind": "source_rooted"} and source_selection["selectors"] == {}:
        print("Missing source selector: provide --source-id, --source-tag, or --source-proteus-id")
        return 2

    if query_entry["status"] != "supported_deterministic":
        if output_dir is not None:
            persist_unsupported_query_result(
                output_dir=output_dir,
                query_entry=query_entry,
                source_id=source_id,
            )
        print(render_unsupported_report(query_entry))
        return 0

    if query_id not in {
        "compare_known_object_reachability",
        "compare_direct_process_connections",
    }:
        print(f"Unsupported query implementation: {query_id}")
        return 2

    source_id, source_selection_diagnostic = resolve_source_selection(
        derived_graph_semantics_path=derived_graph_semantics_path,
        source_selection=source_selection,
    )
    if source_selection_diagnostic is not None:
        if output_dir is not None:
            persist_source_selection_failure(
                output_dir=output_dir,
                query_entry=query_entry,
                source_selection=source_selection,
                diagnostic=source_selection_diagnostic,
            )
        print(source_selection_diagnostic["message"])
        return 1
    source_selection["resolved_source_id"] = source_id

    if query_id == "compare_direct_process_connections":
        generated_query_datalog = build_compare_direct_process_connections_query_datalog(
            source_id
        )
    else:
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
        direct_process_connection_targets = None
        comparison_summary = None
        if query_id == "compare_direct_process_connections":
            direct_process_connection_targets = read_symbol_pairs(
                raw_output_dir / "query_direct_process_connection.csv"
            )
            comparison_summary = compare_direct_process_connection_sets(
                direct_process_connection_targets=direct_process_connection_targets,
                downstream_reference_targets=downstream_reference_targets,
                reachable_targets=reachable_targets,
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
                direct_process_connection_targets=direct_process_connection_targets,
                comparison_summary=comparison_summary,
                source_selection=source_selection,
                diagnostics=diagnostics,
                status="success",
            )

    if query_id == "compare_direct_process_connections":
        print(
            render_compare_direct_process_connections_report(
                query_entry=query_entry,
                source_id=source_id,
                direct_process_connection_targets=direct_process_connection_targets or [],
                downstream_reference_targets=downstream_reference_targets,
                reachable_targets=reachable_targets,
                comparison_summary=comparison_summary or {},
                diagnostics=diagnostics,
            )
        )
    else:
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


def build_source_selection(
    *, source_id: str | None, source_tag: str | None, source_proteus_id: str | None
) -> dict[str, object]:
    selectors = {}
    if source_id is not None:
        selectors["source_id"] = source_id
    if source_tag is not None:
        selectors["source_tag"] = source_tag
    if source_proteus_id is not None:
        selectors["source_proteus_id"] = source_proteus_id
    return {
        "resolution_scope": {"kind": "single_dexpi_source_file"},
        "resolution_source": "derived_graph_semantics",
        "resolved_source_id": source_id,
        "selectors": selectors,
    }


def resolve_source_selection(
    *, derived_graph_semantics_path: Path, source_selection: dict[str, object]
) -> tuple[str | None, dict[str, str] | None]:
    selectors = source_selection["selectors"]
    source_id = selectors.get("source_id")
    candidate_ids = {source_id} if isinstance(source_id, str) else set()
    if set(selectors) == {"source_id"}:
        return source_id if isinstance(source_id, str) else None, None

    generated_query_datalog = build_source_selector_query_datalog(selectors)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_output_dir = tmp_path / "souffle-output"
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        combined_program_path = tmp_path / "source_selector_query.dl"
        combined_program_path.write_text(
            build_compare_reachability_program(
                derived_graph_semantics_path=derived_graph_semantics_path,
                generated_query_datalog=generated_query_datalog,
            ),
            encoding="utf-8",
        )
        souffle_path = shutil.which("souffle")
        if souffle_path is None:
            return None, {
                "code": "missing_souffle",
                "message": "Missing required deterministic engine: souffle",
            }
        result = subprocess.run(
            [souffle_path, str(combined_program_path), "-D", str(raw_output_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None, {
                "code": "source_selector_resolution_failed",
                "message": "Source selector resolution failed",
            }
        rows = read_symbol_pairs(raw_output_dir / "query_source_selector.csv")
        selector_matches: dict[str, set[str]] = {}
        for matched_source_id, selector_kind in rows:
            selector_matches.setdefault(selector_kind, set()).add(matched_source_id)
            candidate_ids.add(matched_source_id)

        for selector_kind in ("source_tag", "source_proteus_id"):
            if selector_kind in selectors and selector_kind not in selector_matches:
                return None, {
                    "code": "source_selector_no_match",
                    "message": "Source selector did not resolve to a graph node",
                }
            if len(selector_matches.get(selector_kind, set())) > 1:
                return None, {
                    "code": "source_selector_ambiguous",
                    "message": "Source selector resolved to multiple graph nodes",
                }

        if len(candidate_ids) != 1:
            return None, {
                "code": "source_selector_mismatch",
                "message": "Source selectors resolve to different graph nodes",
            }
        return next(iter(candidate_ids)), None


def build_source_selector_query_datalog(selectors: dict[str, str]) -> str:
    lines = [
        ".decl query_source_selector(source:symbol, selector_kind:symbol)",
        ".output query_source_selector",
    ]
    source_tag = selectors.get("source_tag")
    if source_tag is not None:
        lines.append(
            f"query_source_selector(source, \"source_tag\") :- node_tag(source, {souffle_symbol(source_tag)})."
        )
    source_proteus_id = selectors.get("source_proteus_id")
    if source_proteus_id is not None:
        lines.append(
            f"query_source_selector(source, \"source_proteus_id\") :- node_proteus_id(source, {souffle_symbol(source_proteus_id)})."
        )
    lines.append("")
    return "\n".join(lines)


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


def build_compare_direct_process_connections_query_datalog(source_id: str) -> str:
    source = souffle_symbol(source_id)
    return "\n".join(
        [
            ".decl query_direct_process_connection(target:symbol, label:symbol)",
            ".decl query_reachable(target:symbol, label:symbol)",
            ".decl query_downstream_reference(target:symbol, label:symbol)",
            ".decl query_source_exists(source:symbol)",
            ".output query_direct_process_connection",
            ".output query_reachable",
            ".output query_downstream_reference",
            ".output query_source_exists",
            f"query_direct_process_connection(target, label) :- direct_process_connection({source}, target), node_label(target, label).",
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
    direct_process_connection_targets: list[tuple[str, str]] | None = None,
    comparison_summary: dict[str, str] | None = None,
    source_selection: dict[str, object] | None = None,
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
    if direct_process_connection_targets is not None:
        artifact["result_sets"]["direct_process_connection_targets"] = render_result_set(
            direct_process_connection_targets
        )
    if comparison_summary is not None:
        artifact["comparison_summary"] = comparison_summary
    if source_selection is not None:
        artifact["source_selection"] = source_selection
    (output_dir / "query_result.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
    )


def persist_source_selection_failure(
    *,
    output_dir: Path,
    query_entry: dict[str, object],
    source_selection: dict[str, object],
    diagnostic: dict[str, str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = {
        "status": "failed",
        "query": {
            "id": query_entry["id"],
            "status": query_entry["status"],
            "question": query_entry["question"],
        },
        "source_id": source_selection["resolved_source_id"],
        "source_selection": source_selection,
        "diagnostics": [diagnostic],
        "result_sets": {},
    }
    (output_dir / "query_result.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
    )


def persist_unsupported_query_result(
    *, output_dir: Path, query_entry: dict[str, object], source_id: str | None
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    query_scope = query_entry.get("query_scope", {"kind": "source_rooted"})
    artifact = {
        "status": unsupported_artifact_status(query_entry),
        "query": {
            "id": query_entry["id"],
            "status": query_entry["status"],
            "question": query_entry["question"],
        },
        "query_scope": query_scope,
        "diagnostics": unsupported_diagnostics(query_entry),
        "result_sets": {},
    }
    if query_scope != {"kind": "whole_pid"}:
        artifact["source_id"] = source_id
    outputs = query_entry.get("outputs")
    if isinstance(outputs, dict) and "candidate_result_sets" in outputs:
        artifact["candidate_result_sets"] = outputs["candidate_result_sets"]
    (output_dir / "query_result.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
    )


def unsupported_artifact_status(query_entry: dict[str, object]) -> str:
    if query_entry["status"] == "future_candidate":
        return "future_candidate"
    return "unsupported"


def unsupported_diagnostics(query_entry: dict[str, object]) -> list[dict[str, object]]:
    query_status = str(query_entry["status"])
    requires = query_entry.get("requires")
    if not isinstance(requires, dict):
        requires = {}

    if query_status == "future_candidate":
        diagnostic = {
            "code": "future_candidate",
            "message": "Query is recorded for future deterministic promotion",
        }
    else:
        diagnostic = {
            "code": str(query_entry.get("unsupported_reason", query_status)),
            "message": "Query cannot run until required predicates are derived",
        }

    for field_name in ("missing_predicates", "missing_facts_or_policy"):
        missing_values = requires.get(field_name)
        if missing_values:
            diagnostic[field_name] = missing_values
    return [diagnostic]


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


def compare_direct_process_connection_sets(
    *,
    direct_process_connection_targets: list[tuple[str, str]],
    downstream_reference_targets: list[tuple[str, str]],
    reachable_targets: list[tuple[str, str]],
) -> dict[str, str]:
    direct_ids = {target_id for target_id, _ in direct_process_connection_targets}
    downstream_reference_ids = {
        target_id for target_id, _ in downstream_reference_targets
    }
    reachable_ids = {target_id for target_id, _ in reachable_targets}
    return {
        "direct_vs_downstream_reference": compare_target_sets(
            direct_ids, downstream_reference_ids, "downstream_reference"
        ),
        "direct_vs_reachable": compare_target_sets(
            direct_ids, reachable_ids, "reachable"
        ),
        "experimental_note": "direct_process_connection is experimental and not yet trusted process-flow semantics",
    }


def compare_target_sets(
    direct_ids: set[str], other_ids: set[str], other_name: str
) -> str:
    if direct_ids == other_ids:
        return "same_targets"
    if direct_ids < other_ids:
        return f"narrower_than_{other_name}"
    if direct_ids > other_ids:
        return f"broader_than_{other_name}"
    return f"overlaps_{other_name}"


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


def render_compare_direct_process_connections_report(
    *,
    query_entry: dict[str, object],
    source_id: str,
    direct_process_connection_targets: list[tuple[str, str]],
    downstream_reference_targets: list[tuple[str, str]],
    reachable_targets: list[tuple[str, str]],
    comparison_summary: dict[str, str],
    diagnostics: list[dict[str, str]],
) -> str:
    diagnostic_lines = [diagnostic["message"] for diagnostic in diagnostics]
    return "\n".join(
        [
            "P&ID QA Query",
            f"Query ID: {query_entry['id']}",
            f"Question: {query_entry['question']}",
            f"Source ID: {source_id}",
            "Experimental predicate: direct_process_connection",
            *diagnostic_lines,
            "",
            render_three_way_targets(
                direct_process_connection_targets=direct_process_connection_targets,
                downstream_reference_targets=downstream_reference_targets,
                reachable_targets=reachable_targets,
            ),
            "",
            render_comparison_summary(comparison_summary),
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


def render_three_way_targets(
    *,
    direct_process_connection_targets: list[tuple[str, str]],
    downstream_reference_targets: list[tuple[str, str]],
    reachable_targets: list[tuple[str, str]],
) -> str:
    rows = [
        "Direct process connection targets                 | Downstream reference targets                    | Reachable targets"
    ]
    row_count = max(
        len(direct_process_connection_targets),
        len(downstream_reference_targets),
        len(reachable_targets),
        1,
    )
    for index in range(row_count):
        direct = target_text(direct_process_connection_targets, index)
        downstream_reference = target_text(downstream_reference_targets, index)
        reachable = target_text(reachable_targets, index)
        rows.append(f"{direct:<49} | {downstream_reference:<49} | {reachable}")
    return "\n".join(rows)


def render_comparison_summary(comparison_summary: dict[str, str]) -> str:
    direct_vs_downstream = comparison_summary.get(
        "direct_vs_downstream_reference", "unknown"
    ).replace("same_targets", "matches downstream_reference")
    direct_vs_reachable = comparison_summary.get(
        "direct_vs_reachable", "unknown"
    ).replace("narrower_than_reachable", "narrower than reachable")
    return f"Comparison: direct_process_connection {direct_vs_downstream}; {direct_vs_reachable}."


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
