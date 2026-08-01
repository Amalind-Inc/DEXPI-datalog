"""Run the PortLog local review API from the frozen macOS sidecar."""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

import uvicorn


def _watch_parent(parent_pid: int) -> None:
    while os.getppid() == parent_pid:
        time.sleep(0.25)
    os.kill(os.getpid(), signal.SIGTERM)


def _watch_parent_pipe() -> None:
    while os.read(0, 4096):
        pass
    os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    parent_pid = os.getppid()
    threading.Thread(target=_watch_parent, args=(parent_pid,), daemon=True).start()
    threading.Thread(target=_watch_parent_pipe, daemon=True).start()
    executable_dir = Path(__file__).resolve().parent
    os.environ["PATH"] = f"{executable_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    os.environ.setdefault("HARBORFIELD_DEPLOYMENT_PROFILE", "local")
    uvicorn.run(
        "pydexpi_datalog.web.asgi:app",
        host=os.environ.get("PORTLOG_SIDECAR_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORTLOG_SIDECAR_PORT", "8000")),
        log_level="warning",
    )
