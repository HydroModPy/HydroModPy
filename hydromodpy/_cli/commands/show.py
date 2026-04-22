"""``hmp show`` — print metadata, metrics, and parameters of a simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydromodpy._cli.helpers import (
    EXIT_NOT_FOUND,
    find_workspace_root,
    resolve_sim_id,
)


NAME = "show"
HELP = "Show metadata, metrics, and parameters of a simulation"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "sim_id",
        help="Full sim_id, unique prefix (>=4 chars), or simulation name",
    )
    parser.add_argument("--workspace", default=None, help="Workspace root (default: auto-detect)")
    parser.add_argument(
        "--json", action="store_true", help="Emit a JSON document (suitable for jq)"
    )
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
        if args.json:
            out = {
                "sim_id": sim.id,
                "name": sim.name,
                "project": sim.project,
                "solver": sim.solver,
                "status": sim.status,
                "duration_s": sim.duration_s,
                "n_cells": sim.n_cells,
                "n_timesteps": sim.n_timesteps,
            }
            print(json.dumps(out, indent=2, default=str))
            return
        print(f"Simulation {sim.name or sim.id[:8]}")
        print(f"  sim_id    : {sim.id}")
        print(f"  project   : {sim.project}")
        print(f"  solver    : {sim.solver}")
        print(f"  status    : {sim.status}")
        if sim.duration_s is not None:
            print(f"  duration  : {sim.duration_s:.1f} s")
        if sim.n_cells is not None:
            print(f"  n_cells   : {sim.n_cells}")
        metrics = sim.metrics
        if not metrics.empty:
            print("Metrics:")
            print(metrics.to_string(index=False))
        params = sim.parameters
        if not params.empty:
            print("Parameters:")
            print(params.to_string(index=False))
