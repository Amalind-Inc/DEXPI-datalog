"""Durable audit trail for temporary Datalog approval decisions.

Each confirm or cancel decision on a temporary Datalog proposal appends one
JSON record to a per-session JSONL file so the decision history survives
process restarts and is readable without the application.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

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
    return {
        "proposal_id": str(proposal.get("proposal_id", "")),
        "session_id": session_id,
        "question": question,
        "formal_restatement": str(proposal.get("formal_restatement", "")),
        "generated_datalog": str(proposal.get("generated_datalog", "")),
        "decision": decision,
        "decided_at": decided_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "executed": executed,
        "execution_status": execution_status,
    }


def append_datalog_audit_record(
    session_dir: Path, record: dict[str, object]
) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    audit_path = session_dir / AUDIT_FILENAME
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return audit_path
