"""``hmp data archive`` - thin wrapper around :func:`hydromodpy.archive_data_cache`."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.output import emit

NAME: str = "archive"
HELP: str = "Archive the cache (data + lockfile) to a portable file"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp data archive --to data-cache.tar.gz",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_destination(
        parser,
        help="Destination archive (.tar / .tar.gz / .tar.zst)",
        required=True,
        metavar="FILE",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.data import archive_data_cache

    dest = archive_data_cache(args.to, workspace=args.workspace)
    emit(args, "data archive", {"path": dest}, table=lambda: print(f"  Archived cache to {dest}"))
