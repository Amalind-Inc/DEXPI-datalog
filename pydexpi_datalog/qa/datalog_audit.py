"""Durable audit trail for temporary Datalog approval decisions.

Each confirm or cancel decision on a temporary Datalog proposal appends one
JSON record to a per-session JSONL file so the decision history survives
process restarts and is readable without the application.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from ..workflow.artifact_store import ArtifactStore

AUDIT_FILENAME = "datalog_audit.jsonl"


def build_datalog_audit_record(
    *,
    session_id: str,
    question: str,
    proposal: dict[str, object],
    decision: str,
    executed: bool,
    execution_status: str,
    decided_at: str | None = None,
) -> dict[str, object]:
    raw_probes = proposal.get("faithfulness_probes")
    faithfulness_probes = (
        [dict(probe) for probe in raw_probes if isinstance(probe, dict)]
        if isinstance(raw_probes, list)
        else []
    )
    raw_attempts = proposal.get("faithfulness_probe_attempts")
    faithfulness_probe_attempts = (
        [dict(attempt) for attempt in raw_attempts if isinstance(attempt, dict)]
        if isinstance(raw_attempts, list)
        else []
    )
    raw_gate_attempts = proposal.get("faithfulness_gate_attempts")
    faithfulness_gate_attempts = (
        [dict(attempt) for attempt in raw_gate_attempts if isinstance(attempt, dict)]
        if isinstance(raw_gate_attempts, list)
        else []
    )
    raw_review = proposal.get("faithfulness_review")
    faithfulness_review = dict(raw_review) if isinstance(raw_review, dict) else {}
    raw_gate = proposal.get("faithfulness_gate")
    faithfulness_gate = dict(raw_gate) if isinstance(raw_gate, dict) else {}
    return {
        "proposal_id": str(proposal.get("proposal_id", "")),
        "session_id": session_id,
        "question": question,
        "formal_restatement": str(proposal.get("formal_restatement", "")),
        "generated_datalog": str(proposal.get("generated_datalog", "")),
        "faithfulness_probes": faithfulness_probes,
        "faithfulness_probe_attempts": faithfulness_probe_attempts,
        "faithfulness_review": faithfulness_review,
        "faithfulness_gate": faithfulness_gate,
        "faithfulness_gate_attempts": faithfulness_gate_attempts,
        "decision": decision,
        "decided_at": decided_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "executed": executed,
        "execution_status": execution_status,
    }


def append_datalog_audit_record(
    store: ArtifactStore, session_id: str, record: dict[str, object]
) -> str:
    key = f"{session_id}/{AUDIT_FILENAME}"
    store.append_line(key, json.dumps(record, ensure_ascii=False))
    return key
