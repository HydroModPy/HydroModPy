"""``hmp delete`` - delete a simulation from the catalog and the Zarr store."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from hydromodpy._cli.helpers import (
    EXIT_NOT_FOUND,
    EXIT_USER_ABORT,
    find_workspace_root,
    resolve_sim_id,
)

NAME = "delete"
HELP = "Delete a simulation (DuckDB row + Zarr store)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "sim_id",
        help="Full sim_id, unique prefix, or simulation name",
    )
    parser.add_argument("--workspace", default=None, help="Workspace root (default: auto-detect)")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = find_workspace_root(
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

        result = delete_simulation_artifacts(catalog, sid)
        for removed_path in result["removed_paths"]:
            print(f"  removed: {removed_path}")
        print(f"Deleted simulation {label}")


def delete_simulation_artifacts(catalog, sid: str) -> dict[str, object]:
    """Delete one simulation row and its on-disk artefacts.

    Returns a small summary with removed paths and the approximate byte count
    freed on disk. Missing artefacts are ignored.
    """
    zarr_path = catalog.zarr_path_for(sid)
    parquet_dir = catalog.parquet_dir_for(sid)
    freed_bytes = _path_size(zarr_path) + _path_size(parquet_dir)

    _delete_from_catalog(catalog, sid)

    removed_paths: list[str] = []
    if zarr_path.exists():
        if zarr_path.is_dir():
            shutil.rmtree(zarr_path, ignore_errors=True)
        else:
            zarr_path.unlink(missing_ok=True)
        removed_paths.append(str(zarr_path))
    if parquet_dir.exists():
        shutil.rmtree(parquet_dir, ignore_errors=True)
        removed_paths.append(str(parquet_dir))
    return {
        "sim_id": sid,
        "freed_bytes": freed_bytes,
        "removed_paths": removed_paths,
    }


def _delete_from_catalog(catalog, sid: str) -> None:
    """Delete a simulation and all related rows via the catalog connection.

    The schema uses ``(sim_id)`` as the natural key across every table that
    carries simulation-scoped data, so a flat delete loop is sufficient.
    """
    conn = catalog.connection
    tables = (
        "parameters",
        "timeseries",
        "budgets",
        "mass_balance",
        "metrics",
        "observation_points",
        "provenance",
        "calibration_iterations",
        "calibration_sessions",
        "geographic_features",
        "geographic_metadata",
        "tags",
        "runs_environment",
    )
    for table in tables:
        try:
            conn.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
        except Exception:
            # Skip tables that may not exist in older workspaces.
            pass
    conn.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])


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
