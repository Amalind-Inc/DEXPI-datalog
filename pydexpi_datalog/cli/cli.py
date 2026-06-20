from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pydexpi-datalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser(
        "dry-run",
        help="Validate a manifest and produce a structural summary for one DEXPI source.",
    )
    dry_run.add_argument("manifest", type=Path, help="Path to a JSON manifest file.")

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

    export_corpus = subparsers.add_parser(
        "export-corpus",
        help="Export graph-mirrored base facts for a DEXPI XML fixture corpus.",
    )
    export_corpus.add_argument(
        "fixture_root", type=Path, help="Directory containing DEXPI XML fixtures."
    )
    export_corpus.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where corpus fact artifacts and summary will be written.",
    )

    derive_graph_semantics = subparsers.add_parser(
        "derive-graph-semantics",
        help="Derive graph semantic predicates from graph-mirrored base facts.",
    )
    derive_graph_semantics.add_argument(
        "graph_facts", type=Path, help="Path to a graph_facts.json artifact."
    )
    derive_graph_semantics.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where derived graph semantics artifacts will be written.",
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

    draft_logic_request = subparsers.add_parser(
        "draft-logic-request",
        help="Draft a BYOK logic request artifact without making the LLM the answer source.",
    )
    draft_logic_request.add_argument("logic_request", help="Natural-language logic request.")
    draft_logic_request.add_argument(
        "--derived-graph-semantics",
        type=Path,
        help="Path to a derived_graph_semantics.dl artifact used for optional source selection.",
    )
    draft_logic_request.add_argument(
        "--source-id",
        help="Known source graph object ID for the logic request.",
    )
    draft_logic_request.add_argument(
        "--source-tag",
        help="Human-facing source equipment tag for the logic request.",
    )
    draft_logic_request.add_argument(
        "--source-proteus-id",
        help="Source Proteus ID for the logic request.",
    )
    draft_logic_request.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where logic-request artifacts will be written.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "dry-run":
        from ..workflow.dry_run import run_dry_run

        return run_dry_run(args.manifest)
    if args.command == "export-facts":
        from ..export.pipeline import run_export_facts

        return run_export_facts(
            dexpi_xml_path=args.dexpi_xml,
            fixture_id=args.fixture_id,
            output_dir=args.output_dir,
        )
    if args.command == "export-corpus":
        from ..export.pipeline import run_export_corpus

        return run_export_corpus(
            fixture_root=args.fixture_root,
            output_dir=args.output_dir,
        )
    if args.command == "derive-graph-semantics":
        from ..semantics.derive_graph_semantics import run_derive_graph_semantics

        return run_derive_graph_semantics(
            graph_facts_path=args.graph_facts,
            output_dir=args.output_dir,
        )
    if args.command == "verify-suite":
        from ..verification.verify_suite import run_verify_suite

        return run_verify_suite(
            suite_manifest_path=args.suite_manifest,
            output_dir=args.output_dir,
        )
    if args.command == "verify-raw-fixture":
        from ..verification.verify_raw_fixture import run_verify_raw_fixture

        return run_verify_raw_fixture(
            dexpi_xml_path=args.dexpi_xml,
            output_dir=args.output_dir,
        )
    if args.command == "draft-logic-request":
        from ..llm.logic_requests import run_draft_logic_request

        return run_draft_logic_request(
            logic_request=args.logic_request,
            derived_graph_semantics_path=args.derived_graph_semantics,
            source_id=args.source_id,
            source_tag=args.source_tag,
            source_proteus_id=args.source_proteus_id,
            output_dir=args.output_dir,
        )

    parser.error(f"unsupported command: {args.command}")
    return 2
