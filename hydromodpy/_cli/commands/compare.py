"""``hmp compare`` - compare two simulations side-by-side."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy._cli.helpers import (
    EXIT_NOT_FOUND,
    find_workspace_root,
    resolve_sim_id,
)

NAME = "compare"
HELP = "Compare two simulations by sim_id, prefix, or name"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("sim_a", help="First simulation")
    parser.add_argument("sim_b", help="Second simulation")
    parser.add_argument("--workspace", default=None, help="Workspace root (default: auto-detect)")
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
        sid_a = resolve_sim_id(catalog, args.sim_a)
        sid_b = resolve_sim_id(catalog, args.sim_b)
        sim_a = catalog[sid_a]
        sim_b = catalog[sid_b]
        print(f"A: {sim_a.name or sid_a[:8]}  (solver={sim_a.solver})")
        print(f"B: {sim_b.name or sid_b[:8]}  (solver={sim_b.solver})")
        placeholders = "(?, ?)"
        df = catalog.connection.execute(
            "SELECT sim_id, station_id, metric_name, value "
            f"FROM metrics WHERE sim_id IN {placeholders} "
            "ORDER BY metric_name, station_id",
            [sid_a, sid_b],
        ).fetchdf()
        if df.empty:
            print("(no metrics recorded for either simulation)")
            return
        pivot = df.pivot_table(
            index=["metric_name", "station_id"],
            columns="sim_id",
            values="value",
            aggfunc="first",
        )
        rename = {sid_a: "A", sid_b: "B"}
        pivot = pivot.rename(columns=rename)
        print(pivot.to_string())
