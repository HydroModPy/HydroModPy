"""``hmp data remove`` - thin wrapper around :func:`hydromodpy.remove_data_entries`."""

from __future__ import annotations

import argparse

NAME: str = "remove"
HELP: str = "Remove cache entries for a variable/provider/station"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--variable", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--station-id", default=None, dest="station_id")
    parser.add_argument("--delete-files", action="store_true", help="Also delete files on disk")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.data import remove_data_entries

    n = remove_data_entries(
        args.workspace,
        variable=args.variable,
        provider=args.provider,
        station_id=args.station_id,
        delete_files=args.delete_files,
    )
    print(f"  Removed {n} entry(ies).")
