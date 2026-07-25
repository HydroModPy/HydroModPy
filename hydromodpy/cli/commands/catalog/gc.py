"""``hmp catalog gc`` - the single workspace maintenance verb.

Plans by default; ``--apply`` purges expired trash, quarantines orphan
stores, replays interrupted purges, marks stale running runs failed, cleans
orphan caches and tmp parquet, and compacts DuckDB + Zarr (the absorbed
``vacuum``). An orphan store is never destroyed: it is moved to
``<project>/.hmp/trash/<stamp>/`` because it may be the last copy of a run.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli._conventions import format_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_OK

NAME: str = "gc"
HELP: str = (
    "Maintenance: expire trash, quarantine orphan stores, replay purges, compact DuckDB + Zarr"
)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[format_parser()])
    parser.add_argument(
        "-w",
        "--workspace",
        default=None,
        help="Workspace root or project directory (default: auto-detect from cwd)",
    )
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

    if args.format == "json":
        import json

        print(json.dumps(result, default=str))
        sys.exit(EXIT_OK)

    label = "[plan] " if dry_run else ""
    for key, items in result["plan"].items():
        print(f"{label}{key}: {len(items)} candidate(s)")
        for item in items:
            print(f"  - {item}")
        if key == "orphan_stores" and items:
            print("  (moved to <project>/.hmp/trash/<stamp>/, never deleted)")
    if dry_run:
        print("\nPlan only. Re-run with --apply to execute.")
        sys.exit(EXIT_OK)
    print()
    print("Summary:")
    for key, value in result["summary"].items():
        print(f"  {key}: {value}")
    sys.exit(EXIT_OK)
