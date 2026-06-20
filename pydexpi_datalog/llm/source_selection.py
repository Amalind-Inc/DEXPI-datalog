from __future__ import annotations

from pathlib import Path
import csv
import shutil
import subprocess
import tempfile


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
            derived_graph_semantics_path.read_text(encoding="utf-8")
            + "\n"
            + generated_query_datalog,
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


def souffle_symbol(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def read_symbol_pairs(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.reader(file, delimiter="\t")
        return sorted((row[0], row[1]) for row in reader if len(row) >= 2)
