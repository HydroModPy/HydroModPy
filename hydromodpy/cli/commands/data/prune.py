"""``hmp data prune`` - thin wrapper around :func:`hydromodpy.prune_data_cache`."""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import verbosity_parser
from hydromodpy.cli.helpers import apply_verbosity

NAME: str = "prune"
HELP: str = "Drop cache entries older than N days"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[verbosity_parser()],
        epilog="Example:\n  hmp data prune --older-than 90 --delete-files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", default=None, help="Workspace holding the data cache")
    parser.add_argument(
        "--older-than", type=int, default=30, help="Age threshold in days (default: 30)"
    )
    parser.add_argument("--delete-files", action="store_true", help="Also delete the files on disk")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.data import prune_data_cache

    n = prune_data_cache(
        args.workspace, older_than_days=args.older_than, delete_files=args.delete_files
    )
    print(f"  Pruned {n} entry(ies) older than {args.older_than} day(s).")
