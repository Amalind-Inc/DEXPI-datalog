from __future__ import annotations

import json
from pathlib import Path

from ..artifacts.result_schemas import validate_result_schema
from ..semantics.derive_graph_semantics import derive_edge_families

ALLOWED_INTERMEDIATE_CLASSES = {"Pipe", "PipeReducer"}
CHECK_VALVE_CLASSES = {"CheckValve", "SwingCheckValve"}
OFF_PAGE_CLASSES = {"FlowOutPipeOffPageConnector", "FlowInPipeOffPageConnector"}


def run_verify_suite(*, suite_manifest_path: Path, output_dir: Path) -> int:
    suite_manifest = json.loads(suite_manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)

    rule_ids = suite_manifest.get("rules", ["pump_discharge_check_valve"])
    behavior_examples: list[dict[str, object]] = []
    for fixture in suite_manifest["fixtures"]:
        graph_facts = json.loads(
            Path(fixture["graph_facts_path"]).read_text(encoding="utf-8")
        )
        artifact_path = output_dir / f"{fixture['fixture_id']}.json"
        if len(rule_ids) == 1:
            result = evaluate_graph_fixture(graph_facts, rule_id=rule_ids[0])
            diagnostics = validate_result_schema(result)
            if diagnostics:
                raise ValueError(
                    f"invalid result schema for {fixture['fixture_id']}: {diagnostics}"
                )
            artifact_path.write_text(
                json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
            )
            behavior_example = build_behavior_example(
                fixture=fixture,
                actual_result=result,
            )
            if behavior_example is not None:
                behavior_examples.append(behavior_example)
            continue

        results = [evaluate_graph_fixture(graph_facts, rule_id=rule_id) for rule_id in rule_ids]
        for result in results:
            diagnostics = validate_result_schema(result)
            if diagnostics:
                raise ValueError(
                    f"invalid result schema for {fixture['fixture_id']}: {diagnostics}"
                )
        artifact = {
            "fixture_id": fixture["fixture_id"],
            "post_edit_reevaluation": "deferred",
            "results": sorted(results, key=lambda item: item["rule_id"]),
        }
        artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")

    if len(rule_ids) == 1:
        summary = build_behavior_harness_summary(
            rule_id=rule_ids[0], examples=behavior_examples
        )
        (output_dir / "behavior_harness_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )

    print(render_console_report(suite_manifest))
    return 0


def build_behavior_example(
    *, fixture: dict[str, object], actual_result: dict[str, object]
) -> dict[str, object] | None:
    expected_result_path = fixture.get("expected_result_path")
    if not expected_result_path:
        return None

    expected_result = json.loads(Path(expected_result_path).read_text(encoding="utf-8"))
    expected_behavior = behavior_for_result_type(expected_result["result_type"])
    if expected_behavior == "diagnostic":
        return {
            "actual_result_type": actual_result["result_type"],
            "expected_behavior": expected_behavior,
            "expected_result_type": expected_result["result_type"],
            "fixture_id": fixture["fixture_id"],
            "status": "diagnostic",
        }

    actual_behavior = behavior_for_result_type(actual_result["result_type"])
    status = "matched" if actual_behavior == expected_behavior else "mismatched"
    return {
        "actual_result_type": actual_result["result_type"],
        "expected_behavior": expected_behavior,
        "expected_result_type": expected_result["result_type"],
        "fixture_id": fixture["fixture_id"],
        "status": status,
    }


def behavior_for_result_type(result_type: str) -> str:
    if result_type == "pass":
        return "satisfying"
    if result_type == "evaluation_diagnostic":
        return "diagnostic"
    return "rejecting"


def build_behavior_harness_summary(
    *, rule_id: str, examples: list[dict[str, object]]
) -> dict[str, object]:
    behavioral_examples = [
        example for example in examples if example["expected_behavior"] != "diagnostic"
    ]
    return {
        "schema_version": 1,
        "execution": "deterministic_fact_layer",
        "candidate_rules": [rule_id],
        "examples": sorted(examples, key=lambda item: item["fixture_id"]),
        "totals": {
            "examples": len(behavioral_examples),
            "satisfying_examples": sum(
                1
                for example in behavioral_examples
                if example["expected_behavior"] == "satisfying"
            ),
            "rejecting_examples": sum(
                1
                for example in behavioral_examples
                if example["expected_behavior"] == "rejecting"
            ),
            "diagnostic_examples": len(examples) - len(behavioral_examples),
            "mismatches": sum(
                1 for example in behavioral_examples if example["status"] == "mismatched"
            ),
        },
    }


def evaluate_graph_fixture(graph_facts: dict[str, object], *, rule_id: str) -> dict[str, object]:
    nodes = {node["node_id"]: node for node in graph_facts["facts"]["nodes"]}
    edge_families = derive_edge_families(graph_facts)
    composition_edges = edge_families["composition_edge"]
    reference_edges = edge_families["reference_edge"]
    semantic_evidence = {
        "traversal_predicate": "downstream_reference",
        "reachability_predicate": "reachable",
    }

    pump = next(
        node for node in graph_facts["facts"]["nodes"] if node["attributes"].get("label") == "CentrifugalPump"
    )
    pump_id = pump["node_id"]
    nozzle_ids = [
        target_id
        for source_id, target_id, attr_name in composition_edges
        if source_id == pump_id and attr_name == "nozzles"
    ]
    discharge_candidates = [
        nozzle_id
        for nozzle_id in nozzle_ids
        if any(
            target_id == nozzle_id and attr_name == "sourceItem"
            for _, target_id, attr_name in reference_edges
        )
    ]
    if len(discharge_candidates) != 1:
        return build_evaluation_diagnostic(
            pump_id=pump_id, rule_id=rule_id, semantic_evidence=semantic_evidence
        )

    discharge_nozzle_id = discharge_candidates[0]
    traversed_objects = [
        {
            "object_id": discharge_nozzle_id,
            "class": nodes[discharge_nozzle_id]["attributes"]["label"],
        }
    ]
    traversed_edges: list[dict[str, object]] = []
    current_id = discharge_nozzle_id

    while True:
        outgoing_edges = [
            source_id
            for source_id, target_id, attr_name in reference_edges
            if target_id == current_id and attr_name == "sourceItem"
        ]
        next_ids = []
        for container_id in outgoing_edges:
            next_ids.extend(
                target_id
                for source_id, target_id, attr_name in reference_edges
                if source_id == container_id and attr_name == "targetItem"
            )
        next_ids = sorted(set(next_ids))
        if len(next_ids) != 1:
            return build_evaluation_diagnostic(
                pump_id=pump_id, rule_id=rule_id, semantic_evidence=semantic_evidence
            )

        next_id = next_ids[0]
        next_label = nodes[next_id]["attributes"]["label"]
        traversed_edges.append(
            {
                "source_id": current_id,
                "target_id": next_id,
                "edge_key": 0,
            }
        )
        traversed_objects.append({"object_id": next_id, "class": next_label})

        if next_label in CHECK_VALVE_CLASSES:
            if rule_id == "pump_discharge_not_terminal_nozzle":
                return {
                    "schema_version": 1,
                    "result_type": "pass",
                    "rule_id": rule_id,
                    "message": "The first downstream item was not a terminal nozzle.",
                    "subject": {
                        "pump_id": pump_id,
                        "discharge_nozzle_id": discharge_nozzle_id,
                    },
                    "evidence": {
                        "derived_graph_semantics": semantic_evidence,
                        "traversed_objects": traversed_objects,
                        "traversed_edges": traversed_edges,
                        "matched_objects": [
                            {"object_id": next_id, "class": next_label}
                        ],
                        "boundary": {
                            "kind": "matched_required_component",
                            "object_id": next_id,
                        },
                    },
                }
            return {
                "schema_version": 1,
                "result_type": "pass",
                "rule_id": rule_id,
                "message": "Required downstream check valve was found before the first branch or terminal boundary.",
                "subject": {
                    "pump_id": pump_id,
                    "discharge_nozzle_id": discharge_nozzle_id,
                },
                "evidence": {
                    "derived_graph_semantics": semantic_evidence,
                    "traversed_objects": traversed_objects,
                    "traversed_edges": traversed_edges,
                    "matched_objects": [
                        {"object_id": next_id, "class": next_label}
                    ],
                    "boundary": {
                        "kind": "matched_required_component",
                        "object_id": next_id,
                    },
                },
            }
        if next_label in ALLOWED_INTERMEDIATE_CLASSES:
            current_id = next_id
            continue
        if next_label in OFF_PAGE_CLASSES:
            return {
                "schema_version": 1,
                "result_type": "bounded_failure_off_page",
                "rule_id": rule_id,
                "message": "No downstream check valve was found before the discharge path terminated at an off-page connector.",
                "subject": {
                    "pump_id": pump_id,
                    "discharge_nozzle_id": discharge_nozzle_id,
                },
                "evidence": {
                    "derived_graph_semantics": semantic_evidence,
                    "traversed_objects": traversed_objects,
                    "traversed_edges": traversed_edges,
                    "matched_objects": [],
                    "boundary": {
                        "kind": "off_page_connector",
                        "object_id": next_id,
                    },
                    "uncertainty_text": "The discharge path may continue beyond the page edge.",
                },
            }
        return {
            "schema_version": 1,
            "result_type": "hard_violation",
            "rule_id": rule_id,
            "message": "No downstream check valve was found before the first terminal boundary."
            if rule_id == "pump_discharge_check_valve"
            else "The first downstream item on the discharge path was a terminal nozzle.",
            "subject": {
                "pump_id": pump_id,
                "discharge_nozzle_id": discharge_nozzle_id,
            },
            "evidence": {
                "derived_graph_semantics": semantic_evidence,
                "traversed_objects": traversed_objects,
                "traversed_edges": traversed_edges,
                "matched_objects": [],
                "boundary": {
                    "kind": "terminal_object",
                    "object_id": next_id,
                },
            },
        }


def build_evaluation_diagnostic(
    *, pump_id: str, rule_id: str, semantic_evidence: dict[str, str] | None = None
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "result_type": "evaluation_diagnostic",
        "rule_id": rule_id,
        "message": "The verifier could not determine a unique discharge nozzle from the available graph evidence.",
        "subject": {
            "pump_id": pump_id,
            "discharge_nozzle_id": "unknown",
        },
        "evidence": {
            "derived_graph_semantics": semantic_evidence
            or {
                "traversal_predicate": "downstream_reference",
                "reachability_predicate": "reachable",
            },
            "traversed_objects": [
                {"object_id": pump_id, "class": "CentrifugalPump"}
            ],
            "traversed_edges": [],
            "matched_objects": [],
            "boundary": {
                "kind": "unresolved_discharge_nozzle",
                "object_id": pump_id,
            },
        },
    }


def render_console_report(suite_manifest: dict[str, object]) -> str:
    return "\n".join(
        [
            "Verified Fixture Suite",
            f"Fixtures: {len(suite_manifest['fixtures'])}",
        ]
    )
