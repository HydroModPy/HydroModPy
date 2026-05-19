"""``hmp catalog show`` - inspect a simulation (metadata, mesh, status, files)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydromodpy.cli.helpers import (
    EXIT_NOT_FOUND,
    find_catalog_root,
    resolve_sim_id,
)
from hydromodpy.core.state.paths import CATALOG_FILENAME

NAME: str = "show"
HELP: str = "Show simulation metadata, metrics, parameters, and storage layout"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "sim_id",
        help="Full sim_id, unique prefix (>=4 chars), or simulation name",
    )
    parser.add_argument(
        "--workspace", default=None, help="Project catalog root (default: auto-detect)"
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON document")
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Include Zarr store layout (groups, paths) alongside metadata",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not (workspace_root / CATALOG_FILENAME).exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    with SimulationCatalog(workspace_root) as catalog:
        sid = resolve_sim_id(catalog, args.sim_id)
        sim = catalog[sid]

        payload: dict[str, object] = {
            "sim_id": sim.sim_id,
            "name": sim.name,
            "project": sim.project,
            "solver": sim.solver,
            "status": sim.status,
            "duration_s": sim.duration_s,
            "n_cells": sim.n_cells,
            "n_timesteps": sim.n_timesteps,
        }

        zarr_path = catalog.zarr_path_for(sid)
        zarr_exists = zarr_path.exists()
        sub_files: list[str] = []
        if args.detail:
            payload["zarr_path"] = str(zarr_path)
            payload["zarr_exists"] = zarr_exists
            if zarr_exists and zarr_path.is_dir():
                try:
                    sub_files = sorted(p.name for p in zarr_path.iterdir() if p.is_dir())[:20]
                except OSError:
                    sub_files = []
            payload["zarr_groups"] = sub_files

        if args.json:
            print(json.dumps(payload, indent=2, default=str))
            return

        print(f"Simulation {sim.name or sim.sim_id[:8]}")
        print(f"  sim_id    : {sim.sim_id}")
        print(f"  project   : {sim.project}")
        print(f"  solver    : {sim.solver}")
        print(f"  status    : {sim.status}")
        if sim.duration_s is not None:
            print(f"  duration  : {sim.duration_s:.1f} s")
        if sim.n_cells is not None:
            print(f"  n_cells   : {sim.n_cells}")
        if sim.n_timesteps is not None:
            print(f"  n_timesteps: {sim.n_timesteps}")

        if args.detail:
            print(f"  zarr       : {zarr_path} ({'OK' if zarr_exists else 'MISSING'})")
            if sub_files:
                print("  groups     :")
                for name in sub_files:
                    print(f"    - {name}")

        metrics = sim.metrics
        if not metrics.empty:
            print("Metrics:")
            print(metrics.to_string(index=False))
        params = sim.parameters
        if not params.empty:
            print("Parameters:")
            print(params.to_string(index=False))
