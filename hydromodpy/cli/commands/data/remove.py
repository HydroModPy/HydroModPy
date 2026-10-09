"""``hmp data remove`` - thin wrapper around :func:`hydromodpy.remove_data_entries`."""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import verbosity_parser
from hydromodpy.cli.helpers import apply_verbosity

NAME: str = "remove"
HELP: str = "Remove cache entries for a variable/provider/station"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[verbosity_parser()],
        epilog="Example:\n  hmp data remove --variable precipitation --provider sim2 --delete-files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", default=None, help="Workspace holding the data cache")
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
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.data import remove_data_entries

    n = remove_data_entries(
        args.workspace,
        variable=args.variable,
        provider=args.provider,
        station_id=args.station_id,
        delete_files=args.delete_files,
    )
    print(f"  Removed {n} entry(ies).")
