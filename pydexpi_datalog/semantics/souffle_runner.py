from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
from pathlib import Path


class SouffleExecutionError(RuntimeError):
    """Raised when a Souffle program cannot be executed to completion."""

    def __init__(self, code: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


def run_souffle_program(program_text: str) -> dict[str, list[tuple[str, ...]]]:
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

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        output_dir = tmp_path / "souffle-output"
        output_dir.mkdir(parents=True, exist_ok=True)
        program_path = tmp_path / "program.dl"
        program_path.write_text(program_text, encoding="utf-8")

        result = subprocess.run(
            [souffle_path, str(program_path), "-D", str(output_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SouffleExecutionError(
                "souffle_execution_failed",
                "Souffle program execution failed",
                detail=result.stderr,
            )

        relations: dict[str, list[tuple[str, ...]]] = {}
        for csv_path in sorted(output_dir.glob("*.csv")):
            with csv_path.open(encoding="utf-8", newline="") as file:
                reader = csv.reader(file, delimiter="\t")
                relations[csv_path.stem] = [tuple(row) for row in reader if row]
        return relations
