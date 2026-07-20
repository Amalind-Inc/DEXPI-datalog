"""Behavior tests for the Arm T prebuilt Datalog template pack (lx6p).

The model's only authored surface is a routing JSON; these tests pin the
three mechanical guarantees the design lock (v3) promises:

1. routing validation is closed-world over the drawing's vocabulary,
2. rendered programs are frozen template bodies + validated bindings only,
3. rendered programs execute end-to-end on the real engine.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark.template_arm import (
    TEMPLATE_PACK,
    render_program,
    routing_vocabulary,
    validate_routing,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SEMANTICS = (
    REPO_ROOT
    / "pydexpi_datalog"
    / "semantics"
    / "datalog"
    / "idb"
    / "graph_topology_semantics.dl"
)

INSPECTION = {
    "nodes": [
        {"id": "pif1", "label": "ProcessInstrumentationFunction", "tag_name": None},
        {"id": "v1", "label": "BallValve", "tag_name": "V-100"},
        {"id": "v2", "label": "BallValve", "tag_name": "V-200"},
        {"id": "p1", "label": "CentrifugalPump", "tag_name": "P-4713"},
    ],
    "edges": [],
}


def vocabulary():
    return routing_vocabulary(json.dumps(INSPECTION))


def test_template_pack_ships_the_six_locked_templates() -> None:
    assert set(TEMPLATE_PACK) == {
        "entity_lookup",
        "attachment",
        "reachability",
        "guarded_reachability",
        "class_count",
        "policy_abstention",
    }
    for template in TEMPLATE_PACK.values():
        assert template.description  # SME-facing, plain language


def test_validate_rejects_unknown_category() -> None:
    errors = validate_routing({"category": "clairvoyance", "parameters": {}}, vocabulary())
    assert any("clairvoyance" in error for error in errors)
    assert any("entity_lookup" in error for error in errors)  # names valid ids


def test_validate_rejects_label_outside_drawing_vocabulary() -> None:
    routing = {
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": ["BallValve", "ImaginaryValve"],
        },
    }
    errors = validate_routing(routing, vocabulary())
    assert any("ImaginaryValve" in error for error in errors)
    assert any("target_labels" in error for error in errors)
    assert any("BallValve" in error for error in errors)  # vocabulary offered


def test_validate_accepts_wellformed_guarded_reachability() -> None:
    routing = {
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": ["BallValve"],
        },
    }
    assert validate_routing(routing, vocabulary()) == []


def test_validate_policy_abstention_takes_no_parameters() -> None:
    assert validate_routing(
        {"category": "policy_abstention", "parameters": {}}, vocabulary()
    ) == []
    errors = validate_routing(
        {"category": "policy_abstention", "parameters": {"labels": ["BallValve"]}},
        vocabulary(),
    )
    assert errors


def test_render_refuses_policy_abstention() -> None:
    with pytest.raises(ValueError, match="abstention"):
        render_program({"category": "policy_abstention", "parameters": {}})


def test_rendered_program_passes_the_authored_rule_guard() -> None:
    """Every rendered program must clear run_query.py's starter guard."""
    import re

    routing = {
        "category": "entity_lookup",
        "parameters": {"tags": ["P-4713"]},
    }
    program = render_program(routing)
    assert '.include "/input/graph_facts.dl"' in program
    assert '.include "/input/graph_topology_semantics.dl"' in program
    assert re.search(r"result_witness\s*\([^)]*\)\s*:-", program)
    assert 'node_tag(' in program and '"P-4713"' in program


@pytest.mark.skipif(shutil.which("souffle") is None, reason="souffle engine not on PATH")
def test_guarded_reachability_template_executes_end_to_end(tmp_path: Path) -> None:
    """PIF reaches v1 but not v2 -> the unguarded valve is the sole witness."""
    (tmp_path / "graph_facts.dl").write_text(
        ".decl node(id:symbol)\n"
        ".decl node_attribute(id:symbol, attr_name:symbol, attr_value:symbol)\n"
        ".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)\n"
        ".decl graph_edge_attribute(source:symbol, target:symbol, edge_key:symbol,"
        " attr_name:symbol, attr_value:symbol)\n"
        'node("pif1").\n'
        'node("v1").\n'
        'node("v2").\n'
        'node_attribute("pif1", "label", "ProcessInstrumentationFunction").\n'
        'node_attribute("v1", "label", "BallValve").\n'
        'node_attribute("v2", "label", "BallValve").\n'
        'graph_edge("pif1", "v1", "e1").\n'
        'graph_edge_attribute("pif1", "v1", "e1", "attr_name", "connections").\n',
        encoding="utf-8",
    )
    shutil.copy(SEMANTICS, tmp_path / "graph_topology_semantics.dl")
    routing = {
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": ["BallValve"],
        },
    }
    program = render_program(routing, include_dir=str(tmp_path))
    program_path = tmp_path / "analysis.dl"
    program_path.write_text(program, encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    completed = subprocess.run(
        ["souffle", "-D", str(out_dir), str(program_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    witnesses = (out_dir / "result_witness.csv").read_text(encoding="utf-8").split()
    assert witnesses == ["v2"]
