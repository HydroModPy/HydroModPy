"""``hmp catalog vacuum`` - thin wrapper around :func:`hydromodpy.vacuum`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "vacuum"
HELP: str = "Compact DuckDB catalogs (CHECKPOINT) and consolidate Zarr metadata"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None, help="Workspace root")
    parser.add_argument("--catalog", action="store_true", help="Only CHECKPOINT catalog.duckdb")
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Only CHECKPOINT data/cache.duckdb and consolidate Zarr stores",
    )
    parser.add_argument("--all", action="store_true", help="Run every compaction step (default)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    if args.all or (not args.catalog and not args.cache):
        do_catalog, do_cache = True, True
    else:
        do_catalog, do_cache = args.catalog, args.cache

    result = hmp.vacuum(args.workspace, catalog=do_catalog, cache=do_cache)
    print("Vacuum summary:")
    for key, value in result["counts"].items():
        print(f"  {key}: {value}")
    sys.exit(EXIT_OK)
