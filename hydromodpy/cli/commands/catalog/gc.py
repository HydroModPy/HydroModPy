"""``hmp catalog gc`` - thin wrapper around :func:`hydromodpy.gc`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_OK

NAME: str = "gc"
HELP: str = "Garbage-collect orphan caches, tmp parquet, and stale running simulations"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None, help="Workspace root")
    parser.add_argument("--dry-run", action="store_true", help="List candidates only")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import gc

    try:
        result = gc(args.workspace, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    label = "[dry-run] " if args.dry_run else ""
    for key, items in result["plan"].items():
        print(f"{label}{key}: {len(items)} candidate(s)")
        for item in items:
            print(f"  - {item}")
    if args.dry_run:
        sys.exit(EXIT_OK)
    print()
    print("Summary:")
    for key, value in result["summary"].items():
        print(f"  {key}: {value}")
    sys.exit(EXIT_OK)
