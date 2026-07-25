from __future__ import annotations

from pydexpi_datalog.qa.topology_tools import RetrievalBudgets, TopologyTools

TOPOLOGY = {
    "nodes": [
        {"id": "pump-1", "label": "Pump", "tag_name": "P-101"},
        {"id": "pump-2", "label": "Pump", "tag_name": "P-102"},
        {"id": "pump-3", "label": "Pump", "tag_name": "P-103"},
    ],
    "edges": [
        {
            "id": "edge-1",
            "source_id": "pump-1",
            "target_id": "pump-2",
            "relationship": "connected_to",
        },
        {
            "id": "edge-2",
            "source_id": "pump-2",
            "target_id": "pump-3",
            "relationship": "connected_to",
        },
    ],
    "evidence_map": {
        "pump-1": {"id": "pump-1"},
        "pump-2": {"id": "pump-2"},
        "pump-3": {"id": "pump-3"},
        "edge-1": {"id": "edge-1"},
        "edge-2": {"id": "edge-2"},
    },
}


def test_existential_lookup_keeps_witness_and_reports_low_row_budget() -> None:
    tools = TopologyTools(
        topology_view=TOPOLOGY,
        session_id="s",
        retrieval_budgets=RetrievalBudgets(max_rows=1, max_evidence_objects=1),
    )

    result = tools.execute(
        "find_equipment",
        {"pattern": "pump", "claim_type": "existential"},
    )

    assert result["outcome"] == "satisfied"
    assert [match["evidence_id"] for match in result["matches"]] == ["pump-1"]
    assert result["coverage"] == {
        "complete": False,
        "examined_rows": 1,
        "total_rows": 3,
        "returned_evidence_objects": 1,
    }
    assert result["limitations"][0]["code"] == "retrieval.row_limit"


def test_incomplete_universal_and_absence_claims_are_indeterminate() -> None:
    tools = TopologyTools(
        topology_view=TOPOLOGY,
        session_id="s",
        retrieval_budgets=RetrievalBudgets(max_rows=1),
    )

    universal = tools.execute(
        "find_equipment", {"pattern": "missing", "claim_type": "universal"}
    )
    absence = tools.execute(
        "find_equipment", {"pattern": "pump", "claim_type": "absence"}
    )

    assert universal["outcome"] == "indeterminate"
    assert absence["outcome"] == "violated"
    assert absence["matches"]  # a witnessed match disproves absence conclusively


def test_witnessed_universal_counterexample_remains_conclusive() -> None:
    tools = TopologyTools(
        topology_view=TOPOLOGY,
        session_id="s",
        retrieval_budgets=RetrievalBudgets(max_rows=1),
    )

    result = tools.execute(
        "find_equipment",
        {
            "pattern": "pump",
            "claim_type": "universal",
            "evidence_role": "counterexample",
        },
    )

    assert result["outcome"] == "violated"
    assert result["coverage"]["complete"] is False


def test_low_path_and_path_length_limits_keep_explanatory_evidence() -> None:
    tools = TopologyTools(
        topology_view=TOPOLOGY,
        session_id="s",
        retrieval_budgets=RetrievalBudgets(max_paths=1, max_path_length=1),
    )

    result = tools.execute(
        "get_reachable_equipment",
        {"equipment_id": "pump-1", "max_hops": 6, "claim_type": "explanation"},
    )

    assert result["outcome"] == "satisfied"
    assert result["reachable"]
    assert result["coverage"]["complete"] is False
    assert {item["code"] for item in result["limitations"]} >= {
        "retrieval.path_limit",
        "retrieval.path_length_limit",
    }


def test_step_and_payload_limits_are_explicit() -> None:
    tools = TopologyTools(
        topology_view=TOPOLOGY,
        session_id="s",
        retrieval_budgets=RetrievalBudgets(max_steps=1, max_payload_bytes=1),
    )

    first = tools.execute("find_equipment", {"pattern": "pump"})
    second = tools.execute("find_equipment", {"pattern": "pump"})

    assert first["coverage"]["complete"] is False
    assert first["limitations"][0]["code"] == "retrieval.payload_size_limit"
    assert second["outcome"] == "indeterminate"
    assert second["limitations"][0]["code"] == "retrieval.step_limit"


def test_zero_time_budget_returns_explicit_indeterminate_result() -> None:
    tools = TopologyTools(
        topology_view=TOPOLOGY,
        session_id="s",
        retrieval_budgets=RetrievalBudgets(max_seconds=0),
    )

    result = tools.execute("find_equipment", {"pattern": "pump"})

    assert result["outcome"] == "indeterminate"
    assert result["coverage"]["complete"] is False
    assert result["limitations"][0]["code"] == "retrieval.time_limit"


def test_time_budget_is_not_consumed_by_time_between_tool_calls() -> None:
    """
    Regression: the time budget used to be measured as wall-clock time since
    TopologyTools was constructed, which included time spent waiting on the
    model between tool calls. A slower model (larger reasoning model over
    BYOK/OpenRouter) could burn through the whole budget on its own thinking
    time alone, so every retrieval call after the first one or two would be
    spuriously time_limit-rejected regardless of how trivial the query was.
    The budget must only count time actually spent inside tool execution.
    """
    import time

    tools = TopologyTools(
        topology_view=TOPOLOGY,
        session_id="s",
        retrieval_budgets=RetrievalBudgets(max_seconds=0.02),
    )

    # Simulate model "thinking time" between tool calls, comfortably longer
    # than the budget itself -- under the old (buggy) wall-clock-since-init
    # measurement this alone would exhaust the budget before any tool ever
    # ran; it must not count against the budget now.
    time.sleep(0.05)

    result = tools.execute("find_equipment", {"pattern": "pump"})

    limitation_codes = [limitation["code"] for limitation in result.get("limitations", [])]
    assert "retrieval.time_limit" not in limitation_codes
