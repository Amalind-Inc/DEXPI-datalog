"""Mark the benchmark suite slow so deselecting it is a visible choice.

These tests generate synthetic drawings and run real Souffle, which takes
minutes rather than seconds. They stay in the default `pytest` run: a suite
that hides its slow half by default is how a genuine truth-vs-engine
disagreement sat unnoticed here (bead pydexpi-datalog-1-plz7). The fast loop
opts out with `-m "not slow"`, which reports the count it deselected.
"""

from __future__ import annotations

import pathlib

import pytest

_BENCHMARK_DIR = pathlib.Path(__file__).parent


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    # This hook is handed every collected item in the session, not only the
    # ones under this directory, so it has to select its own.
    for item in items:
        if _BENCHMARK_DIR in pathlib.Path(str(item.path)).parents:
            item.add_marker(pytest.mark.slow)
