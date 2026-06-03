"""``hmp catalog show`` - inspect a simulation.

Thin wrapper around :func:`hydromodpy.show_simulation`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_catalog_root
from hydromodpy.core.state.paths import CATALOG_FILENAME

NAME: str = "show"
HELP: str = "Show simulation metadata, metrics, parameters, and storage layout"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp catalog show ab12cd34 --detail",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Include Zarr store layout (groups, paths) alongside metadata",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import show_simulation
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationCatalog,
        SimulationNotFoundError,
    )

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not (workspace_root / CATALOG_FILENAME).exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        payload = show_simulation(args.sim_ref, workspace=workspace_root, detail=args.detail)
    except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if args.format == "json":
        print(json.dumps(payload, indent=2, default=str))
        return

    name = payload.get("name") or payload["sim_id"][:8]
    print(f"Simulation {name}")
    print(f"  sim_id    : {payload['sim_id']}")
    print(f"  project   : {payload['project']}")
    print(f"  solver    : {payload['solver']}")
    print(f"  status    : {payload['status']}")
    if payload.get("duration_s") is not None:
        print(f"  duration  : {payload['duration_s']:.1f} s")
    if payload.get("n_cells") is not None:
        print(f"  n_cells   : {payload['n_cells']}")
    if payload.get("n_timesteps") is not None:
        print(f"  n_timesteps: {payload['n_timesteps']}")
    if args.detail:
        zarr_path = payload.get("zarr_path", "")
        zarr_ok = "OK" if payload.get("zarr_exists") else "MISSING"
        print(f"  zarr       : {zarr_path} ({zarr_ok})")
        groups = payload.get("zarr_groups", [])
        if groups:
            print("  groups     :")
            for group in groups:
                print(f"    - {group}")

    # Metrics / parameters tables still require a direct catalog read.
    with SimulationCatalog(workspace_root) as catalog:
        sim = catalog[payload["sim_id"]]
        metrics = sim.metrics
        if not metrics.empty:
            print("Metrics:")
            print(metrics.to_string(index=False))
        params = sim.parameters
        if not params.empty:
            print("Parameters:")
            print(params.to_string(index=False))
