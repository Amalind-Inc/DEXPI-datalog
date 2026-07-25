"""PROTOTYPE -- throwaway. Delete after the question below is answered.

Question this prototype answers:
    When a real LLM drives the actual /turns HTTP flow end to end -- template
    routing (3qo.9.1/9.2), structured-intent + counterfactual faithfulness
    gating (3qo.9.3/9.4/9.5), and the structured execution trace (3qo.9.6) --
    does the resulting turn state feel right from a terminal, question by
    question? Does the model reach for the bundled template when it should,
    fall back to generated Datalog + the faithfulness gate when it shouldn't,
    and does the trace read as a sane audit log of what happened?

This does NOT reimplement any logic. It boots the real FastAPI review app
in-process (the same `create_review_api_app` the frontend talks to) against
the checked-in E06 pump/heat-exchanger fixture, wires a real OpenRouter
model, and lets you type questions at it. Nothing here should be lifted into
production -- if the answer is "yes, this feels right", the interesting bit
was already production code before this file existed.

Run:
    uv run python -m pydexpi_datalog.web.prototype_qa_turn_repl

OPENROUTER_API_KEY is read from the environment, or from a repo-root .env /
.env.local file (KEY=VALUE lines) if not already set -- same as the .env
this repo already keeps for manual/local LLM runs. An explicit environment
variable always wins over the file.

Optional:
    PROTOTYPE_QA_MODEL=anthropic/claude-sonnet-4   (default; must be tool-capable)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from pydexpi_datalog.web.review_api import create_review_api_app  # noqa: E402
from pydexpi_datalog.web.turn_lifecycle import compute_turn_id  # noqa: E402

REPO_ROOT = _REPO_ROOT
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"

STATUS_COLOR = {
    "answered": GREEN,
    "completed": GREEN,
    "active": YELLOW,
    "paused": YELLOW,
    "failed": RED,
    "canceled": RED,
}


def clear() -> None:
    print("\033[2J\033[H", end="")


def bold(text: str) -> str:
    return f"{BOLD}{text}{RESET}"


def dim(text: str) -> str:
    return f"{DIM}{text}{RESET}"


def colored_status(status: str) -> str:
    color = STATUS_COLOR.get(status, "")
    return f"{color}{status}{RESET}" if color else status


def render_event(event: dict[str, object]) -> None:
    event_type = event.get("type")
    data = event.get("data", {})
    if not isinstance(data, dict):
        data = {}
    if event_type == "execution-trace":
        kind = data.get("kind", "?")
        category = data.get("category", "?")
        status = data.get("status", "?")
        summary = data.get("summary", "")
        occurrences = data.get("occurrence_count", 1)
        evidence = data.get("evidence_references", [])
        print(
            f"  {bold('trace')} {dim(f'[{category}]')} {kind} -> {colored_status(str(status))}"
        )
        print(f"    {summary}")
        if occurrences and occurrences != 1:
            print(dim(f"    occurrences: {occurrences}"))
        if evidence:
            print(dim(f"    evidence: {', '.join(str(e) for e in evidence)}"))
    elif event_type == "text":
        print(f"  {bold('answer')} {data.get('text', '')}")
    elif event_type == "review-required":
        review = data.get("review", {})
        print(f"  {bold('review-required')} {dim(str(review)[:200])}")
    elif event_type == "tool-progress":
        print(dim(f"  tool-progress: {data}"))
    elif event_type == "failure":
        print(f"  {RED}failure{RESET}: {data.get('message', '')}")
    elif event_type == "cancellation":
        print(f"  {RED}canceled{RESET}: {data.get('message', '')}")
    else:
        print(dim(f"  {event_type}: {data}"))


def render_grounding(turn: dict[str, object]) -> None:
    """One reliability line per answer: how grounded it is and how it was
    assembled -- deterministic template execution vs model-assembled tool use.
    All data comes from the answered payload; nothing is inferred here."""
    result = turn.get("result")
    if not isinstance(result, dict):
        return
    posture = result.get("grounding_posture") or "unspecified"
    grounded = result.get("source_grounded")
    grounded_text = (
        f"{GREEN}source-grounded{RESET}"
        if grounded
        else f"{YELLOW}not source-grounded{RESET}"
    )
    print(f"  {bold('grounding')} {grounded_text} {dim(f'(posture: {posture})')}")

    route_artifact = result.get("route_artifact")
    if isinstance(route_artifact, dict):
        template = route_artifact.get("template_id", "?")
        version = route_artifact.get("template_version", "?")
        print(
            f"  {bold('method')} {GREEN}deterministic{RESET} "
            f"{dim(f'bundled template {template} v{version}, real engine run over the loaded graph -- [:o] shows the executed logic')}"
        )
    else:
        tool_names = [
            str(event["data"].get("tool_name"))
            for event in turn.get("events", [])
            if isinstance(event, dict)
            and event.get("type") == "tool-progress"
            and isinstance(event.get("data"), dict)
            and event["data"].get("tool_name")
        ]
        assembled = (
            f"model-assembled from tool calls: {', '.join(tool_names)}"
            if tool_names
            else "model-assembled without tool calls"
        )
        print(
            f"  {bold('method')} {YELLOW}not deterministically verified{RESET} {dim(f'({assembled})')}"
        )
    disclosure = result.get("disclosure")
    if disclosure:
        print(f"  {bold('disclosure')} {YELLOW}{disclosure}{RESET}")


def render_frame(
    *,
    session_id: str,
    provider: str,
    model: str,
    topology_summary: str,
    history: list[dict[str, object]],
) -> None:
    clear()
    print(bold("=== Grounded QA turn REPL (PROTOTYPE) ==="))
    print(dim(f"session: {session_id}  provider: {provider}/{model}"))
    print(dim(f"fixture: {topology_summary}"))
    print()
    if not history:
        print(dim("No turns yet. Ask a question about the loaded E06 drawing."))
    for turn in history[-5:]:
        print(f"{bold('Q:')} {turn['question']}")
        print(f"{bold('status:')} {colored_status(str(turn['status']))}")
        for event in turn.get("events", []):
            render_event(event)
        render_grounding(turn)
        print()
    print(dim("-" * 60))
    print(
        f"{bold('[type a question + enter]')}  {bold('[:q]')} {dim('quit')}  {bold('[:h]')} {dim('full history')}  {bold('[:o]')} {dim('logic program')}"
    )
    print(dim("-" * 60))


def _load_dotenv_defaults(env_path: Path) -> None:
    """Populate os.environ from a simple KEY=VALUE .env file, without
    overriding variables the caller already set explicitly."""
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    _load_dotenv_defaults(REPO_ROOT / ".env")
    _load_dotenv_defaults(REPO_ROOT / ".env.local")
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("OPENROUTER_API_KEY is required. Set it in the environment or in a")
        print(f"repo-root .env file ({REPO_ROOT / '.env'}). Example:")
        print(
            "  OPENROUTER_API_KEY=sk-... uv run python -m pydexpi_datalog.web.prototype_qa_turn_repl"
        )
        sys.exit(1)
    if not E06_FIXTURE.is_file():
        print(f"Fixture not found: {E06_FIXTURE}")
        print("TrainingTestCases is an external fixture corpus and is not checked in.")
        sys.exit(1)

    # Deliberately not sourced from .env's OPENROUTER_MODEL: that value may
    # not be on the native-tool-calling allowlist this flow requires.
    model = os.environ.get("PROTOTYPE_QA_MODEL", "anthropic/claude-sonnet-4")
    artifact_root = Path(tempfile.mkdtemp(prefix="pydexpi-qa-repl-"))
    session_id = f"repl-{uuid.uuid4().hex[:8]}"
    history: list[dict[str, object]] = []

    try:
        app = create_review_api_app(artifact_root=artifact_root)
        client = TestClient(app)

        prepared = client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={
                "filename": E06_FIXTURE.name,
                "content": E06_FIXTURE.read_text(encoding="utf-8"),
            },
        )
        if prepared.status_code != 200:
            print(f"Session preparation failed: {prepared.status_code} {prepared.text}")
            sys.exit(1)
        topology_view = prepared.json().get("topology_view") or {}
        node_count = len(topology_view.get("nodes", []))
        edge_count = len(topology_view.get("edges", []))
        topology_summary = (
            f"{E06_FIXTURE.name} ({node_count} nodes, {edge_count} edges)"
        )

        configured = client.put(
            f"/api/review/sessions/{session_id}/provider-settings",
            json={"provider": "openrouter", "model": model, "credential": api_key},
        )
        if configured.status_code != 200:
            print(
                f"Provider configuration failed: {configured.status_code} {configured.text}"
            )
            sys.exit(1)

        render_frame(
            session_id=session_id,
            provider="openrouter",
            model=model,
            topology_summary=topology_summary,
            history=history,
        )

        while True:
            try:
                question = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question:
                continue
            if question in (":q", ":quit"):
                break
            if question in (":h", ":history"):
                render_frame(
                    session_id=session_id,
                    provider="openrouter",
                    model=model,
                    topology_summary=topology_summary,
                    history=history,
                )
                for turn in history:
                    print(
                        f"{bold('Q:')} {turn['question']}  {dim(str(turn['status']))}"
                    )
                input(dim("\n[enter to continue]"))
                render_frame(
                    session_id=session_id,
                    provider="openrouter",
                    model=model,
                    topology_summary=topology_summary,
                    history=history,
                )
                continue
            if question in (":o", ":logic"):
                # Show the deterministic logic behind the most recent
                # template-backed answer: the exact rules the engine ran.
                artifact = None
                for past in reversed(history):
                    result = past.get("result")
                    if isinstance(result, dict) and isinstance(
                        result.get("route_artifact"), dict
                    ):
                        artifact = result["route_artifact"]
                        break
                if artifact is None:
                    print(
                        dim(
                            "  no template-backed answer yet -- the logic program"
                            " exists only for deterministic template routes"
                        )
                    )
                    continue
                print(bold("=== executed logic program (Souffle) ==="))
                print(
                    dim(
                        f"template: {artifact.get('template_id')}"
                        f" v{artifact.get('template_version')}"
                    )
                )
                print(dim(f"bindings: {artifact.get('bindings')}"))
                print(
                    dim(
                        "EDB facts (node_label, edges) come from the loaded"
                        " drawing; piping_connected from the bundled topology"
                        " IDB. Rules below ran verbatim:"
                    )
                )
                print(artifact.get("logic_program", "(missing)"))
                input(dim("\n[enter to continue]"))
                render_frame(
                    session_id=session_id,
                    provider="openrouter",
                    model=model,
                    topology_summary=topology_summary,
                    history=history,
                )
                continue

            request_id = uuid.uuid4().hex
            turn_id = compute_turn_id(session_id, request_id)
            print(dim("  -> calling model... (live trace below)"))

            result_holder: dict[str, object] = {}

            # Bound as defaults, not captured: the worker is joined before the
            # next iteration today, so this is about keeping that safe if the
            # loop ever starts more than one turn.
            def _run_turn(
                holder: dict[str, object] = result_holder,
                question: str = question,
                request_id: str = request_id,
            ) -> None:
                holder["response"] = client.post(
                    f"/api/review/sessions/{session_id}/turns",
                    json={"question": question, "request_id": request_id},
                )

            worker = threading.Thread(target=_run_turn, daemon=True)
            worker.start()

            after_sequence = -1
            while worker.is_alive():
                time.sleep(0.3)
                events_response = client.get(
                    f"/api/review/sessions/{session_id}/turns/{turn_id}/events",
                    params={"after": after_sequence},
                )
                if events_response.status_code != 200:
                    continue
                for line in events_response.text.splitlines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    render_event(event)
                    after_sequence = max(
                        after_sequence, int(event.get("sequence", after_sequence))
                    )
            worker.join()
            response = result_holder["response"]
            if response.status_code != 200:
                turn = {
                    "question": question,
                    "status": "failed",
                    "events": [
                        {
                            "type": "failure",
                            "data": {
                                "message": f"HTTP {response.status_code}: {response.text[:300]}"
                            },
                        }
                    ],
                }
            else:
                body = response.json()
                turn = {
                    "question": question,
                    "status": body.get("status", "unknown"),
                    "events": body.get("events", []),
                    "result": body.get("result"),
                }
            history.append(turn)
            render_frame(
                session_id=session_id,
                provider="openrouter",
                model=model,
                topology_summary=topology_summary,
                history=history,
            )
    finally:
        shutil.rmtree(artifact_root, ignore_errors=True)


if __name__ == "__main__":
    main()
