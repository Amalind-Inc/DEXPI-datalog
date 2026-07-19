from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

INPUT_DIR = Path(os.environ.get("INPUT_DIR", "/input"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
EXPECTED_SHA256 = {
    "analysis_template.dl": "4d4c86df3afdfdac714a3c7cc6ea22fc614c4c3d256e3a9484f97ed12d1d2cbe",
    "graph_facts.dl": "535bde8beb6a0833ee8ffae512785fe611f40cfa516213881d52e85374177f11",
    "graph_facts.json": "2c3d13575af7c08c4644013a55ee4015e87379b6186aeaed1d6f32f97b0de142",
    "graph_inspection.json": "6b8f1720189415bd6a3f223d889fbcd6f51c875b55ea8a37117bb1a804377769",
    "graph_topology_semantics.dl": "1b0270917c598f8bc5f66db94dc5f0247b14290d7acb4bb76f79ae2b9cfa15eb",
    "run_query.py": "73d621b2e9dcbd398006ed1160943e903f8301c9ab8aeaffefd1911543c2796a"
}
REQUIRED_NONEMPTY = ["analysis.dl"]
REPLAY_PYTHON_ANALYSIS = False
PYTHON_ANALYSIS_INPUT = 'drawing.xml'


def main() -> int:
    for name, expected in EXPECTED_SHA256.items():
        actual = hashlib.sha256((INPUT_DIR / name).read_bytes()).hexdigest()
        if actual != expected:
            raise AssertionError(f"read-only input was changed: {name}")

    answer_path = WORKSPACE_DIR / "structured_answer.json"
    if not answer_path.exists():
        raise AssertionError(f"missing structured answer: {answer_path}")
    answer = json.loads(answer_path.read_text(encoding="utf-8"))
    if not isinstance(answer, dict):
        raise AssertionError(f"structured answer is not a JSON object: {answer!r}")
    for name in REQUIRED_NONEMPTY:
        path = WORKSPACE_DIR / name
        if not path.exists():
            raise AssertionError(f"missing required submission: {path}")
        if not path.read_text(encoding="utf-8").strip():
            raise AssertionError(f"required submission is empty: {path}")
    if REPLAY_PYTHON_ANALYSIS:
        script_path = WORKSPACE_DIR / "analysis.py"
        replay = subprocess.run(
            [sys.executable, str(script_path), str(INPUT_DIR / PYTHON_ANALYSIS_INPUT)],
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if replay.returncode != 0:
            raise AssertionError(
                f"analysis replay failed ({replay.returncode}): {replay.stderr}"
            )
        try:
            replayed = json.loads(replay.stdout)
        except json.JSONDecodeError as error:
            raise AssertionError(f"analysis replay did not emit JSON: {error}")
        expected = {
            "verdict": answer.get("verdict"),
            "witness_ids": answer.get("witness_ids"),
        }
        if replayed != expected:
            raise AssertionError(
                f"analysis replay does not match structured answer: "
                f"{replayed!r} != {expected!r}"
            )
        (WORKSPACE_DIR / "analysis_replay.json").write_text(
            json.dumps(replayed, sort_keys=True), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
