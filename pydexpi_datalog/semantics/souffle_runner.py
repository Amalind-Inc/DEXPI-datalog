from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile

try:
    import resource
except ImportError:  # pragma: no cover - exercised on non-POSIX hosts
    resource = None  # type: ignore[assignment]
from collections.abc import Callable
from pathlib import Path


class SouffleExecutionError(RuntimeError):
    """Raised when a Souffle program cannot be executed to completion."""

    def __init__(self, code: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


def _resource_limiter(
    *,
    cpu_seconds: int,
    address_space_bytes: int,
    output_bytes: int,
) -> Callable[[], None]:
    def apply_limits() -> None:
        if resource is None:
            raise RuntimeError("POSIX resource limits are unavailable.")
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (output_bytes, output_bytes),
        )
        if sys.platform == "linux":
            resource.setrlimit(
                resource.RLIMIT_AS,
                (address_space_bytes, address_space_bytes),
            )

    return apply_limits


def run_souffle_program(
    program_text: str,
    *,
    timeout_seconds: float | None = None,
    max_output_bytes: int | None = None,
    max_address_space_bytes: int | None = None,
) -> dict[str, list[tuple[str, ...]]]:
    """Execute a complete Souffle program and return its output relations.

    Returns a mapping of output relation name to its rows (tab-delimited
    Souffle CSV output, one tuple per row). Raises SouffleExecutionError if
    the souffle binary is missing or the program fails to run.
    """
    souffle_path = shutil.which("souffle")
    if souffle_path is None:
        raise SouffleExecutionError(
            "missing_souffle",
            "Missing required deterministic engine: souffle",
        )
    limits_requested = (
        max_output_bytes is not None and max_address_space_bytes is not None
    )
    if limits_requested and resource is None:
        raise SouffleExecutionError(
            "souffle_resource_isolation_unavailable",
            "Souffle resource isolation is unavailable on this platform",
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        output_dir = tmp_path / "souffle-output"
        output_dir.mkdir(parents=True, exist_ok=True)
        program_path = tmp_path / "program.dl"
        program_path.write_text(program_text, encoding="utf-8")
        apply_resource_limits: Callable[[], None] | None = None
        if limits_requested:
            assert max_output_bytes is not None
            assert max_address_space_bytes is not None
            apply_resource_limits = _resource_limiter(
                cpu_seconds=max(1, int(timeout_seconds or 1)),
                address_space_bytes=max_address_space_bytes,
                output_bytes=max_output_bytes,
            )

        try:
            result = subprocess.run(
                [souffle_path, str(program_path), "-D", str(output_dir)],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
                preexec_fn=apply_resource_limits,
            )
        except subprocess.TimeoutExpired as error:
            raise SouffleExecutionError(
                "souffle_execution_timeout",
                "Souffle program execution exceeded its time limit",
                detail=str(error),
            ) from error
        except subprocess.SubprocessError as error:
            raise SouffleExecutionError(
                "souffle_resource_isolation_failed",
                "Souffle resource isolation could not be established",
                detail=str(error),
            ) from error
        if result.returncode != 0:
            raise SouffleExecutionError(
                "souffle_execution_failed",
                "Souffle program execution failed",
                detail=result.stderr,
            )

        relations: dict[str, list[tuple[str, ...]]] = {}
        aggregate_output_bytes = 0
        for csv_path in sorted(output_dir.glob("*.csv")):
            aggregate_output_bytes += csv_path.stat().st_size
            if (
                max_output_bytes is not None
                and aggregate_output_bytes > max_output_bytes
            ):
                raise SouffleExecutionError(
                    "souffle_output_limit",
                    "Souffle output exceeded its size limit",
                    detail=csv_path.name,
                )
            with csv_path.open(encoding="utf-8", newline="") as file:
                reader = csv.reader(file, delimiter="\t")
                relations[csv_path.stem] = [tuple(row) for row in reader if row]
        return relations
