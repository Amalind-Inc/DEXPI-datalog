"""Local HTTP enforcement gateway for pre-registered RMSO model calls."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import httpx

from pydexpi_datalog.benchmark.rmso_openrouter_policy import (
    MAX_OUTPUT_TOKENS,
    MODEL,
    OpenRouterRequestPolicy,
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
            call_number, reservation = self._reserve_call()
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json(handler, 400, {"error": str(error)})
            return

        self._write_artifact(
            call_number,
            "request",
            {
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
            if response.is_success:
                cost = self._validate_response(payload)
                self._settle_call(reservation=reservation, actual_cost=cost)
            self._send_json(handler, response.status_code, payload)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
            self._write_artifact(call_number, "error", {"error": str(error)})
            self._send_json(handler, 502, {"error": str(error)})

    def _reserve_call(self) -> tuple[int, float]:
        with self._lock:
            reservation = self.policy.reserve_call(
                input_tokens=self.reserved_input_tokens,
                actual_spend=self.actual_spend,
                active_reservations=self._active_reservations,
            )
            self._active_reservations += reservation
            self._call_count += 1
            return self._call_count, reservation

    def _settle_call(self, *, reservation: float, actual_cost: float) -> None:
        with self._lock:
            self._active_reservations -= reservation
            self.actual_spend += actual_cost

    @staticmethod
    def _validate_response(payload: dict[str, Any]) -> float:
        if payload.get("model") != MODEL:
            raise ValueError("OpenRouter resolved a model other than pinned V4 Flash.")
        metadata = payload.get("openrouter_metadata")
        if not isinstance(metadata, dict):
            raise ValueError("OpenRouter response lacks resolved-provider metadata.")
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("OpenRouter response lacks usage accounting.")
        completion_tokens = usage.get("completion_tokens")
        if (
            not isinstance(completion_tokens, int)
            or isinstance(completion_tokens, bool)
            or completion_tokens > MAX_OUTPUT_TOKENS
        ):
            raise ValueError("OpenRouter response exceeds the output-token ceiling.")
        cost = usage.get("cost")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
            raise ValueError("OpenRouter response lacks paid-cost accounting.")
        return float(cost)

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
