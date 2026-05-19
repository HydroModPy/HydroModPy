"""``hmp data check`` - thin wrapper around :func:`hydromodpy.check_data_cache`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_DATA_ERROR

NAME: str = "check"
HELP: str = "Validate the drag-and-drop <variable>_custom/ folders without ingesting"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None, help="Workspace root")
    parser.add_argument(
        "--variable", default=None, help="Restrict to one variable (e.g. piezometry)"
    )
    parser.add_argument("--fix", action="store_true", help="Attempt to repair stale entries")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    result = hmp.check_data_cache(args.workspace, variable=args.variable, fix=args.fix)
    if result["fix_summary"] is not None:
        s = result["fix_summary"]
        print(
            f"  catalog: dropped {s['dropped']} stale entries, refreshed {s['refreshed']} mtimes."
        )
    issues = result["issues"]
    if not issues:
        print(f"  OK: no schema issues in {result['workspace']}")
        return
    print(f"  {len(issues)} issue(s) found:")
    for path, msg in issues:
        print(f"    {path}: {msg}")
    sys.exit(EXIT_DATA_ERROR)
