"""Complete preregistered RMSO dry run with scripted providers only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from pydexpi_datalog.benchmark.agentic_arm import (
    ANALYSIS_REPLAY_FILENAME,
    ANALYSIS_SCRIPT_FILENAME,
    ANSWER_FILENAME,
    AgenticArm,
    EpisodeBudgets,
    EpisodeResult,
    parse_harbor_artifacts,
    requires_analysis_replay,
    verify_agentic_answer_trace,
)
from pydexpi_datalog.benchmark.contract import (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    SOURCE_CONCLUSION_VERDICTS,
    VERDICT_UNANSWERABLE,
)
from pydexpi_datalog.benchmark.dataset import load_question_manifest
from pydexpi_datalog.benchmark.rmso_eval import (
    materialize_preregistered_rmso_manifest,
)
from pydexpi_datalog.benchmark.rmso_faithfulness import (
    replay_result_witness,
    run_preregistered_faithfulness_gate,
)
from pydexpi_datalog.benchmark.runner import run_benchmark
from pydexpi_datalog.benchmark.souffle_arm import (
    PROGRAM_FILENAME,
    build_rmso_souffle_harbor_task,
    requires_executed_program,
    validate_faithfulness_program,
    verify_souffle_answer_trace,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "testdata" / "benchmark" / "rmso_eval_lock_v2.json"

INCLUDES = """\
.include "/input/graph_facts.dl"
.include "/input/graph_topology_semantics.dl"
"""

PROGRAMS = {
    "ha-e03-pump-p4713-retrieval": INCLUDES
    + """\
.decl result_witness(id:symbol)
.output result_witness
result_witness(X) :- node_label(X, "CentrifugalPump"), node_tag(X, "P-4713").
""",
    "nozzle": INCLUDES
    + """\
.decl nozzle(x:symbol)
nozzle(X) :- node_label(X, "Nozzle").
.decl attached(x:symbol)
attached(X) :- reference_edge(_, X, "sourceItem").
attached(X) :- reference_edge(_, X, "targetItem").
attached(X) :- reference_edge(_, X, "sourceNode").
attached(X) :- reference_edge(_, X, "targetNode").
.decl result_witness(id:symbol)
.output result_witness
result_witness(X) :- nozzle(X), !attached(X).
""",
    "valve": INCLUDES
    + """\
.decl valve(x:symbol)
valve(X) :- node_label(X, "BallValve").
valve(X) :- node_label(X, "ButterflyValve").
valve(X) :- node_label(X, "GlobeValve").
valve(X) :- node_label(X, "OperatedValve").
valve(X) :- node_label(X, "SwingCheckValve").
valve(X) :- node_label(X, "SpringLoadedGlobeSafetyValve").
.decl monitored(x:symbol)
.decl graph_reachable(x:symbol, y:symbol)
graph_reachable(X, Y) :- graph_edge(X, Y, _).
graph_reachable(X, Z) :- graph_edge(X, Y, _), graph_reachable(Y, Z).
monitored(X) :- node_label(S, "ProcessInstrumentationFunction"), graph_reachable(S, X).
.decl result_witness(id:symbol)
.output result_witness
result_witness(X) :- valve(X), !monitored(X).
""",
    "equipment": INCLUDES
    + """\
.decl allowed_attr(a:symbol)
allowed_attr("sourceItem"). allowed_attr("targetItem").
allowed_attr("sourceNode"). allowed_attr("targetNode").
allowed_attr("nodes"). allowed_attr("segments").
allowed_attr("connections"). allowed_attr("items").
allowed_attr("pipingNetworkSystems"). allowed_attr("nozzles").
.decl adjacent(x:symbol, y:symbol)
adjacent(X, Y) :- graph_edge_attribute(X, Y, _, "attr_name", A), allowed_attr(A).
adjacent(X, Y) :- graph_edge_attribute(Y, X, _, "attr_name", A), allowed_attr(A).
.decl connected(x:symbol, y:symbol)
connected(X, Y) :- adjacent(X, Y).
connected(X, Z) :- adjacent(X, Y), connected(Y, Z).
.decl pump(x:symbol)
pump(X) :- node_label(X, "CentrifugalPump").
pump(X) :- node_label(X, "ReciprocatingPump").
.decl equipment(x:symbol)
equipment(X) :- node_label(X, "PlateHeatExchanger").
equipment(X) :- node_label(X, "TubularHeatExchanger").
equipment(X) :- node_label(X, "Tank").
equipment(X) :- node_label(X, "ProcessColumn").
.decl pump_connected(x:symbol)
pump_connected(X) :- equipment(X), pump(P), connected(P, X).
.decl result_witness(id:symbol)
.output result_witness
result_witness(X) :- equipment(X), !pump_connected(X).
""",
}


def _program_for(question_id: str) -> str:
    if question_id.startswith("hq-nozzle-"):
        return PROGRAMS["nozzle"]
    if question_id.startswith("hq-valve-"):
        return PROGRAMS["valve"]
    if question_id.startswith("hq-equipment-"):
        return PROGRAMS["equipment"]
    return PROGRAMS[question_id]


def _persist_verifier_result(
    *, task_dir: Path, jobs_dir: Path, workspace: Path, names: tuple[str, ...]
) -> None:
    verifier_dir = jobs_dir / "trial-0" / "verifier"
    verifier_dir.mkdir(parents=True)
    checked = subprocess.run(
        [sys.executable, str(task_dir / "tests" / "test_outputs.py")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "INPUT_DIR": str(task_dir / "environment"),
            "WORKSPACE_DIR": str(workspace),
        },
    )
    (verifier_dir / "reward.txt").write_text(
        "1\n" if checked.returncode == 0 else "0\n", encoding="utf-8"
    )
    for name in names:
        source = workspace / name
        if source.exists():
            shutil.copyfile(source, verifier_dir / name)
    if checked.returncode != 0:
        raise AssertionError(checked.stderr)


class ScriptedRawXMLProvider:
    def __init__(self, expected: dict[str, tuple[str, tuple[str, ...]]]) -> None:
        self.expected = expected

    def run(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> EpisodeResult:
        question_id = task_dir.name.removeprefix("benchmark-")
        verdict, witness_ids = self.expected[question_id]
        workspace = jobs_dir / "workspace"
        workspace.mkdir(parents=True)
        if verdict == VERDICT_UNANSWERABLE:
            answer = {
                "verdict": verdict,
                "witness_ids": [],
                "posture": POSTURE_SOURCE_DATA_UNAVAILABLE,
                "answer_text": (
                    "Permission is not soundly decidable from monotone drawing facts; "
                    "provide the governing policy and exemptions."
                ),
                "support": {
                    "steps": [{
                        "id": "policy",
                        "kind": "policy_abstention",
                        "operation": (
                            "permission_or_defeasible_not_decidable_from_"
                            "monotone_drawing"
                        ),
                        "dependencies": [],
                    }],
                    "claims": [{"claim": "verdict", "step_ids": ["policy"]}],
                },
            }
            names = (ANSWER_FILENAME,)
        else:
            xml_path = task_dir / "environment" / "drawing.xml"
            replay = {"verdict": verdict, "witness_ids": list(witness_ids)}
            answer = {
                **replay,
                "posture": POSTURE_SOURCE_GROUNDED,
                "answer_text": "Scripted raw-XML dry-run result.",
                "support": {
                    "steps": [
                        {
                            "id": "scope",
                            "kind": "xml_scope",
                            "artifact": "drawing.xml",
                            "sha256": hashlib.sha256(xml_path.read_bytes()).hexdigest(),
                            "dependencies": [],
                        },
                        {
                            "id": "execution",
                            "kind": "python_execution",
                            "artifact": ANALYSIS_SCRIPT_FILENAME,
                            "input": "drawing.xml",
                            "output": ANALYSIS_REPLAY_FILENAME,
                            **replay,
                            "dependencies": ["scope"],
                        },
                    ],
                    "claims": [
                        {"claim": "verdict", "step_ids": ["execution"]},
                        *[
                            {
                                "claim": f"witness:{witness}",
                                "step_ids": ["execution"],
                            }
                            for witness in witness_ids
                        ],
                    ],
                },
            }
            (workspace / ANALYSIS_SCRIPT_FILENAME).write_text(
                "import json,sys,xml.etree.ElementTree as ET\n"
                "ET.parse(sys.argv[1])\n"
                f"print(json.dumps({replay!r}))\n",
                encoding="utf-8",
            )
            names = (
                ANSWER_FILENAME,
                ANALYSIS_SCRIPT_FILENAME,
                ANALYSIS_REPLAY_FILENAME,
            )
        (workspace / ANSWER_FILENAME).write_text(json.dumps(answer), encoding="utf-8")
        _persist_verifier_result(
            task_dir=task_dir, jobs_dir=jobs_dir, workspace=workspace, names=names
        )
        return parse_harbor_artifacts(jobs_dir)


class ScriptedSouffleProvider:
    def __init__(self, expected: dict[str, tuple[str, tuple[str, ...]]]) -> None:
        self.expected = expected

    def run(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> EpisodeResult:
        question_id = task_dir.name.removeprefix("benchmark-")
        expected_verdict, expected_ids = self.expected[question_id]
        workspace = jobs_dir / "workspace"
        workspace.mkdir(parents=True)
        if expected_verdict == VERDICT_UNANSWERABLE:
            answer = {
                "verdict": expected_verdict,
                "witness_ids": [],
                "posture": POSTURE_SOURCE_DATA_UNAVAILABLE,
                "answer_text": (
                    "Permission is not soundly decidable from monotone drawing facts; "
                    "provide the governing policy and exemptions."
                ),
                "support": {
                    "steps": [{
                        "id": "policy",
                        "kind": "policy_abstention",
                        "operation": (
                            "permission_or_defeasible_not_decidable_from_"
                            "monotone_drawing"
                        ),
                        "dependencies": [],
                    }],
                    "claims": [{"claim": "verdict", "step_ids": ["policy"]}],
                },
            }
            names = (ANSWER_FILENAME,)
        else:
            program = _program_for(question_id)
            graph_facts = json.loads(
                (task_dir / "environment" / "graph_facts.json").read_text()
            )
            actual_ids = replay_result_witness(program, graph_facts)
            assert actual_ids == tuple(sorted(expected_ids))
            facts = graph_facts["facts"]
            answer = {
                "verdict": expected_verdict,
                "witness_ids": list(actual_ids),
                "posture": POSTURE_SOURCE_GROUNDED,
                "answer_text": "Scripted local-Souffle dry-run result.",
                "support": {
                    "steps": [
                        {
                            "id": "scope",
                            "kind": "graph_scope",
                            "node_count": len(facts["nodes"]),
                            "edge_count": len(facts["edges"]),
                            "dependencies": [],
                        },
                        {
                            "id": "execution",
                            "kind": "souffle_execution",
                            "artifact": PROGRAM_FILENAME,
                            "relation": "result_witness",
                            "witness_ids": list(actual_ids),
                            "dependencies": ["scope"],
                        },
                    ],
                    "claims": [
                        {"claim": "verdict", "step_ids": ["execution"]},
                        *[
                            {
                                "claim": f"witness:{witness}",
                                "step_ids": ["execution"],
                            }
                            for witness in actual_ids
                        ],
                    ],
                },
            }
            (workspace / PROGRAM_FILENAME).write_text(program, encoding="utf-8")
            names = (ANSWER_FILENAME, PROGRAM_FILENAME)
        (workspace / ANSWER_FILENAME).write_text(json.dumps(answer), encoding="utf-8")
        _persist_verifier_result(
            task_dir=task_dir, jobs_dir=jobs_dir, workspace=workspace, names=names
        )
        return parse_harbor_artifacts(jobs_dir)


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_complete_nine_entry_scripted_provider_and_local_souffle_dry_run(
    tmp_path: Path,
) -> None:
    manifest = materialize_preregistered_rmso_manifest(
        LOCK_PATH, tmp_path / "rmso-manifest.json"
    )
    dataset = load_question_manifest(manifest)
    expected = {
        question.question_id: (
            question.ground_truth.verdict,
            question.ground_truth.witness_ids,
        )
        for question in dataset.questions
    }
    budgets = EpisodeBudgets(
        max_turns=64,
        max_commands=128,
        max_output_tokens=8192,
        agent_timeout_sec=300.0,
        verifier_timeout_sec=60.0,
    )
    arm_a = AgenticArm(
        runner=ScriptedRawXMLProvider(expected),
        budgets=budgets,
        model_name="scripted-dry-run",
        require_analysis_replay=requires_analysis_replay,
        analysis_trace_gate=verify_agentic_answer_trace,
    )
    arm_b = AgenticArm(
        runner=ScriptedSouffleProvider(expected),
        budgets=budgets,
        model_name="scripted-dry-run",
        arm_label="b-souffle",
        task_builder=build_rmso_souffle_harbor_task,
        require_executed_program=requires_executed_program,
        program_validator=validate_faithfulness_program,
        program_faithfulness_gate=lambda program, question: (
            run_preregistered_faithfulness_gate(program, question.question_id)
        ),
        answer_trace_gate=verify_souffle_answer_trace,
    )

    report_a = run_benchmark(
        manifest_path=manifest, arm=arm_a, output_dir=tmp_path / "arm-a-report"
    )
    report_b = run_benchmark(
        manifest_path=manifest, arm=arm_b, output_dir=tmp_path / "arm-b-report"
    )

    assert report_a["totals"] == {"questions": 9, "passed": 9, "failed": 0}
    assert report_b["totals"] == {"questions": 9, "passed": 9, "failed": 0}
    for report in (report_a, report_b):
        assert all(
            episode["usage"]["audit_trace"]["trace_safe"] is True
            for episode in report["episodes"]
        )
    assert all(
        "faithfulness_gate" in episode["usage"]
        for episode in report_b["episodes"][1:7]
    )
