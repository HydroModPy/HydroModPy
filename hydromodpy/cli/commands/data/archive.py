"""``hmp data archive`` - archive the workspace cache to a portable file."""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.helpers import resolve_workspace

NAME: str = "archive"
HELP: str = "Archive the cache (data + lockfile) to a portable file"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("output", help="Destination archive (.tar / .tar.gz / .tar.zst)")
    parser.add_argument("--workspace", default=None)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.data_freeze import archive_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    dest = Path(args.output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    print(f"  Archived cache to {dest}")
