"""``hmp catalog gc`` - the single workspace maintenance verb.

Plans by default; ``--apply`` purges expired trash, removes orphan stores,
replays interrupted purges, marks stale running runs failed, cleans orphan
caches and tmp parquet, and compacts DuckDB + Zarr (the absorbed ``vacuum``).
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_OK

NAME: str = "gc"
HELP: str = "Maintenance: expire trash, drop orphan stores, replay purges, compact DuckDB + Zarr"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None, help="Workspace root")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the plan and free resources (default: print the plan only)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import gc

    # Safe by default: planner unless --apply (mirrors `audit prune`,
    # the inverse of the old destructive-by-default --dry-run opt-in).
    dry_run = not args.apply
    try:
        result = gc(args.workspace, dry_run=dry_run)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    label = "[plan] " if dry_run else ""
    for key, items in result["plan"].items():
        print(f"{label}{key}: {len(items)} candidate(s)")
        for item in items:
            print(f"  - {item}")
    if dry_run:
        print("\nPlan only. Re-run with --apply to execute.")
        sys.exit(EXIT_OK)
    print()
    print("Summary:")
    for key, value in result["summary"].items():
        print(f"  {key}: {value}")
    sys.exit(EXIT_OK)
