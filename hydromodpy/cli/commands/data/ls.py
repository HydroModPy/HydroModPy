"""``hmp data ls`` - list artefacts indexed in the workspace cache."""

from __future__ import annotations

import argparse

from hydromodpy.cli.helpers import resolve_workspace

NAME: str = "ls"
HELP: str = "List artefacts indexed in the workspace cache"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--variable", default=None, help="Filter by variable")
    parser.add_argument("--provider", default=None, help="Filter by provider")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    if not db_path.exists():
        print(f"  (no cache found at {db_path})")
        return

    with DataCatalogDuckDB(db_path) as catalog:
        df = catalog.list_entries(
            variable=args.variable,
            source=args.provider,
        )
        if df.empty:
            print("  (empty cache - drop files in <variable>_custom/ then run 'hmp run')")
            return
        cols = [c for c in ("variable", "source", "station_id", "file_path") if c in df.columns]
        print(df[cols].to_string(index=False))
