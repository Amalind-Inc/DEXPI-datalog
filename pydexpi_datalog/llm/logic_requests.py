from __future__ import annotations

import json
import re
from pathlib import Path

from .model_access import (
    ModelProvider,
    missing_byok_credentials_diagnostic,
    resolve_model_access_config,
)
from .source_selection import build_source_selection, resolve_source_selection


def run_draft_logic_request(
    *,
    logic_request: str,
    output_dir: Path,
    derived_graph_semantics_path: Path | None = None,
    source_id: str | None = None,
    source_tag: str | None = None,
    source_proteus_id: str | None = None,
    allow_raw_attributes: bool = False,
    provider: ModelProvider | None = None,
    environ: dict[str, str] | None = None,
) -> int:
    artifact = draft_logic_request(
        logic_request=logic_request,
        derived_graph_semantics_path=derived_graph_semantics_path,
        source_id=source_id,
        source_tag=source_tag,
        source_proteus_id=source_proteus_id,
        allow_raw_attributes=allow_raw_attributes,
        provider=provider,
        environ=environ,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "logic_request.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
    )
    generated_datalog = artifact.get("draft", {}).get("generated_datalog")
    if isinstance(generated_datalog, str):
        (output_dir / "generated_query.dl").write_text(
            generated_datalog.rstrip() + "\n", encoding="utf-8"
        )
    print(render_logic_request_report(artifact))
    return 0 if artifact["status"] != "failed" else 1


def draft_logic_request(
    *,
    logic_request: str,
    derived_graph_semantics_path: Path | None = None,
    source_id: str | None = None,
    source_tag: str | None = None,
    source_proteus_id: str | None = None,
    allow_raw_attributes: bool = False,
    provider: ModelProvider | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    route = route_logic_request(
        logic_request, allow_raw_attributes=allow_raw_attributes
    )
    source_node_context = build_source_node_context(
        derived_graph_semantics_path=derived_graph_semantics_path,
        source_id=source_id,
        source_tag=source_tag,
        source_proteus_id=source_proteus_id,
    )
    artifact: dict[str, object] = {
        "artifact_type": "logic_request_draft",
        "logic_request": logic_request,
        "route": route,
        "raw_attribute_mode": {"enabled": allow_raw_attributes},
        "source_node_context": source_node_context,
        "diagnostics": [],
    }

    if route["kind"] != "topology_logic":
        artifact.update(route_without_model_access(route))
        return artifact

    model_access = resolve_model_access_config(environ=environ)
    artifact["model_access"] = model_access.metadata()

    if source_node_context["diagnostics"] and source_node_context["scope"] != {
        "kind": "whole_pid"
    }:
        artifact["status"] = "failed"
        artifact["diagnostics"] = source_node_context["diagnostics"]
        return artifact

    if not model_access.has_credentials:
        artifact["status"] = "failed"
        artifact["diagnostics"] = [missing_byok_credentials_diagnostic(model_access)]
        return artifact

    if provider is None:
        artifact["status"] = "failed"
        artifact["diagnostics"] = [
            {
                "code": "model_access.provider_not_configured",
                "message": "No model provider adapter was configured for this logic request.",
            }
        ]
        return artifact

    response = provider.complete(
        request=logic_request,
        context={
            "route": artifact["route"],
            "model_access": model_access.metadata(),
            "raw_attribute_mode": artifact["raw_attribute_mode"],
            "source_node_context": source_node_context,
        },
    )
    artifact["status"] = "drafted"
    artifact["draft"] = {
        "provider": provider.provider,
        "model": provider.model,
        **parse_model_draft_response(response),
    }
    return artifact


def parse_model_draft_response(response: str) -> dict[str, str]:
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        return {"text": response}

    if not isinstance(parsed, dict):
        return {"text": response}

    draft: dict[str, str] = {}
    generated_datalog = parsed.get("generated_datalog")
    formal_restatement = parsed.get("formal_restatement")
    if isinstance(generated_datalog, str):
        draft["generated_datalog"] = generated_datalog
    if isinstance(formal_restatement, str):
        draft["formal_restatement"] = formal_restatement
    return draft or {"text": response}


def route_logic_request(
    logic_request: str, *, allow_raw_attributes: bool = False
) -> dict[str, str]:
    normalized = logic_request.lower()
    if uses_raw_attributes(normalized) and not allow_raw_attributes:
        return {"kind": "raw_attribute_rejected"}
    if any(term in normalized for term in ("downstream", "reachable", "connected", "source")):
        return {"kind": "topology_logic"}
    if any(term in normalized for term in ("model", "artifact", "run", "context policy")):
        return {"kind": "metadata_lookup"}
    if any(term in normalized for term in ("what is", "explain", "document", "predicate")):
        return {"kind": "documentation_answer"}
    if any(
        term in normalized
        for term in (
            "hydraulic",
            "pressure drop",
            "pump head",
            "thermodynamic",
            "simulation",
            "biowin",
            "epa",
            "hazop",
        )
    ):
        return {"kind": "missing_capability"}
    return {"kind": "clarification"}


def uses_raw_attributes(normalized_logic_request: str) -> bool:
    return any(
        term in normalized_logic_request
        for term in (
            "node_attribute",
            "graph_edge_attribute",
            "raw attribute",
            "raw attributes",
        )
    )


def route_without_model_access(route: dict[str, str]) -> dict[str, object]:
    kind = route["kind"]
    if kind == "documentation_answer":
        return {
            "status": "routed",
            "route_result": {
                "kind": kind,
                "message": "This request can be answered from project or predicate documentation without model access.",
            },
        }
    if kind == "metadata_lookup":
        return {
            "status": "routed",
            "route_result": {
                "kind": kind,
                "message": "This request can be answered from persisted logic-request artifacts without model access.",
            },
        }
    if kind == "missing_capability":
        return {
            "status": "unsupported",
            "diagnostics": [
                {
                    "code": "logic_request.missing_capability",
                    "message": "This request needs facts, predicates, policy, or external tools that are not available in the OSS topology QA workflow.",
                }
            ],
        }
    if kind == "raw_attribute_rejected":
        return {
            "status": "unsupported",
            "diagnostics": [
                {
                    "code": "logic_request.raw_attributes_disabled",
                    "message": (
                        "Generic raw attributes are disabled by default. Re-run with "
                        "advanced raw-attribute mode only when messy source attribute "
                        "names are intentional."
                    ),
                }
            ],
        }
    return {
        "status": "needs_clarification",
        "diagnostics": [
            {
                "code": "logic_request.needs_clarification",
                "message": "The request is too vague to route safely. Clarify the object, relationship, and expected condition.",
            }
        ],
    }


def render_logic_request_report(artifact: dict[str, object]) -> str:
    return "\n".join(
        [
            "Logic Request Draft",
            f"Status: {artifact['status']}",
            f"Route: {artifact['route']['kind']}",
        ]
    )


def build_source_node_context(
    *,
    derived_graph_semantics_path: Path | None,
    source_id: str | None,
    source_tag: str | None,
    source_proteus_id: str | None,
) -> dict[str, object]:
    source_selection = build_source_selection(
        source_id=source_id,
        source_tag=source_tag,
        source_proteus_id=source_proteus_id,
    )
    if source_selection["selectors"] == {}:
        return {
            "scope": {"kind": "whole_pid"},
            "diagnostics": [
                {
                    "code": "source_selection.not_provided",
                    "message": "No source node selector was provided; the logic request has whole-P&ID scope.",
                }
            ],
        }

    if derived_graph_semantics_path is None:
        return {
            "scope": {"kind": "affected_connected_subgraph"},
            "source_selection": source_selection,
            "diagnostics": [
                {
                    "code": "source_selection.missing_derived_graph_semantics",
                    "message": "Source node selection requires a derived_graph_semantics.dl artifact.",
                }
            ],
        }

    resolved_source_id, diagnostic = resolve_source_selection(
        derived_graph_semantics_path=derived_graph_semantics_path,
        source_selection=source_selection,
    )
    if diagnostic is not None:
        return {
            "scope": {"kind": "affected_connected_subgraph"},
            "source_selection": source_selection,
            "diagnostics": [diagnostic],
        }

    source_selection["resolved_source_id"] = resolved_source_id
    graph = parse_graph_fact_summaries(derived_graph_semantics_path)
    if resolved_source_id not in graph["nodes"]:
        return {
            "scope": {"kind": "affected_connected_subgraph"},
            "source_selection": source_selection,
            "diagnostics": [
                {
                    "code": "source_selector_no_match",
                    "message": "Source selector did not resolve to a graph node",
                }
            ],
        }
    return {
        "scope": {"kind": "affected_connected_subgraph"},
        "source_selection": source_selection,
        "selected_node": summarize_node(graph, resolved_source_id),
        "affected_connected_subgraph": summarize_connected_subgraph(
            graph=graph, source_id=resolved_source_id
        ),
        "diagnostics": [],
    }


def parse_graph_fact_summaries(path: Path) -> dict[str, object]:
    nodes: dict[str, dict[str, str]] = {}
    reference_edges: list[dict[str, str]] = []
    composition_edges: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        predicate, values = parse_quoted_fact(line)
        if predicate == "node" and len(values) == 1:
            nodes.setdefault(values[0], {})
        elif predicate == "node_attribute" and len(values) == 3:
            node_id, name, value = values
            if name in {"label", "tagName", "proteusId"}:
                nodes.setdefault(node_id, {})[name] = value
        elif predicate == "reference_edge" and len(values) == 3:
            reference_edges.append(edge_summary(values))
        elif predicate == "composition_edge" and len(values) == 3:
            composition_edges.append(edge_summary(values))
        elif predicate == "graph_edge_attribute" and len(values) == 5:
            edge_label = values[4]
            if values[3] == "label" and edge_label == "reference":
                reference_edges.append(edge_summary([values[0], values[1], edge_label]))
            elif values[3] == "label" and edge_label == "composition":
                composition_edges.append(edge_summary([values[0], values[1], edge_label]))
    return {
        "nodes": nodes,
        "reference_edges": reference_edges,
        "composition_edges": composition_edges,
    }


def parse_quoted_fact(line: str) -> tuple[str | None, list[str]]:
    match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)\.$", line.strip())
    if match is None:
        return None, []
    return match.group(1), re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(2))


def edge_summary(values: list[str]) -> dict[str, str]:
    return {"source_id": values[0], "target_id": values[1], "kind": values[2]}


def summarize_node(graph: dict[str, object], node_id: str | None) -> dict[str, str | None]:
    node = graph["nodes"].get(node_id, {})
    return {
        "id": node_id,
        "label": node.get("label"),
        "proteus_id": node.get("proteusId"),
        "tag": node.get("tagName"),
    }


def summarize_connected_subgraph(
    *, graph: dict[str, object], source_id: str | None
) -> dict[str, list[dict[str, object]]]:
    reference_edges = [
        summarize_edge_with_target(graph, edge)
        for edge in graph["reference_edges"]
        if edge["source_id"] == source_id or edge["target_id"] == source_id
    ]
    composition_edges = [
        summarize_edge_with_target(graph, edge)
        for edge in graph["composition_edges"]
        if edge["source_id"] == source_id or edge["target_id"] == source_id
    ]
    return {
        "reference_edges": reference_edges,
        "composition_edges": composition_edges,
    }


def summarize_edge_with_target(
    graph: dict[str, object], edge: dict[str, str]
) -> dict[str, object]:
    return {
        **edge,
        "source": summarize_node(graph, edge["source_id"]),
        "target": summarize_node(graph, edge["target_id"]),
    }
