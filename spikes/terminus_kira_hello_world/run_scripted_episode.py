from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


SPIKE_ROOT = Path(__file__).resolve().parent
TASKS_ROOT = SPIKE_ROOT / "tasks"
TASK_NAME = "structured-answer-hello-world"
DRAWING_PATH = TASKS_ROOT / TASK_NAME / "environment" / "drawing.json"


class ScriptedOpenAIHandler(BaseHTTPRequestHandler):
    """A three-response OpenAI-compatible stand-in for one KIRA episode."""

    request_count = 0
    received_tool_schemas: list[list[dict[str, Any]]] = []

    def do_POST(self) -> None:  # noqa: N802 - HTTP handler API
        if not self.path.endswith("/chat/completions"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(content_length))
        tools = request.get("tools")
        if not isinstance(tools, list):
            self.send_error(HTTPStatus.BAD_REQUEST, "KIRA must use native tools")
            return
        type(self).received_tool_schemas.append(tools)

        response_index = type(self).request_count
        type(self).request_count += 1
        response = _scripted_completion(response_index, str(request.get("model", "")))
        encoded = json.dumps(response).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        """Keep the runnable spike output focused on its Harbor result."""


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _scripted_completion(response_index: int, model: str) -> dict[str, Any]:
    actions = [
        _tool_call(
            "scripted-write-answer",
            "execute_commands",
            {
                "analysis": "Inspect the supplied drawing and materialize its answer.",
                "plan": "Write the required structured result and display it.",
                "commands": [
                    {
                        "keystrokes": (
                            "cat /input/drawing.json && "
                            "printf '%s\\n' "
                            "'{\"verdict\":\"violation_found\","
                            "\"witness_ids\":[\"P-101\",\"CV-201\"]}' "
                            "> /workspace/structured_answer.json && "
                            "cat /workspace/structured_answer.json"
                        ),
                        "duration": 1,
                    }
                ],
            },
        ),
        _tool_call("scripted-complete-confirm", "task_complete", {}),
        _tool_call("scripted-complete-final", "task_complete", {}),
    ]
    if response_index >= len(actions):
        raise AssertionError("KIRA requested more than its scripted three responses")
    return {
        "id": f"scripted-{response_index}",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "", "tool_calls": [actions[response_index]]},
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _function_names(value: object) -> list[str]:
    if isinstance(value, dict):
        names = [str(value["function_name"])] if "function_name" in value else []
        for child in value.values():
            names.extend(_function_names(child))
        return names
    if isinstance(value, list):
        return [name for child in value for name in _function_names(child)]
    return []


def _validate_harbor_artifacts(jobs_dir: Path) -> None:
    rewards = list(jobs_dir.rglob("reward.txt"))
    if len(rewards) != 1 or rewards[0].read_text().strip() != "1":
        raise AssertionError(f"expected one passing Harbor reward, found: {rewards}")

    trajectories = list(jobs_dir.rglob("*trajectory*.json"))
    names = [name for path in trajectories for name in _function_names(json.loads(path.read_text()))]
    if "bash_command" not in names:
        raise AssertionError("trajectory did not record KIRA terminal execution")
    if names.count("mark_task_complete") < 2:
        raise AssertionError("trajectory did not record KIRA's two-step completion gate")


def run_episode(*, kira_dir: Path, jobs_dir: Path) -> None:
    before_drawing = DRAWING_PATH.read_bytes()
    ScriptedOpenAIHandler.request_count = 0
    ScriptedOpenAIHandler.received_tool_schemas = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedOpenAIHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    api_base = f"http://127.0.0.1:{server.server_port}/v1"
    env = os.environ | {"OPENAI_API_KEY": "scripted-stand-in-key"}
    command = [
        "uv",
        "run",
        "--directory",
        str(kira_dir),
        "harbor",
        "run",
        "--path",
        str(TASKS_ROOT),
        "--task-name",
        TASK_NAME,
        "--agent-import-path",
        "terminus_kira.terminus_kira:TerminusKira",
        "--model",
        "openai/scripted-structured-answer",
        "--agent-kwarg",
        f"api_base={api_base}",
        "--agent-kwarg",
        "max_turns=3",
        "--env",
        "docker",
        "--jobs-dir",
        str(jobs_dir),
    ]
    try:
        subprocess.run(command, check=True, env=env)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()

    if DRAWING_PATH.read_bytes() != before_drawing:
        raise AssertionError("the immutable toy drawing was modified")
    if ScriptedOpenAIHandler.request_count != 3:
        raise AssertionError(
            f"expected exactly three native-tool completions, got {ScriptedOpenAIHandler.request_count}"
        )
    if not all(ScriptedOpenAIHandler.received_tool_schemas):
        raise AssertionError("one or more model calls did not receive KIRA's tool schema")
    _validate_harbor_artifacts(jobs_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Harbor/Terminus-KIRA structured-answer smoke episode."
    )
    parser.add_argument(
        "--kira-dir",
        type=Path,
        default=os.environ.get("HARBORFIELD_TERMINUS_KIRA_DIR"),
        help="Checkout of the official krafton-ai/KIRA repository.",
    )
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        help="Optional Harbor output directory; defaults to a temporary directory.",
    )
    args = parser.parse_args()
    if args.kira_dir is None:
        parser.error("supply --kira-dir or set HARBORFIELD_TERMINUS_KIRA_DIR")
    kira_dir = args.kira_dir.resolve()
    if not (kira_dir / "pyproject.toml").exists():
        parser.error(f"not a KIRA checkout: {kira_dir}")

    if args.jobs_dir is None:
        with tempfile.TemporaryDirectory(prefix="pydexpi-3q1-kira-") as temp_dir:
            run_episode(kira_dir=kira_dir, jobs_dir=Path(temp_dir))
    else:
        if args.jobs_dir.exists():
            shutil.rmtree(args.jobs_dir)
        run_episode(kira_dir=kira_dir, jobs_dir=args.jobs_dir.resolve())
    print("PASS: Harbor/Terminus-KIRA completed the structured-answer smoke episode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
