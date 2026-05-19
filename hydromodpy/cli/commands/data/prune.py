"""``hmp data prune`` - drop cache entries older than N days."""

from __future__ import annotations

import argparse

from hydromodpy.cli.helpers import resolve_workspace

NAME: str = "prune"
HELP: str = "Drop cache entries older than N days"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None)
    parser.add_argument(
        "--older-than", type=int, default=30, help="Age threshold in days (default: 30)"
    )
    parser.add_argument("--delete-files", action="store_true")
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
        n = catalog.prune_older_than(
            days=args.older_than,
            delete_files=args.delete_files,
        )
    print(f"  Pruned {n} entry(ies) older than {args.older_than} day(s).")
