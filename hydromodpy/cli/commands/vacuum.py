"""``hmp vacuum`` - compact DuckDB catalogs and Zarr metadata.

Two compaction passes:

* DuckDB ``CHECKPOINT`` on every catalog file detected in the workspace
  (per-project ``catalog.duckdb``) and on the shared ``data/cache.duckdb``;
* ``zarr.consolidate_metadata`` on every per-simulation Zarr store still on
  disk in directory form (``.zarr/``). Packed stores (``.zarr.zip``) are
  already consolidated at write time.

The selectors ``--catalog``, ``--cache``, ``--all`` (default) gate which
groups run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_OK, resolve_workspace
from hydromodpy.core.state.paths import CATALOG_FILENAME

NAME: str = "vacuum"
HELP: str = "Compact DuckDB catalogs (CHECKPOINT) and consolidate Zarr metadata"

_DATA_CACHE_FILENAME = "cache.duckdb"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: ~/hydromodpy)",
    )
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="Only CHECKPOINT per-project catalog.duckdb files",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Only CHECKPOINT data/cache.duckdb and consolidate Zarr stores",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run every compaction step (default behavior when no flag is set)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    workspace = resolve_workspace(args.workspace)

    do_catalog, do_cache = _resolve_flags(args)

    counts: dict[str, int] = {
        "catalog_checkpoints": 0,
        "cache_checkpoints": 0,
        "zarr_consolidated": 0,
    }

    if do_catalog:
        counts["catalog_checkpoints"] = _checkpoint_catalogs(workspace)
    if do_cache:
        counts["cache_checkpoints"] = _checkpoint_data_cache(workspace)
        counts["zarr_consolidated"] = _consolidate_zarr_stores(workspace)

    print("Vacuum summary:")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    sys.exit(EXIT_OK)


def _resolve_flags(args: argparse.Namespace) -> tuple[bool, bool]:
    flag_all = bool(getattr(args, "all", False))
    flag_catalog = bool(getattr(args, "catalog", False))
    flag_cache = bool(getattr(args, "cache", False))

    if flag_all or (not flag_catalog and not flag_cache):
        return True, True
    return flag_catalog, flag_cache


def _iter_catalog_files(workspace: Path) -> list[Path]:
    catalogs: list[Path] = []
    candidate = workspace / CATALOG_FILENAME
    if candidate.is_file():
        catalogs.append(candidate)
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            if not entry.is_dir():
                continue
            cat = entry / CATALOG_FILENAME
            if cat.is_file():
                catalogs.append(cat)
    return catalogs


def _checkpoint_catalogs(workspace: Path) -> int:
    import duckdb

    count = 0
    for catalog_path in _iter_catalog_files(workspace):
        try:
            conn = duckdb.connect(str(catalog_path))
            try:
                conn.execute("CHECKPOINT")
            finally:
                conn.close()
            count += 1
            print(f"  CHECKPOINT {catalog_path}")
        except duckdb.Error as exc:
            print(f"  WARN {catalog_path}: {exc}", file=sys.stderr)
    return count


def _checkpoint_data_cache(workspace: Path) -> int:
    import duckdb

    cache_path = workspace / "data" / _DATA_CACHE_FILENAME
    if not cache_path.is_file():
        return 0
    try:
        conn = duckdb.connect(str(cache_path))
        try:
            conn.execute("CHECKPOINT")
        finally:
            conn.close()
        print(f"  CHECKPOINT {cache_path}")
        return 1
    except duckdb.Error as exc:
        print(f"  WARN {cache_path}: {exc}", file=sys.stderr)
        return 0


def _iter_zarr_dirs(workspace: Path) -> list[Path]:
    """Find every ``.zarr/`` directory inside a project's ``simulations/``."""
    zarr_dirs: list[Path] = []
    for sim_dir in workspace.rglob("simulations"):
        if not sim_dir.is_dir():
            continue
        for entry in sorted(sim_dir.iterdir()):
            if entry.is_dir() and entry.suffix == ".zarr":
                zarr_dirs.append(entry)
    return zarr_dirs


def _consolidate_zarr_stores(workspace: Path) -> int:
    try:
        import zarr  # noqa: F401
    except ImportError:
        return 0

    from hydromodpy.results.zarr_store import SimulationZarr

    count = 0
    for zarr_dir in _iter_zarr_dirs(workspace):
        try:
            sz = SimulationZarr(zarr_dir)
            try:
                sz.consolidate_metadata()
            finally:
                sz.close()
            count += 1
            print(f"  consolidate {zarr_dir}")
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  WARN {zarr_dir}: {exc}", file=sys.stderr)
    return count


__all__ = ("NAME", "HELP", "register", "run")
