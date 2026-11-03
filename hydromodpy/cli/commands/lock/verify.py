"""``hmp lock verify`` - verify the data cache matches the lockfile."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_VALIDATION
from hydromodpy.cli.output import emit

NAME: str = "verify"
HELP: str = "Verify the cache matches the lockfile"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp lock verify --project path/to/project --strict",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", default=None, help="Project root owning hydromodpy.lock")
    parser.add_argument("--lockfile", default=None, help="Explicit lockfile path")
    parser.add_argument("--strict", action="store_true", help="Strict input verification")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.dev import lock_verify

    result = lock_verify(
        args.workspace, project=args.project, lockfile=args.lockfile, strict=args.strict
    )
    label = "ERROR" if args.strict else "WARNING"
    mismatches = result["mismatches"]
    if result["schema_diverged"]:
        print(
            f"  {label}: configuration schema has changed since freeze "
            f"(lockfile={result['locked_schema'][:12]}..., "
            f"current={result['current_schema'][:12]}...).",
            file=sys.stderr,
        )

    def table() -> None:
        if result["ok"]:
            print("  OK: catalog matches lockfile")
            return
        print(f"  {label}: {len(mismatches)} mismatch(es):")
        for mismatch in mismatches:
            print(
                f"    [{mismatch.kind}] {mismatch.variable}/{mismatch.source}/"
                f"{mismatch.station_id} -> {mismatch.path}"
            )

    emit(args, "lock verify", result, table=table)
    if not result["ok"] or (args.strict and result["schema_diverged"]):
        sys.exit(EXIT_VALIDATION)
