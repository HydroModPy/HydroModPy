"""``hmp data archive`` - thin wrapper around :func:`hydromodpy.archive_data_cache`."""

from __future__ import annotations

import argparse

NAME: str = "archive"
HELP: str = "Archive the cache (data + lockfile) to a portable file"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("output", help="Destination archive (.tar / .tar.gz / .tar.zst)")
    parser.add_argument("--workspace", default=None)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.data import archive_data_cache

    dest = archive_data_cache(args.output, workspace=args.workspace)
    print(f"  Archived cache to {dest}")
