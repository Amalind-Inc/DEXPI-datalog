from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys


def write_checkpoint(program: Path, witnesses: list[str]) -> None:
    inspection = json.loads(
        (Path(__file__).resolve().parent / "graph_inspection.json").read_text(
            encoding="utf-8"
        )
    )
    known_ids = {node["id"] for node in inspection["nodes"]}
    unknown_ids = sorted(set(witnesses) - known_ids)
    if unknown_ids:
        raise ValueError(f"query emitted IDs outside the graph: {unknown_ids}")
    verdict = "violation_found" if witnesses else "no_violation"
    answer = {
        "verdict": verdict,
        "witness_ids": witnesses,
        "posture": "source_grounded",
        "answer_text": "Result produced by the latest executed Souffle query.",
        "support": {
            "steps": [
                {
                    "id": "scope",
                    "kind": "graph_scope",
                    "node_count": inspection["node_count"],
                    "edge_count": inspection["edge_count"],
                    "dependencies": [],
                },
                {
                    "id": "execution",
                    "kind": "souffle_execution",
                    "artifact": "analysis.dl",
                    "relation": "result_witness",
                    "witness_ids": witnesses,
                    "dependencies": ["scope"],
                },
            ],
            "claims": [
                {"claim": "verdict", "step_ids": ["execution"]},
                *(
                    {"claim": f"witness:{witness}", "step_ids": ["execution"]}
                    for witness in witnesses
                ),
            ],
        },
    }
    answer_path = program.parent / "structured_answer.json"
    temporary = answer_path.with_name(f".{answer_path.name}.tmp")
    temporary.write_text(
        json.dumps(answer, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(answer_path)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_query.py PROGRAM", file=sys.stderr)
        return 2
    program = Path(sys.argv[1]).resolve()
    if program.name != "analysis.dl":
        print("PROGRAM must be named analysis.dl", file=sys.stderr)
        return 2
    output = program.parent / ".query-out"
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)
    completed = subprocess.run(
        ["souffle", str(program), "-D", str(output)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        diagnostics = (completed.stderr or completed.stdout)[-4000:]
        print(diagnostics, file=sys.stderr)
        return completed.returncode
    result = output / "result_witness.csv"
    if not result.is_file():
        print("Souffle did not produce result_witness.csv", file=sys.stderr)
        return 1
    witnesses = []
    with result.open(newline="", encoding="utf-8") as stream:
        witnesses = [row[0] for row in csv.reader(stream, delimiter="\t") if row]
    witnesses = sorted(set(witnesses))
    write_checkpoint(program, witnesses)
    print(json.dumps({
        "ok": True,
        "rmso_checkpoint": "accepted",
        "witness_ids": witnesses,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
