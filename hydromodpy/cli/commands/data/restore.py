"""``hmp data restore`` - restore a cache archive into the workspace."""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.helpers import resolve_workspace

NAME: str = "restore"
HELP: str = "Restore a cache archive into the workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("input", help="Archive produced by 'hmp data archive'")
    parser.add_argument("--workspace", default=None)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.data_freeze import restore_archive

    workspace = resolve_workspace(args.workspace)
    src = Path(args.input).expanduser().resolve()
    dest = workspace / "data" / "imported"
    restore_archive(src, dest)
    print(f"  Restored {src} into {dest}")
