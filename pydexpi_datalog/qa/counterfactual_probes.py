"""Intent-selected counterfactual replay for generated topology queries."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping

from pydexpi_datalog.qa.structured_intent import without_datalog_comments
from pydexpi_datalog.semantics.derive_graph_semantics import (
    build_graph_facts_datalog,
    load_graph_topology_idb,
)
from pydexpi_datalog.semantics.souffle_runner import (
    SouffleExecutionError,
    run_souffle_program,
)

PROBE_CATALOG_VERSION = "counterfactual-probes/1"
COUNTERFACTUAL_TIMEOUT_SECONDS = 5.0
COUNTERFACTUAL_OUTPUT_BYTES = 64 * 1024
COUNTERFACTUAL_ADDRESS_SPACE_BYTES = 512 * 1024 * 1024
MAX_COUNTERFACTUAL_PROBES = 32
_TOPOLOGY_PREDICATES = frozenset(
    {
        "direct_process_connection",
        "piping_connected",
        "piping_reachable",
        "reachable",
        "reachable_any",
        "reachable_any_undirected",
    }
)
_PIPING_ATTR_NAMES = frozenset(
    {
        "sourceItem",
        "targetItem",
        "sourceNode",
        "targetNode",
        "nodes",
        "segments",
        "connections",
        "items",
        "pipingNetworkSystems",
        "nozzles",
    }
)
_PREDICATE_BY_SCOPE_DIRECTION = {
    ("piping_only", "directed"): "piping_reachable",
    ("piping_only", "undirected"): "piping_connected",
    ("instrumentation_inclusive", "directed"): "reachable_any",
    ("instrumentation_inclusive", "undirected"): "reachable_any_undirected",
    ("all_topology", "directed"): "reachable_any",
    ("all_topology", "undirected"): "reachable_any_undirected",
}


def run_mandatory_counterfactual_probes(
    program: str,
    structured_intent: Mapping[str, object],
) -> dict[str, object]:
    """Replay an applicable generated program against synthetic graph mutations."""
    predicate_contract = _predicate_contract(program)
    try:
        probe_namespace = secrets.token_hex(32)
    except OSError as error:
        return {
            "status": "failed",
            "catalog_version": PROBE_CATALOG_VERSION,
            "predicate_contract": list(predicate_contract),
            "probes": [],
            "diagnostics": [
                {
                    "code": "faithfulness.counterfactual_unavailable",
                    "probe_id": "probe_setup",
                    "message": (
                        "Mandatory counterfactual replay could not create "
                        f"opaque probe identities: {error}"
                    ),
                }
            ],
        }
    probes, selection_diagnostics = _select_probes(
        structured_intent,
        predicate_contract,
        probe_namespace=probe_namespace,
    )
    if selection_diagnostics:
        return {
            "status": "failed",
            "catalog_version": PROBE_CATALOG_VERSION,
            "predicate_contract": list(predicate_contract),
            "probes": [],
            "diagnostics": selection_diagnostics,
        }
    if not probes:
        return {
            "status": "not_applicable",
            "catalog_version": PROBE_CATALOG_VERSION,
            "predicate_contract": list(predicate_contract),
            "probes": [],
            "diagnostics": [],
        }

    outcomes = [_run_probe(program, probe) for probe in probes]
    diagnostics: list[dict[str, object]] = []
    for outcome in outcomes:
        raw_diagnostics = outcome.get("diagnostics")
        if isinstance(raw_diagnostics, list):
            diagnostics.extend(
                diagnostic
                for diagnostic in raw_diagnostics
                if isinstance(diagnostic, dict)
            )
    return {
        "status": (
            "passed"
            if all(outcome["outcome"] == "passed" for outcome in outcomes)
            else "failed"
        ),
        "catalog_version": PROBE_CATALOG_VERSION,
        "predicate_contract": list(predicate_contract),
        "probes": outcomes,
        "diagnostics": diagnostics,
    }


def _without_string_literals(line: str) -> str:
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', line)


def _datalog_statements(program: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    escaped = False
    for character in program:
        current.append(character)
        if escaped:
            escaped = False
        elif character == "\\" and in_string:
            escaped = True
        elif character == '"':
            in_string = not in_string
        elif character == "." and not in_string:
            statements.append("".join(current))
            current = []
    if current and "".join(current).strip():
        statements.append("".join(current))
    return statements


def _predicate_contract(program: str) -> tuple[str, ...]:
    executable_program = without_datalog_comments(program)
    dependencies: dict[str, set[str]] = {}
    for statement in _datalog_statements(executable_program):
        executable_line = _without_string_literals(statement)
        if ":-" not in executable_line:
            continue
        head, body = executable_line.split(":-", 1)
        head_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", head)
        if head_match is None:
            continue
        dependencies.setdefault(head_match.group(1), set()).update(
            re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", body)
        )

    reachable = ["answer"]
    visited: set[str] = set()
    contract: set[str] = set()
    while reachable:
        predicate = reachable.pop()
        if predicate in visited:
            continue
        visited.add(predicate)
        for dependency in dependencies.get(predicate, set()):
            if dependency in _TOPOLOGY_PREDICATES:
                contract.add(dependency)
            elif dependency in dependencies:
                reachable.append(dependency)
    return tuple(sorted(contract))


def _select_probes(
    intent: Mapping[str, object],
    predicate_contract: tuple[str, ...],
    *,
    probe_namespace: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    output_obligations = intent.get("output_obligations")
    applicable = (
        intent.get("quantifier") == "all"
        and intent.get("negated") is True
        and isinstance(output_obligations, list)
        and "violating_source_ids" in output_obligations
    )
    if not applicable:
        return [], []
    expected_predicate = _PREDICATE_BY_SCOPE_DIRECTION.get(
        (str(intent.get("graph_scope")), str(intent.get("direction")))
    )
    if expected_predicate is None:
        return [], [_selection_unavailable("graph_scope/direction")]
    if expected_predicate not in predicate_contract:
        return [], [
            {
                "code": "faithfulness.predicate_contract_mismatch",
                "probe_id": "topology_connectivity",
                "expected_predicate": expected_predicate,
                "message": (
                    "The normalized intent requires topology predicate "
                    f"{expected_predicate!r}, but it is not reachable from answer."
                ),
            }
        ]

    source_classes = intent.get("source_classes")
    target_classes = intent.get("target_classes")
    if not isinstance(source_classes, list) or not source_classes:
        return [], [_selection_unavailable("source_classes")]
    if not isinstance(target_classes, list) or not target_classes:
        return [], [_selection_unavailable("target_classes")]
    if (
        len(source_classes) > 4
        or len(target_classes) > 3
        or len(source_classes) * (len(target_classes) + 4) > MAX_COUNTERFACTUAL_PROBES
    ):
        return [], [
            {
                "code": "faithfulness.probe_budget_exceeded",
                "message": (
                    f"Mandatory probe selection exceeds the "
                    f"{MAX_COUNTERFACTUAL_PROBES}-probe budget."
                ),
            }
        ]

    if any(not isinstance(item, str) for item in source_classes):
        return [], [_selection_unavailable("source_classes")]
    if any(not isinstance(item, str) for item in target_classes):
        return [], [_selection_unavailable("target_classes")]
    all_source_classes = tuple(str(item) for item in source_classes)
    all_target_classes = tuple(str(item) for item in target_classes)

    probes: list[dict[str, object]] = []
    for source_index, source_class in enumerate(all_source_classes):
        probes.append(
            _connectivity_probe(
                source_class=source_class,
                target_class=all_target_classes[0],
                source_index=source_index,
                target_index=0,
                path_shape="disconnected",
                required_predicate=expected_predicate,
                all_source_classes=all_source_classes,
                all_target_classes=all_target_classes,
                probe_namespace=probe_namespace,
                predicate_contract=predicate_contract,
            )
        )
        for target_index, target_class in enumerate(all_target_classes):
            probes.append(
                _connectivity_probe(
                    source_class=source_class,
                    target_class=target_class,
                    source_index=source_index,
                    target_index=target_index,
                    path_shape="direct",
                    required_predicate=expected_predicate,
                    all_source_classes=all_source_classes,
                    all_target_classes=all_target_classes,
                    probe_namespace=probe_namespace,
                    predicate_contract=predicate_contract,
                )
            )
        for path_shape in ("multihop", "reverse", "non_piping"):
            probes.append(
                _connectivity_probe(
                    source_class=source_class,
                    target_class=all_target_classes[0],
                    source_index=source_index,
                    target_index=0,
                    path_shape=path_shape,
                    required_predicate=expected_predicate,
                    all_source_classes=all_source_classes,
                    all_target_classes=all_target_classes,
                    probe_namespace=probe_namespace,
                    predicate_contract=predicate_contract,
                )
            )
    return probes, []


def _reaches_target_class(
    source_id: str,
    *,
    node_labels: Mapping[str, str],
    edges: list[tuple[str, str]],
    target_classes: tuple[str, ...],
) -> bool:
    frontier = [
        edge_target for edge_source, edge_target in edges if edge_source == source_id
    ]
    visited: set[str] = set()
    while frontier:
        node_id = frontier.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        if node_labels.get(node_id) in target_classes:
            return True
        frontier.extend(
            edge_target for edge_source, edge_target in edges if edge_source == node_id
        )
    return False


def _opaque_symbol(namespace: str, *parts: object) -> str:
    material = ":".join([namespace, *(str(part) for part in parts)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _connectivity_probe(
    *,
    source_class: str,
    target_class: str,
    source_index: int,
    target_index: int,
    path_shape: str,
    required_predicate: str,
    all_source_classes: tuple[str, ...],
    all_target_classes: tuple[str, ...],
    probe_namespace: str,
    predicate_contract: tuple[str, ...],
) -> dict[str, object]:
    source_id = _opaque_symbol(probe_namespace, "s", source_index)
    target_id = _opaque_symbol(
        probe_namespace,
        "t",
        source_index,
        target_index,
    )
    intermediate_id = _opaque_symbol(
        probe_namespace,
        "i",
        source_index,
        target_index,
    )
    node_labels = {
        source_id: source_class,
        target_id: target_class,
    }
    edge_pairs: list[tuple[str, str, str]] = []
    if path_shape == "direct":
        edge_pairs.append((source_id, target_id, "sourceItem"))
    elif path_shape == "multihop":
        node_labels[intermediate_id] = _opaque_symbol(
            probe_namespace,
            "intermediate-label",
        )
        edge_pairs.extend(
            [
                (source_id, intermediate_id, "sourceItem"),
                (intermediate_id, target_id, "targetItem"),
            ]
        )
    elif path_shape == "reverse":
        edge_pairs.append((target_id, source_id, "sourceItem"))
    elif path_shape == "non_piping":
        edge_pairs.append(
            (
                source_id,
                target_id,
                _opaque_symbol(probe_namespace, "non-piping-attribute"),
            )
        )

    graph_facts: dict[str, object] = {
        "facts": {
            "nodes": [
                {
                    "node_id": node_id,
                    "attributes": {"label": label},
                }
                for node_id, label in node_labels.items()
            ],
            "edges": [
                {
                    "source_id": edge_source,
                    "target_id": edge_target,
                    "edge_key": edge_index,
                    "attributes": {
                        "label": "reference",
                        "attr_name": attr_name,
                    },
                }
                for edge_index, (edge_source, edge_target, attr_name) in enumerate(
                    edge_pairs,
                    start=1,
                )
            ],
        }
    }
    applicable_edges = [
        (edge_source, edge_target)
        for edge_source, edge_target, attr_name in edge_pairs
        if not required_predicate.startswith("piping_")
        or attr_name in _PIPING_ATTR_NAMES
    ]
    if required_predicate in {
        "piping_connected",
        "reachable_any_undirected",
    }:
        applicable_edges.extend(
            (edge_target, edge_source)
            for edge_source, edge_target in list(applicable_edges)
        )
    expected = sorted(
        node_id
        for node_id, label in node_labels.items()
        if label in all_source_classes
        and not _reaches_target_class(
            node_id,
            node_labels=node_labels,
            edges=applicable_edges,
            target_classes=all_target_classes,
        )
    )
    identity = {
        "catalog_version": PROBE_CATALOG_VERSION,
        "source_class": source_class,
        "target_class": target_class,
        "path_shape": path_shape,
        "predicate_contract": list(predicate_contract),
        "required_predicate": required_predicate,
        "graph_facts": graph_facts,
        "expected_witness_ids": expected,
    }
    input_version = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "probe_id": (
            f"{required_predicate}:{source_class}:{target_class}:{path_shape}"
        ),
        "input_version": input_version,
        "graph_facts": graph_facts,
        "expected_witness_ids": expected,
    }


def _run_probe(program: str, probe: Mapping[str, object]) -> dict[str, object]:
    probe_id = str(probe["probe_id"])
    input_version = str(probe["input_version"])
    raw_expected = probe.get("expected_witness_ids")
    expected = (
        sorted(str(item) for item in raw_expected)
        if isinstance(raw_expected, list)
        else []
    )
    raw_graph_facts = probe.get("graph_facts")
    graph_facts = (
        {str(key): value for key, value in raw_graph_facts.items()}
        if isinstance(raw_graph_facts, Mapping)
        else {}
    )
    try:
        complete_program = (
            build_graph_facts_datalog(graph_facts)
            + "\n"
            + load_graph_topology_idb()
            + "\n"
            + _without_input_includes(program)
        )
        relations = run_souffle_program(
            complete_program,
            timeout_seconds=COUNTERFACTUAL_TIMEOUT_SECONDS,
            max_output_bytes=COUNTERFACTUAL_OUTPUT_BYTES,
            max_address_space_bytes=COUNTERFACTUAL_ADDRESS_SPACE_BYTES,
        )
        rows = relations.get("answer")
        if rows is None or any(len(row) != 1 for row in rows):
            raise ValueError("Generated program must emit unary answer witnesses.")
        actual = sorted({row[0] for row in rows})
    except (
        OSError,
        SouffleExecutionError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        detail = (
            error.detail if isinstance(error, SouffleExecutionError) else str(error)
        )
        return {
            "probe_id": probe_id,
            "input_version": input_version,
            "outcome": "not_evaluated",
            "expected_witness_ids": expected,
            "actual_witness_ids": [],
            "diagnostics": [
                {
                    "code": "faithfulness.counterfactual_unavailable",
                    "probe_id": probe_id,
                    "message": detail or "Counterfactual probe could not be evaluated.",
                }
            ],
        }

    passed = actual == expected
    return {
        "probe_id": probe_id,
        "input_version": input_version,
        "outcome": "passed" if passed else "failed",
        "expected_witness_ids": expected,
        "actual_witness_ids": actual,
        "diagnostics": (
            []
            if passed
            else [
                {
                    "code": "faithfulness.counterfactual_mismatch",
                    "probe_id": probe_id,
                    "expected": expected,
                    "actual": actual,
                    "message": (
                        f"Counterfactual probe {probe_id!r} expected {expected!r} "
                        f"but observed {actual!r}."
                    ),
                }
            ]
        ),
    }


def _without_input_includes(program: str) -> str:
    return re.sub(
        r'^\s*\.include\s+"/input/(?:graph_facts|graph_topology_semantics)\.dl"\s*$',
        "",
        program,
        flags=re.MULTILINE,
    )


def _selection_unavailable(field: str) -> dict[str, object]:
    return {
        "code": "faithfulness.probe_selection_unavailable",
        "field": field,
        "message": f"Mandatory probes cannot be selected from {field}.",
    }
