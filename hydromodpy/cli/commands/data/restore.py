"""``hmp data restore`` - thin wrapper around :func:`hydromodpy.restore_data_cache`."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import apply_verbosity
from hydromodpy.cli.output import emit

NAME: str = "restore"
HELP: str = "Restore a cache archive into the workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp data restore data-cache.tar.gz",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="Archive produced by 'hmp data archive'")
    add_destination(
        parser,
        help="Folder to restore into (default: data/imported of the workspace)",
        metavar="DIR",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.data import restore_data_cache

    src = args.input
    dest = restore_data_cache(src, workspace=args.workspace, to=args.to)
    emit(
        args,
        "data restore",
        {"source": src, "path": dest},
        table=lambda: print(f"  Restored {src} into {dest}"),
    )
