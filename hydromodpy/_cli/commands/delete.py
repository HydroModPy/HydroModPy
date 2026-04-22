"""``hmp delete`` — delete a simulation from the catalog and the Zarr store."""

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

        zarr_path = workspace_root / "simulations" / f"{sid}.zarr"
        _delete_from_catalog(catalog, sid)
        if zarr_path.exists():
            shutil.rmtree(zarr_path, ignore_errors=True)
            print(f"  removed zarr: {zarr_path}")
        print(f"Deleted simulation {label}")


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
