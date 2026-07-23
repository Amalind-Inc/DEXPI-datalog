from __future__ import annotations

import json
import pytest

from pydexpi_datalog.qa import counterfactual_probes
from pydexpi_datalog.qa.counterfactual_probes import (
    run_mandatory_counterfactual_probes,
)
from pydexpi_datalog.qa.datalog_audit import (
    append_datalog_audit_record,
    build_datalog_audit_record,
)
from pydexpi_datalog.semantics.souffle_runner import SouffleExecutionError


CONNECTIVITY_INTENT = {
    "source_classes": ["Tank"],
    "target_classes": ["CentrifugalPump"],
    "source_role": "process_equipment",
    "target_role": "pump",
    "graph_scope": "piping_only",
    "direction": "undirected",
    "quantifier": "all",
    "negated": True,
    "output_obligations": ["violating_source_ids"],
}


def test_probe_selection_uses_executable_predicate_contract_not_comments() -> None:
    result = run_mandatory_counterfactual_probes(
        "// piping_connected(Source, Target)\n.decl answer(x:symbol)",
        CONNECTIVITY_INTENT,
    )

    assert result["status"] == "failed"
    assert result["predicate_contract"] == []
    assert result["diagnostics"][0]["code"] == (
        "faithfulness.predicate_contract_mismatch"
    )


def test_probe_contract_cannot_be_spoofed_by_a_string_literal() -> None:
    result = run_mandatory_counterfactual_probes(
        (
            ".decl answer(x:symbol)\n.output answer\n"
            'answer(X) :- node_attribute(X, "label", '
            '"piping_connected(Source, Target)").'
        ),
        CONNECTIVITY_INTENT,
    )

    assert result["status"] == "failed"
    assert result["predicate_contract"] == []
    assert result["diagnostics"][0]["code"] == (
        "faithfulness.predicate_contract_mismatch"
    )


def test_probe_contract_follows_dependencies_across_multiline_rules(
    monkeypatch,
) -> None:
    def unavailable(_program: str, **_limits: object):
        raise SouffleExecutionError("missing", "unavailable")

    monkeypatch.setattr(counterfactual_probes, "run_souffle_program", unavailable)
    result = run_mandatory_counterfactual_probes(
        (
            ".decl disconnected(x:symbol)\n"
            ".decl answer(x:symbol)\n"
            ".output answer\n"
            "disconnected(Source) :-\n"
            "  piping_connected(Source, Target).\n"
            "answer(Source) :-\n"
            "  disconnected(Source)."
        ),
        CONNECTIVITY_INTENT,
    )

    assert result["predicate_contract"] == ["piping_connected"]
    assert result["probes"]


def test_probe_expectations_include_overlapping_source_and_target_classes(
    monkeypatch,
) -> None:
    def unavailable(_program: str, **_limits: object):
        raise SouffleExecutionError("missing", "unavailable")

    monkeypatch.setattr(counterfactual_probes, "run_souffle_program", unavailable)
    result = run_mandatory_counterfactual_probes(
        (
            ".decl answer(x:symbol)\n.output answer\n"
            "answer(Source) :- piping_connected(Source, Target)."
        ),
        {
            **CONNECTIVITY_INTENT,
            "source_classes": ["ProcessEquipment"],
            "target_classes": ["ProcessEquipment"],
        },
    )

    disconnected, direct, multihop, reverse, non_piping = result["probes"]
    assert len(disconnected["expected_witness_ids"]) == 2
    assert direct["expected_witness_ids"] == []
    assert multihop["expected_witness_ids"] == []
    assert reverse["expected_witness_ids"] == []
    assert len(non_piping["expected_witness_ids"]) == 2


def test_probe_identity_entropy_failure_blocks_progression(monkeypatch) -> None:
    def unavailable_entropy(_byte_count: int) -> str:
        raise BlockingIOError("entropy source unavailable")

    monkeypatch.setattr(counterfactual_probes.secrets, "token_hex", unavailable_entropy)
    result = run_mandatory_counterfactual_probes(
        (
            ".decl answer(x:symbol)\n.output answer\n"
            "answer(Source) :- piping_connected(Source, Target)."
        ),
        CONNECTIVITY_INTENT,
    )

    assert result["status"] == "failed"
    assert result["probes"] == []
    assert result["diagnostics"][0]["code"] == (
        "faithfulness.counterfactual_unavailable"
    )


def test_mandatory_probe_engine_unavailability_blocks_progression(monkeypatch) -> None:
    def unavailable(_program: str, **_limits: object):
        raise SouffleExecutionError(
            "souffle_missing",
            "Souffle is unavailable.",
            "No executable on PATH.",
        )

    monkeypatch.setattr(counterfactual_probes, "run_souffle_program", unavailable)
    result = run_mandatory_counterfactual_probes(
        (
            ".decl answer(x:symbol)\n.output answer\n"
            "answer(Source) :- piping_connected(Source, Target)."
        ),
        CONNECTIVITY_INTENT,
    )

    assert result["status"] == "failed"
    assert result["probes"]
    assert all(probe["outcome"] == "not_evaluated" for probe in result["probes"])
    assert all(
        probe["diagnostics"][0]["code"] == "faithfulness.counterfactual_unavailable"
        for probe in result["probes"]
    )


@pytest.mark.parametrize(
    ("graph_scope", "direction", "expected_predicate"),
    [
        ("piping_only", "directed", "piping_reachable"),
        ("piping_only", "undirected", "piping_connected"),
        ("instrumentation_inclusive", "directed", "reachable_any"),
        (
            "instrumentation_inclusive",
            "undirected",
            "reachable_any_undirected",
        ),
        ("all_topology", "directed", "reachable_any"),
        ("all_topology", "undirected", "reachable_any_undirected"),
    ],
)
def test_probe_selection_follows_normalized_scope_and_direction(
    monkeypatch,
    graph_scope,
    direction,
    expected_predicate,
) -> None:
    def unavailable(_program: str, **_limits: object):
        raise SouffleExecutionError(
            "souffle_missing",
            "Souffle is unavailable.",
            "No executable on PATH.",
        )

    monkeypatch.setattr(counterfactual_probes, "run_souffle_program", unavailable)
    intent = {
        **CONNECTIVITY_INTENT,
        "source_classes": ["AirReceiver"],
        "target_classes": ["PressureTransmitter"],
        "source_role": "vessel",
        "target_role": "instrument",
        "graph_scope": graph_scope,
        "direction": direction,
    }
    program = (
        ".decl disconnected(x:symbol)\n"
        ".decl answer(x:symbol)\n"
        ".output answer\n"
        f"disconnected(Source) :- {expected_predicate}(Source, Target).\n"
        "answer(Source) :- disconnected(Source)."
    )

    result = run_mandatory_counterfactual_probes(program, intent)

    assert result["predicate_contract"] == [expected_predicate]
    assert result["probes"]
    assert all(
        probe["probe_id"].startswith(f"{expected_predicate}:")
        for probe in result["probes"]
    )
    by_shape = {
        probe["probe_id"].rsplit(":", 1)[-1]: probe for probe in result["probes"]
    }
    assert by_shape["disconnected"]["expected_witness_ids"]
    assert by_shape["direct"]["expected_witness_ids"] == []
    assert by_shape["multihop"]["expected_witness_ids"] == []
    assert bool(by_shape["reverse"]["expected_witness_ids"]) is (
        direction == "directed"
    )
    assert bool(by_shape["non_piping"]["expected_witness_ids"]) is (
        graph_scope == "piping_only"
    )


def test_probe_selection_rejects_intents_over_bounded_replay_budget() -> None:
    intent = {
        **CONNECTIVITY_INTENT,
        "source_classes": [f"Source{index}" for index in range(5)],
        "target_classes": ["Target"],
    }

    result = run_mandatory_counterfactual_probes(
        (
            ".decl answer(x:symbol)\n.output answer\n"
            "answer(Source) :- piping_connected(Source, Target)."
        ),
        intent,
    )

    assert result["status"] == "failed"
    assert result["probes"] == []
    assert result["diagnostics"][0]["code"] == ("faithfulness.probe_budget_exceeded")


def test_datalog_audit_persists_counterfactual_probe_versions_and_outcomes(
    tmp_path,
) -> None:
    probes = [
        {
            "probe_id": "piping:Tank:CentrifugalPump:connected",
            "input_version": "probe-input-sha256",
            "outcome": "passed",
            "expected_witness_ids": [],
            "actual_witness_ids": [],
            "diagnostics": [],
        }
    ]
    attempts = [
        {
            "program_id": "failed-program-sha256",
            "status": "failed",
            "catalog_version": "counterfactual-probes/1",
            "predicate_contract": ["piping_connected"],
            "probes": probes,
            "diagnostics": [
                {
                    "code": "faithfulness.counterfactual_mismatch",
                    "probe_id": probes[0]["probe_id"],
                }
            ],
        },
        {
            "program_id": "corrected-program-sha256",
            "status": "passed",
            "catalog_version": "counterfactual-probes/1",
            "predicate_contract": ["piping_connected"],
            "probes": probes,
            "diagnostics": [],
        },
    ]
    review = {
        "status": "faithful",
        "back_translated_intent": CONNECTIVITY_INTENT,
        "diagnostics": [],
    }
    gate = {
        "status": "passed",
        "layers": {
            "mechanical": {"status": "passed", "diagnostics": []},
            "semantic": {"status": "passed", "diagnostics": []},
            "counterfactual": {"status": "passed", "diagnostics": []},
            "model_review": {"status": "passed", "diagnostics": []},
        },
        "diagnostics": [],
    }
    gate_attempts = [
        {"program_id": "failed-program-sha256", "status": "failed"},
        {"program_id": "corrected-program-sha256", **gate},
    ]
    record = build_datalog_audit_record(
        session_id="session-1",
        question="Must every tank reach a pump?",
        proposal={
            "proposal_id": "proposal-1",
            "formal_restatement": "Return disconnected tanks.",
            "generated_datalog": ".output answer",
            "faithfulness_probes": probes,
            "faithfulness_probe_attempts": attempts,
            "faithfulness_review": review,
            "faithfulness_gate": gate,
            "faithfulness_gate_attempts": gate_attempts,
        },
        decision="approved",
        executed=True,
        execution_status="answered",
        decided_at="2026-07-23T00:00:00+00:00",
    )

    audit_path = append_datalog_audit_record(tmp_path, record)
    persisted = json.loads(audit_path.read_text(encoding="utf-8"))

    assert persisted["faithfulness_probes"] == probes
    assert persisted["faithfulness_probe_attempts"] == attempts
    assert persisted["faithfulness_review"] == review
    assert persisted["faithfulness_gate"] == gate
    assert persisted["faithfulness_gate_attempts"] == gate_attempts
