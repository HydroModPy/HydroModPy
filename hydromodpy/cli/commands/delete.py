"""``hmp delete`` - delete a simulation from the catalog and the Zarr store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

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

        result = delete_simulation_artifacts(catalog, sid, remove_storage=not args.keep_storage)
        for removed_path in result["removed_paths"]:
            print(f"  removed: {removed_path}")
        print(f"Deleted simulation {label}")


def delete_simulation_artifacts(
    catalog: Any,
    sid: str,
    *,
    remove_storage: bool = True,
) -> dict[str, object]:
    """Delete one simulation and return a small storage summary."""
    zarr_path = catalog.zarr_path_for(sid)
    parquet_dir = catalog.parquet_dir_for(sid)
    existing_paths = [path for path in (zarr_path, parquet_dir) if path.exists()]
    freed_bytes = sum(_path_size(path) for path in existing_paths) if remove_storage else 0

    catalog.delete(sid, remove_storage=remove_storage)

    return {
        "sim_id": sid,
        "freed_bytes": freed_bytes,
        "removed_paths": [str(path) for path in existing_paths] if remove_storage else [],
    }


def _path_size(path: Path) -> int:
    """Return the recursive file size for *path* in bytes."""
    if not path.exists():
        return 0
    try:
        if path.is_file():
            return int(path.stat().st_size)
    except OSError:
        return 0

    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += int(child.stat().st_size)
            except OSError:
                continue
    except OSError:
        return total
    return total
