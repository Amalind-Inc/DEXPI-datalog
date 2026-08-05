from __future__ import annotations

import json
from pathlib import Path

import pytest

from pydexpi_datalog.verification.governed_check import (
    CHECK_ID,
    CHECK_VERSION,
    GovernedCheckExecutionError,
    run_governed_check,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "testdata" / "verifier_suite" / "inputs"


def graph(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_scoped_pump_check_returns_typed_satisfied_result_with_ordered_evidence() -> None:
    result = run_governed_check(
        graph("pass_c01_local_segment_graph.json"),
        check_id=CHECK_ID,
        scope_entity_id="CentrifugalPump-1",
    )

    assert result["check_id"] == CHECK_ID
    assert result["check_version"] == CHECK_VERSION
    assert result["run_status"] == "completed"
    assert result["outcome"] == "satisfied"
    assert result["reason_code"] == "check_valve_found"
    assert result["scope"]["pump_id"] == "CentrifugalPump-1"
    assert result["coverage"]["requested_entity_id"] == "CentrifugalPump-1"
    assert result["coverage"]["evaluated_entity_id"] == "CentrifugalPump-1"
    assert result["coverage"]["complete"] is True
    assert result["source_attestation"]["revision"] == result["document_preparation_digest"]
    assert result["evidence"]["ordered_entity_ids"]
    assert result["evidence"]["ordered_entity_ids"][0] == "CentrifugalPump-1"
    assert result["engine"]["name"] == "souffle"
    assert result["cache_provenance"]["hit"] is False


def test_scoped_pump_check_returns_violated_only_for_a_complete_segment() -> None:
    result = run_governed_check(
        graph("hard_violation_c01_no_check_valve_graph.json"),
        check_id=CHECK_ID,
        scope_entity_id="CentrifugalPump-1",
    )

    assert result["run_status"] == "completed"
    assert result["outcome"] == "violated"
    assert result["reason_code"] == "no_check_valve_on_complete_segment"
    assert result["evidence"]["scope_completeness"]["complete"] is True
    assert result["evidence"]["ordered_entity_ids"]


def test_incomplete_segment_is_indeterminate_and_not_a_violation() -> None:
    result = run_governed_check(
        graph("bounded_failure_off_page_c01_graph.json"),
        check_id=CHECK_ID,
        scope_entity_id="CentrifugalPump-1",
    )

    assert result["run_status"] == "completed"
    assert result["outcome"] == "indeterminate"
    assert result["reason_code"] == "incomplete_discharge_segment"
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["missing_facts"]
    assert result["evidence"]["scope_completeness"]["complete"] is False


def test_scope_must_identify_exactly_one_centrifugal_pump() -> None:
    with pytest.raises(GovernedCheckExecutionError, match="scope.invalid"):
        run_governed_check(
            graph("pass_c01_local_segment_graph.json"),
            check_id=CHECK_ID,
            scope_entity_id="not-a-pump",
        )


def test_generic_valve_does_not_satisfy_the_check() -> None:
    result = run_governed_check(
        graph("hard_violation_c01_no_check_valve_graph.json"),
        check_id=CHECK_ID,
        scope_entity_id="CentrifugalPump-1",
    )

    matched_classes = [
        item["class"] for item in result["evidence"]["traversed_objects"]
    ]
    assert "CheckValve" not in matched_classes
    assert result["outcome"] == "violated"


def test_engine_failure_has_no_engineering_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("engine unavailable")

    monkeypatch.setattr(
        "pydexpi_datalog.verification.governed_check.evaluate_pack_rule",
        fail,
    )
    result = run_governed_check(
        graph("pass_c01_local_segment_graph.json"),
        check_id=CHECK_ID,
        scope_entity_id="CentrifugalPump-1",
    )

    assert result["run_status"] == "failed"
    assert result["outcome"] is None
    assert result["reason_code"] == "engine.execution_failed"


def test_cache_key_includes_digest_rule_version_and_parameters() -> None:
    from pydexpi_datalog.verification.governed_check import governed_check_cache_key

    first = governed_check_cache_key(
        document_digest="source-a",
        check_id=CHECK_ID,
        check_version=CHECK_VERSION,
        parameters={"scope_entity_id": "CentrifugalPump-1"},
    )
    assert first != governed_check_cache_key(
        document_digest="source-b",
        check_id=CHECK_ID,
        check_version=CHECK_VERSION,
        parameters={"scope_entity_id": "CentrifugalPump-1"},
    )
    assert first != governed_check_cache_key(
        document_digest="source-a",
        check_id=CHECK_ID,
        check_version=CHECK_VERSION + 1,
        parameters={"scope_entity_id": "CentrifugalPump-1"},
    )
    assert first != governed_check_cache_key(
        document_digest="source-a",
        check_id=CHECK_ID,
        check_version=CHECK_VERSION,
        parameters={"scope_entity_id": "CentrifugalPump-2"},
    )
