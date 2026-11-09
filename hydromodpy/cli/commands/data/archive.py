"""``hmp data archive`` - thin wrapper around :func:`hydromodpy.data.request.cache_verbs.archive_data_cache`."""

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
HELP: str = "Archive the cache (files, sidecars and lockfile) to a portable file"


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
    from hydromodpy.cli.helpers import resolve_workspace
    from hydromodpy.data.request.cache_verbs import archive_data_cache

    dest = archive_data_cache(args.to, workspace_root=resolve_workspace(args.workspace))
    emit(args, "data archive", {"path": dest}, table=lambda: print(f"  Archived cache to {dest}"))
