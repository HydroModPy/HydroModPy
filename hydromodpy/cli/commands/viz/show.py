"""``hmp viz show <sim_ref> <figure>`` - render one figure for a simulation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_catalog_root

NAME: str = "show"
HELP: str = "Render one figure for a simulation"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("sim_ref", help="Simulation reference: full UUID, prefix, or name")
    parser.add_argument("figure", help="Figure name (e.g. watertable_map)")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Project catalog root (default: auto-detect)",
    )
    parser.add_argument(
        "--output",
        default=None,
        type=Path,
        help="Output file path (default: figures/<figure>.png in cwd)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.display import get as get_figure
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationCatalog,
        SimulationNotFoundError,
    )

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    with SimulationCatalog(workspace_root) as catalog:
        try:
            sim = catalog[args.sim_ref]
        except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        save = (
            Path(args.output).expanduser().resolve()
            if args.output
            else Path.cwd() / "figures" / f"{args.figure}.png"
        )
        save.parent.mkdir(parents=True, exist_ok=True)
        get_figure(args.figure).plot(sim, save_path=save)
        print(f"wrote {save}", file=sys.stderr)
