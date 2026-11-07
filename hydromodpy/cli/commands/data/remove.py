"""``hmp data remove`` - thin wrapper around :func:`hydromodpy.remove_data_entries`."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    confirm_parser,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import confirm
from hydromodpy.cli.output import emit

NAME: str = "remove"
HELP: str = "Remove cache entries for a variable/provider/station"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[
            workspace_parser(),
            confirm_parser(),
            dry_run_parser(),
            format_parser(),
            verbosity_parser(),
        ],
        epilog="Example:\n  hmp data remove --variable precipitation --provider sim2 --delete-files -y",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--variable", default=None, help="Remove the entries of this variable")
    parser.add_argument("--provider", default=None, help="Remove the entries of this provider")
    parser.add_argument(
        "--station-id",
        default=None,
        dest="station_id",
        help="Remove the entries of this station",
    )
    parser.add_argument("--delete-files", action="store_true", help="Also delete files on disk")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.helpers import resolve_workspace
    from hydromodpy.data.request.cache_verbs import remove_data_entries

    if not args.dry_run:
        confirm(args, "Remove these cache entries?", doing="remove cache entries")
    n = remove_data_entries(
        resolve_workspace(args.workspace),
        variable=args.variable,
        provider=args.provider,
        station_id=args.station_id,
        delete_files=args.delete_files,
        dry_run=args.dry_run,
    )
    verb = "Would remove" if args.dry_run else "Removed"
    emit(
        args,
        "data remove",
        {"applied": not args.dry_run, "removed": n},
        table=lambda: print(f"  {verb} {n} entry(ies)."),
    )
