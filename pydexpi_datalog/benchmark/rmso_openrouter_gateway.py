"""Local HTTP enforcement gateway for pre-registered RMSO model calls."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Iterator

import httpx

from pydexpi_datalog.benchmark.rmso_openrouter_policy import (
    MAX_OUTPUT_TOKENS,
    MODEL,
    OpenRouterRequestPolicy,
    OpenRouterSpendCapError,
)


class LockedOpenRouterGateway:
    """OpenAI-compatible localhost gateway enforcing one locked request policy."""

    def __init__(
        self,
        *,
        policy: OpenRouterRequestPolicy,
        credential: str,
        artifact_dir: Path,
        reserved_input_tokens: int,
        upstream_url: str,
        http_client: httpx.Client,
    ) -> None:
        self.policy = policy
        self.credential = credential
        self.artifact_dir = artifact_dir
        self.reserved_input_tokens = reserved_input_tokens
        self.upstream_url = upstream_url
        self.http_client = http_client
        self.actual_spend = 0.0
        self._active_reservations = 0.0
        self._call_count = 0
        self._unknown_cost_calls: list[int] = []
        self._policy_violations: list[dict[str, object]] = []
        self._current_attribution: dict[str, str] | None = None
        self._call_records: dict[int, dict[str, object]] = {}
        self._unattributed_attempts = 0
        self._spend_cap_blocked_attempts = 0
        self._lock = Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def __enter__(self) -> "LockedOpenRouterGateway":
        if self._server is not None:
            raise RuntimeError("OpenRouter gateway is already running.")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                gateway._handle_post(self)

            def log_message(self, format: str, *args: object) -> None:
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def base_url(self) -> str:
        """OpenAI-compatible base URL passed to the external agent."""
        if self._server is None:
            raise RuntimeError("OpenRouter gateway is not running.")
        host, port = self._server.server_address
        return f"http://{host}:{port}/v1"

    def accounting_snapshot(self) -> dict[str, object]:
        """Return complete known spend plus any condition invalidating the run."""
        with self._lock:
            return {
                "actual_spend_usd": self.actual_spend,
                "active_reservations_usd": self._active_reservations,
                "accounting_complete": not self._unknown_cost_calls,
                "attribution_complete": self._unattributed_attempts == 0,
                "unattributed_attempts": self._unattributed_attempts,
                "spend_cap_complete": self._spend_cap_blocked_attempts == 0,
                "spend_cap_blocked_attempts": self._spend_cap_blocked_attempts,
                "unknown_cost_calls": list(self._unknown_cost_calls),
                "calls": [
                    dict(self._call_records[number])
                    for number in sorted(self._call_records)
                ],
                "policy_violations": [dict(item) for item in self._policy_violations],
            }

    @contextmanager
    def attribute_calls(self, *, arm_id: str, question_id: str) -> Iterator[None]:
        """Attribute every call in one sequential scored episode."""
        if not arm_id or not question_id:
            raise ValueError("Call attribution requires arm_id and question_id.")
        with self._lock:
            if self._current_attribution is not None:
                raise RuntimeError("OpenRouter call attribution is already active.")
            self._current_attribution = {
                "arm_id": arm_id,
                "question_id": question_id,
            }
        try:
            yield
        finally:
            with self._lock:
                self._current_attribution = None

    def episode_accounting(
        self, *, arm_id: str, question_id: str
    ) -> dict[str, object]:
        """Return provider-ledger accounting for one scored episode."""
        with self._lock:
            records = [
                dict(record)
                for record in self._call_records.values()
                if record["arm_id"] == arm_id
                and record["question_id"] == question_id
            ]
        records.sort(key=lambda record: int(record["call_number"]))
        unknown = [
            record for record in records if record["status"] == "unknown_cost"
        ]
        known_cost = sum(float(record["known_cost_usd"]) for record in records)
        return {
            "accounting_complete": not unknown,
            "call_numbers": [int(record["call_number"]) for record in records],
            "cost_usd": None if unknown else known_cost,
            "known_cost_usd": known_cost,
            "policy_violation_call_numbers": [
                int(record["call_number"])
                for record in records
                if record["status"] == "policy_violation"
            ],
        }

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        if handler.path not in ("/chat/completions", "/v1/chat/completions"):
            self._send_json(handler, 404, {"error": "unsupported gateway path"})
            return
        try:
            content_length = int(handler.headers.get("Content-Length", "0"))
            incoming = json.loads(handler.rfile.read(content_length))
            if not isinstance(incoming, dict):
                raise ValueError("Chat completion request must be a JSON object.")
            locked = self.policy.apply(incoming)
            call_number, reservation, attribution = self._reserve_call()
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json(handler, 400, {"error": str(error)})
            return

        self._write_artifact(
            call_number,
            "request",
            {
                "attribution": attribution,
                "reservation_usd": reservation,
                "reserved_input_tokens": self.reserved_input_tokens,
                "request": locked,
            },
        )
        try:
            response = self.http_client.post(
                self.upstream_url,
                headers={
                    "Authorization": f"Bearer {self.credential}",
                    "Content-Type": "application/json",
                    "X-OpenRouter-Metadata": "enabled",
                },
                json=locked,
            )
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("OpenRouter response must be a JSON object.")
            self._write_artifact(
                call_number,
                "response",
                {"status_code": response.status_code, "response": payload},
            )
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
            self._mark_unknown_cost(call_number=call_number, reservation=reservation)
            self._write_artifact(call_number, "error", {"error": str(error)})
            self._send_json(handler, 502, {"error": str(error)})
            return

        if not response.is_success:
            if response.status_code >= 500:
                try:
                    cost = self._reported_cost(payload)
                except ValueError:
                    self._mark_unknown_cost(
                        call_number=call_number, reservation=reservation
                    )
                else:
                    self._settle_call(
                        call_number=call_number,
                        reservation=reservation,
                        actual_cost=cost,
                        status="upstream_error_billed",
                    )
            else:
                self._release_reservation(
                    call_number=call_number,
                    reservation=reservation,
                    status="upstream_rejected",
                )
            self._send_json(handler, response.status_code, payload)
            return

        try:
            cost = self._reported_cost(payload)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
            self._mark_unknown_cost(call_number=call_number, reservation=reservation)
            self._write_artifact(call_number, "error", {"error": str(error)})
            self._send_json(handler, 502, {"error": str(error)})
            return

        self._settle_call(
            call_number=call_number, reservation=reservation, actual_cost=cost
        )
        try:
            self._validate_response(payload)
        except ValueError as error:
            self._record_policy_violation(call_number=call_number, reason=str(error))
            self._write_artifact(call_number, "error", {"error": str(error)})
            self._send_json(handler, 502, {"error": str(error)})
            return
        self._send_json(handler, response.status_code, payload)

    def _reserve_call(self) -> tuple[int, float, dict[str, str]]:
        with self._lock:
            if self._current_attribution is None:
                self._unattributed_attempts += 1
                raise ValueError("OpenRouter call has no active episode attribution.")
            try:
                reservation = self.policy.reserve_call(
                    input_tokens=self.reserved_input_tokens,
                    actual_spend=self.actual_spend,
                    active_reservations=self._active_reservations,
                )
            except OpenRouterSpendCapError:
                self._spend_cap_blocked_attempts += 1
                raise
            self._active_reservations += reservation
            self._call_count += 1
            call_number = self._call_count
            attribution = dict(self._current_attribution)
            self._call_records[call_number] = {
                "call_number": call_number,
                **attribution,
                "status": "reserved",
                "known_cost_usd": 0.0,
                "reservation_usd": reservation,
            }
            return call_number, reservation, attribution

    def _settle_call(
        self,
        *,
        call_number: int,
        reservation: float,
        actual_cost: float,
        status: str = "settled",
    ) -> None:
        with self._lock:
            self._active_reservations -= reservation
            self.actual_spend += actual_cost
            self._call_records[call_number].update(
                {"status": status, "known_cost_usd": actual_cost}
            )

    def _release_reservation(
        self, *, call_number: int, reservation: float, status: str
    ) -> None:
        with self._lock:
            self._active_reservations -= reservation
            self._call_records[call_number]["status"] = status

    def _mark_unknown_cost(self, *, call_number: int, reservation: float) -> None:
        with self._lock:
            self._active_reservations -= reservation
            self._unknown_cost_calls.append(call_number)
            self._call_records[call_number]["status"] = "unknown_cost"

    def _record_policy_violation(self, *, call_number: int, reason: str) -> None:
        with self._lock:
            self._policy_violations.append(
                {"call_number": call_number, "reason": reason}
            )
            self._call_records[call_number]["status"] = "policy_violation"

    @staticmethod
    def _reported_cost(payload: dict[str, Any]) -> float:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("OpenRouter response lacks usage accounting.")
        cost = usage.get("cost")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
            raise ValueError("OpenRouter response lacks paid-cost accounting.")
        return float(cost)

    @staticmethod
    def _validate_response(payload: dict[str, Any]) -> None:
        if payload.get("model") != MODEL:
            raise ValueError("OpenRouter resolved a model other than pinned V4 Flash.")
        metadata = payload.get("openrouter_metadata")
        if (
            not isinstance(metadata, dict)
            or not isinstance(metadata.get("selected_provider"), str)
            or not metadata["selected_provider"]
        ):
            raise ValueError("OpenRouter response lacks resolved-provider metadata.")
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("OpenRouter response lacks usage accounting.")
        completion_tokens = usage.get("completion_tokens")
        if (
            not isinstance(completion_tokens, int)
            or isinstance(completion_tokens, bool)
            or completion_tokens < 0
            or completion_tokens > MAX_OUTPUT_TOKENS
        ):
            raise ValueError("OpenRouter response exceeds the output-token ceiling.")

    def _write_artifact(
        self, call_number: int, kind: str, payload: dict[str, object]
    ) -> None:
        destination = self.artifact_dir / f"call-{call_number:04d}-{kind}.json"
        staging = destination.with_name(f".{destination.name}.tmp")
        staging.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        staging.replace(destination)

    @staticmethod
    def _send_json(
        handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]
    ) -> None:
        content = json.dumps(payload).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(content)))
        handler.end_headers()
        handler.wfile.write(content)
