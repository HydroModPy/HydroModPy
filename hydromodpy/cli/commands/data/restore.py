"""``hmp data restore`` - thin wrapper around :func:`hydromodpy.restore_data_cache`."""

from __future__ import annotations

import argparse

NAME: str = "restore"
HELP: str = "Restore a cache archive into the workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("input", help="Archive produced by 'hmp data archive'")
    parser.add_argument("--workspace", default=None)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.data import restore_data_cache

    src = args.input
    dest = restore_data_cache(src, workspace=args.workspace)
    print(f"  Restored {src} into {dest}")
