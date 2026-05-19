"""``hmp data remove`` - remove cache entries for a variable/provider/station."""

from __future__ import annotations

import argparse

from hydromodpy.cli.helpers import resolve_workspace

NAME: str = "remove"
HELP: str = "Remove cache entries for a variable/provider/station"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--variable", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--station-id", default=None, dest="station_id")
    parser.add_argument(
        "--delete-files",
        action="store_true",
        help="Also delete the underlying files on disk",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    if not db_path.exists():
        print(f"  (no cache at {db_path})")
        return
    with DataCatalogDuckDB(db_path) as catalog:
        n = catalog.invalidate(
            variable=args.variable,
            source=args.provider,
            station_id=args.station_id,
            delete_files=args.delete_files,
        )
    print(f"  Removed {n} entry(ies).")
