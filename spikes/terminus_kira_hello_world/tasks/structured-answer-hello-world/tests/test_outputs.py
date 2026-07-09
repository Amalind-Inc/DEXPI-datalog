from __future__ import annotations

import json
from pathlib import Path


DRAWING_PATH = Path("/input/drawing.json")
ANSWER_PATH = Path("/workspace/structured_answer.json")
EXPECTED_DRAWING = {
    "drawing_id": "hello-world-pid",
    "graph_facts": {
        "violations": [
            {
                "verdict": "violation_found",
                "witness_ids": ["P-101", "CV-201"],
            }
        ]
    },
}
EXPECTED_ANSWER = {
    "verdict": "violation_found",
    "witness_ids": ["P-101", "CV-201"],
}


def main() -> int:
    drawing = json.loads(DRAWING_PATH.read_text())
    if drawing != EXPECTED_DRAWING:
        raise AssertionError(f"source drawing was changed: {drawing!r}")

    if not ANSWER_PATH.exists():
        raise AssertionError(f"missing structured answer: {ANSWER_PATH}")

    answer = json.loads(ANSWER_PATH.read_text())
    if answer != EXPECTED_ANSWER:
        raise AssertionError(f"unexpected structured answer: {answer!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
