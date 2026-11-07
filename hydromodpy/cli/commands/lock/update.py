"""``hmp lock update`` - scan the cache and write ``hydromodpy.lock``."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import add_destination, format_parser, workspace_parser
from hydromodpy.cli.output import emit

NAME: str = "update"
HELP: str = "Scan the cache and write or update hydromodpy.lock"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp lock update --project path/to/project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", default=None, help="Project root owning hydromodpy.lock")
    add_destination(parser, help="Destination lockfile", metavar="FILE")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.project.lock import lock_update

    written = lock_update(args.workspace, project=args.project, output=args.to)
    emit(
        args,
        "lock update",
        {"path": written},
        table=lambda: print(f"  Lockfile written: {written}"),
    )
