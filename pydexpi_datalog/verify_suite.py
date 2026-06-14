from __future__ import annotations

import json
from pathlib import Path

from .result_schemas import validate_result_schema


ALLOWED_INTERMEDIATE_CLASSES = {"Pipe", "PipeReducer"}
CHECK_VALVE_CLASSES = {"CheckValve", "SwingCheckValve"}
OFF_PAGE_CLASSES = {"FlowOutPipeOffPageConnector", "FlowInPipeOffPageConnector"}


def run_verify_suite(*, suite_manifest_path: Path, output_dir: Path) -> int:
    suite_manifest = json.loads(suite_manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)

    rule_ids = suite_manifest.get("rules", ["pump_discharge_check_valve"])
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

    print(render_console_report(suite_manifest))
    return 0


def evaluate_graph_fixture(graph_facts: dict[str, object], *, rule_id: str) -> dict[str, object]:
    nodes = {node["node_id"]: node for node in graph_facts["facts"]["nodes"]}
    edges = graph_facts["facts"]["edges"]

    pump = next(
        node for node in graph_facts["facts"]["nodes"] if node["attributes"].get("label") == "CentrifugalPump"
    )
    pump_id = pump["node_id"]
    nozzle_ids = [
        edge["target_id"]
        for edge in edges
        if edge["source_id"] == pump_id and edge["attributes"].get("attr_name") == "nozzles"
    ]
    discharge_candidates = [
        nozzle_id
        for nozzle_id in nozzle_ids
        if any(
            edge["target_id"] == nozzle_id
            and edge["attributes"].get("attr_name") == "sourceItem"
            for edge in edges
        )
    ]
    if len(discharge_candidates) != 1:
        return build_evaluation_diagnostic(pump_id=pump_id, rule_id=rule_id)

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
            edge
            for edge in edges
            if edge["target_id"] == current_id
            and edge["attributes"].get("attr_name") == "sourceItem"
        ]
        next_ids = []
        for edge in outgoing_edges:
            container_id = edge["source_id"]
            next_ids.extend(
                candidate["target_id"]
                for candidate in edges
                if candidate["source_id"] == container_id
                and candidate["attributes"].get("attr_name") == "targetItem"
            )
        next_ids = sorted(set(next_ids))
        if len(next_ids) != 1:
            return build_evaluation_diagnostic(pump_id=pump_id)

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
                "traversed_objects": traversed_objects,
                "traversed_edges": traversed_edges,
                "matched_objects": [],
                "boundary": {
                    "kind": "terminal_object",
                    "object_id": next_id,
                },
            },
        }


def build_evaluation_diagnostic(*, pump_id: str, rule_id: str) -> dict[str, object]:
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
