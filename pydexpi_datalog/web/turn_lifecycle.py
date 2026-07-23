from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from typing import Callable

from pydexpi_datalog.web.execution_trace import (
    TRACE_EVENT_ID_LENGTH,
    bound_reasoning_text,
    render_execution_trace,
    sanitize_progress_tool_input,
)

TURN_ID_LENGTH = 20
_TURN_ID_PATTERN = re.compile(rf"[0-9a-f]{{{TURN_ID_LENGTH}}}")
_TRACE_EVENT_ID_PATTERN = re.compile(rf"[0-9a-f]{{{TRACE_EVENT_ID_LENGTH}}}")


def compute_turn_id(session_id: str, request_id: str) -> str:
    """Deterministic turn_id, matching the frontend's computeTurnId() formula
    (frontend/lib/turn-client.ts) so the client can know a turn's id up front."""
    return hashlib.sha256(f"{session_id}\n{request_id}".encode("utf-8")).hexdigest()[
        :TURN_ID_LENGTH
    ]


class TurnLifecycleStore:
    """Disk-backed, replayable lifecycle for one server-owned QA turn."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = artifact_root
        self._lock = RLock()

    def start(
        self,
        *,
        session_id: str,
        request_id: str,
        question: str,
        execute: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        turn_id = compute_turn_id(session_id, request_id)
        with self._lock:
            existing = self.get(session_id=session_id, turn_id=turn_id)
            if existing is not None:
                if (
                    existing["request_id"] != request_id
                    or existing["question"] != question
                ):
                    raise ValueError("request_id was already used for a different turn")
                return existing
            turn = self.begin(
                session_id=session_id,
                request_id=request_id,
                question=question,
            )
        try:
            result = execute()
        except Exception as error:
            with self._lock:
                current = self.get(session_id=session_id, turn_id=turn_id)
                if current is not None and current.get("status") == "canceled":
                    return current
                # Reload before appending: execute() may have persisted
                # progress events directly to disk (append_progress) while it
                # ran -- reusing the pre-execute() in-memory snapshot here
                # would silently overwrite those with a stale copy.
                turn = current if current is not None else turn
                turn["status"] = "failed"
                self._append(turn, "failure", {"message": str(error)})
                self._save(turn)
            return turn

        with self._lock:
            current = self.get(session_id=session_id, turn_id=turn_id)
            if current is not None and current.get("status") == "canceled":
                return current
            turn = current if current is not None else turn
            turn["result"] = result
            self._append_result_events(turn, result)
            self._save(turn)
        return turn

    def begin(
        self, *, session_id: str, request_id: str, question: str
    ) -> dict[str, object]:
        turn_id = hashlib.sha256(
            f"{session_id}\n{request_id}".encode("utf-8")
        ).hexdigest()[:20]
        with self._lock:
            existing = self.get(session_id=session_id, turn_id=turn_id)
            if existing is not None:
                if (
                    existing["request_id"] != request_id
                    or existing["question"] != question
                ):
                    raise ValueError("request_id was already used for a different turn")
                return existing
            turn: dict[str, object] = {
                "schema_version": 1,
                "session_id": session_id,
                "turn_id": turn_id,
                "request_id": request_id,
                "question": question,
                "status": "active",
                "events": [self._event(0, "tool-progress", {"status": "started"})],
            }
            self._save(turn)
            return turn

    def append_progress(
        self,
        *,
        session_id: str,
        turn_id: str,
        round_index: int,
        max_rounds: int,
        tool_name: str | None,
        tool_input: dict[str, object] | None = None,
        reasoning: str | None = None,
    ) -> None:
        """Append a live round-progress event while a turn is still executing.

        Called from inside the (synchronous, in-request) tool-calling loop, so
        the frontend's existing poll-while-waiting loop has something new to
        render instead of a static "working" placeholder for the whole turn.

        Tool arguments and model reasoning are persisted bounded and redacted
        (bead 3qo.9.12) and omitted entirely when absent -- never fabricated.
        """
        with self._lock:
            turn = self.get(session_id=session_id, turn_id=turn_id)
            if turn is None or turn.get("status") != "active":
                return
            data: dict[str, object] = {
                "status": "round",
                "round": round_index,
                "max_rounds": max_rounds,
                "tool_name": tool_name,
            }
            sanitized_input = sanitize_progress_tool_input(tool_input)
            if sanitized_input:
                data["tool_input"] = sanitized_input
            bounded_reasoning = bound_reasoning_text(reasoning)
            if bounded_reasoning:
                data["reasoning"] = bounded_reasoning
            self._append(turn, "tool-progress", data)
            self._save(turn)

    def get(self, *, session_id: str, turn_id: str) -> dict[str, object] | None:
        path = self._path(session_id, turn_id)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None

    def get_trace_detail(
        self, *, session_id: str, turn_id: str, event_id: str
    ) -> dict[str, object] | None:
        if not _TURN_ID_PATTERN.fullmatch(
            turn_id
        ) or not _TRACE_EVENT_ID_PATTERN.fullmatch(event_id):
            return None
        root = self._artifact_root.resolve()
        path = (
            self._artifact_root
            / session_id
            / "turns"
            / f"{turn_id}.trace"
            / f"{event_id}.json"
        ).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None

    def cancel(self, *, session_id: str, turn_id: str) -> dict[str, object] | None:
        with self._lock:
            turn = self.get(session_id=session_id, turn_id=turn_id)
            if turn is None:
                return None
            if turn.get("status") in {"active", "paused"}:
                turn["status"] = "canceled"
                self._append(
                    turn,
                    "cancellation",
                    {"message": "The turn was canceled by the user."},
                )
                self._save(turn)
            return turn

    def resume(
        self,
        *,
        session_id: str,
        turn_id: str,
        execute: Callable[[], dict[str, object]],
    ) -> dict[str, object] | None:
        with self._lock:
            turn = self.get(session_id=session_id, turn_id=turn_id)
            if turn is None or turn.get("status") != "paused":
                return turn
            turn["status"] = "active"
            self._append(turn, "tool-progress", {"status": "resumed"})
            self._save(turn)
        try:
            result = execute()
        except Exception as error:
            with self._lock:
                current = self.get(session_id=session_id, turn_id=turn_id)
                if current is not None and current.get("status") == "canceled":
                    return current
                turn = current if current is not None else turn
                turn["status"] = "failed"
                self._append(turn, "failure", {"message": str(error)})
                self._save(turn)
            return turn
        with self._lock:
            current = self.get(session_id=session_id, turn_id=turn_id)
            if current is not None and current.get("status") == "canceled":
                return current
            turn = current if current is not None else turn
            turn["result"] = result
            self._append_result_events(turn, result)
            self._save(turn)
        return turn

    def _append_result_events(
        self, turn: dict[str, object], result: dict[str, object]
    ) -> None:
        status = str(result.get("status", "answered"))
        trace_events = render_execution_trace(
            artifact_root=self._artifact_root,
            session_id=str(turn["session_id"]),
            turn_id=str(turn["turn_id"]),
            raw_events=result.get("trace_events"),
            fallback_evidence_references=result.get(
                "evidence_references", result.get("witnesses", [])
            ),
        )
        for trace_event in trace_events:
            self._append(turn, "execution-trace", trace_event)
        answer_text = result.get("answer_text")
        if isinstance(answer_text, str) and answer_text:
            self._append(turn, "text", {"text": answer_text})

        evidence = {
            "evidence_references": result.get("evidence_references", []),
            "evidence_highlight": result.get("evidence_highlight", {}),
        }
        if evidence["evidence_references"] or evidence["evidence_highlight"]:
            self._append(turn, "evidence", evidence)

        if status in {"needs_direction_review", "needs_datalog_confirmation"}:
            turn["status"] = "paused"
            self._append(turn, "review-required", {"review": result})
            return
        if status in {"canceled", "cancelled"}:
            turn["status"] = "canceled"
            self._append(turn, "cancellation", {"result": result})
            return
        if status in {"failed", "execution_failed"}:
            turn["status"] = "failed"
            # Surface the result's diagnostics through `message` -- the
            # frontend renders event.data.message and otherwise shows a bare
            # "Turn failed" (bead 3cq).
            data: dict[str, object] = {"result": result}
            diagnostics = result.get("diagnostics")
            if isinstance(diagnostics, list):
                messages = [
                    str(item["message"])
                    for item in diagnostics
                    if isinstance(item, dict) and item.get("message")
                ]
                if messages:
                    data["message"] = "; ".join(messages)
            self._append(turn, "failure", data)
            return
        turn["status"] = "completed"
        self._append(turn, "completion", {"status": "completed"})

    @staticmethod
    def _event(sequence: int, event_type: str, data: object) -> dict[str, object]:
        return {"sequence": sequence, "type": event_type, "data": data}

    def _append(self, turn: dict[str, object], event_type: str, data: object) -> None:
        events = turn.setdefault("events", [])
        assert isinstance(events, list)
        events.append(self._event(len(events), event_type, data))

    def _path(self, session_id: str, turn_id: str) -> Path:
        return self._artifact_root / session_id / "turns" / f"{turn_id}.json"

    def _save(self, turn: dict[str, object]) -> None:
        path = self._path(str(turn["session_id"]), str(turn["turn_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(turn, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)
