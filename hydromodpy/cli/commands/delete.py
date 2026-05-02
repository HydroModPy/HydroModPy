"""``hmp delete`` - delete a simulation from the catalog and the Zarr store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import (
    EXIT_NOT_FOUND,
    EXIT_USER_ABORT,
    find_catalog_root,
    resolve_sim_id,
)

NAME: str = "delete"
HELP: str = "Delete a simulation (DuckDB row + Zarr store)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "sim_id",
        help="Full sim_id, unique prefix, or simulation name",
    )
    parser.add_argument(
        "--workspace", default=None, help="Project catalog root (default: auto-detect)"
    )
    parser.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    parser.add_argument(
        "--keep-storage",
        action="store_true",
        help="Drop catalog rows but keep the Zarr store and Parquet directory on disk",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not (workspace_root / "hydromodpy.duckdb").exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    with SimulationCatalog(workspace_root) as catalog:
        sid = resolve_sim_id(catalog, args.sim_id)
        sim = catalog[sid]
        label = sim.name or sid

        if not args.yes:
            if not sys.stdin.isatty():
                print(
                    "Refusing to delete without -y in non-interactive mode.",
                    file=sys.stderr,
                )
                sys.exit(EXIT_USER_ABORT)
            try:
                resp = (
                    input(f"Delete simulation {label} ({sid}) and its Zarr store? [y/N] ")
                    .strip()
                    .lower()
                )
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.", file=sys.stderr)
                sys.exit(EXIT_USER_ABORT)
            if resp not in {"y", "yes"}:
                print("Aborted.", file=sys.stderr)
                sys.exit(EXIT_USER_ABORT)

        catalog.delete(sid, remove_storage=not args.keep_storage)
        print(f"Deleted simulation {label}")
