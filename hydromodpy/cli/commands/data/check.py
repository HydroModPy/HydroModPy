"""``hmp data check`` - thin wrapper around :func:`hydromodpy.check_data_cache`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_VALIDATION
from hydromodpy.cli.output import emit

NAME: str = "check"
HELP: str = "Validate the custom files in data/<variable>/ without ingesting"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Examples:\n  hmp data check\n  hmp data check --variable dem --fix",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--variable", default=None, help="Restrict to one variable (e.g. piezometry)"
    )
    parser.add_argument("--fix", action="store_true", help="Attempt to repair stale entries")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.helpers import resolve_workspace
    from hydromodpy.data.request.cache_verbs import check_data_cache

    result = check_data_cache(
        resolve_workspace(args.workspace), variable=args.variable, fix=args.fix
    )
    issues = result["issues"]

    def table() -> None:
        if result["fix_summary"] is not None:
            fixed = result["fix_summary"]
            print(
                f"  catalog: dropped {fixed['dropped']} stale entries, "
                f"refreshed {fixed['refreshed']} mtimes."
            )
        if not issues:
            print(f"  OK: no schema issues in {result['workspace']}")
            return
        print(f"  {len(issues)} issue(s) found:")
        for path, message in issues:
            print(f"    {path}: {message}")

    emit(
        args,
        "data check",
        {
            "workspace": result["workspace"],
            "fix_summary": result["fix_summary"],
            "issues": [{"path": path, "message": message} for path, message in issues],
        },
        table=table,
    )
    if issues:
        sys.exit(EXIT_VALIDATION)
