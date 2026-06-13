from __future__ import annotations

import argparse
from pathlib import Path

from .dry_run import run_dry_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pydexpi-datalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser(
        "dry-run",
        help="Validate a manifest and produce a structural summary for one DEXPI source.",
    )
    dry_run.add_argument("manifest", type=Path, help="Path to a JSON manifest file.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "dry-run":
        return run_dry_run(args.manifest)

    parser.error(f"unsupported command: {args.command}")
    return 2
