from __future__ import annotations

import argparse
from pathlib import Path

from .compile_rule import run_compile_rule
from .dry_run import run_dry_run
from .export_facts import run_export_facts
from .review_only import run_review_only
from .verify_raw_fixture import run_verify_raw_fixture
from .verify_suite import run_verify_suite


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pydexpi-datalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser(
        "dry-run",
        help="Validate a manifest and produce a structural summary for one DEXPI source.",
    )
    dry_run.add_argument("manifest", type=Path, help="Path to a JSON manifest file.")

    review_only = subparsers.add_parser(
        "review-only",
        help="Evaluate one rule pack and persist raw findings with evidence only.",
    )
    review_only.add_argument(
        "manifest", type=Path, help="Path to a JSON manifest file."
    )

    export_facts = subparsers.add_parser(
        "export-facts",
        help="Export graph-mirrored base facts from one DEXPI XML fixture.",
    )
    export_facts.add_argument("dexpi_xml", type=Path, help="Path to a DEXPI XML file.")
    export_facts.add_argument(
        "--fixture-id",
        required=True,
        help="Stable fixture identifier used for persisted output.",
    )
    export_facts.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where exported fact artifacts will be written.",
    )

    compile_rule = subparsers.add_parser(
        "compile-rule",
        help="Validate one YAML discharge rule and compile it to Souffle-style Datalog.",
    )
    compile_rule.add_argument("rule_yaml", type=Path, help="Path to a YAML rule file.")
    compile_rule.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where compiled rule artifacts will be written.",
    )

    verify_suite = subparsers.add_parser(
        "verify-suite",
        help="Run the tracer-bullet verifier over a checked-in fixture suite.",
    )
    verify_suite.add_argument(
        "suite_manifest", type=Path, help="Path to a verifier suite manifest."
    )
    verify_suite.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where verifier output artifacts will be written.",
    )

    verify_raw_fixture = subparsers.add_parser(
        "verify-raw-fixture",
        help="Run the tracer-bullet verifier from one raw DEXPI XML input.",
    )
    verify_raw_fixture.add_argument(
        "dexpi_xml", type=Path, help="Path to a raw DEXPI XML input fixture."
    )
    verify_raw_fixture.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where persisted verifier artifacts will be written.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "dry-run":
        return run_dry_run(args.manifest)
    if args.command == "review-only":
        return run_review_only(args.manifest)
    if args.command == "export-facts":
        return run_export_facts(
            dexpi_xml_path=args.dexpi_xml,
            fixture_id=args.fixture_id,
            output_dir=args.output_dir,
        )
    if args.command == "compile-rule":
        return run_compile_rule(rule_yaml_path=args.rule_yaml, output_dir=args.output_dir)
    if args.command == "verify-suite":
        return run_verify_suite(
            suite_manifest_path=args.suite_manifest,
            output_dir=args.output_dir,
        )
    if args.command == "verify-raw-fixture":
        return run_verify_raw_fixture(
            dexpi_xml_path=args.dexpi_xml,
            output_dir=args.output_dir,
        )

    parser.error(f"unsupported command: {args.command}")
    return 2
