"""``hmp viz show`` - thin wrapper around :func:`hydromodpy.render_figure`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND

NAME: str = "show"
HELP: str = "Render one figure for a simulation"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("sim_ref", help="Simulation reference: full UUID, prefix, or name")
    parser.add_argument("figure", help="Figure name (e.g. watertable_map)")
    parser.add_argument("--workspace", default=None, help="Project catalog root")
    parser.add_argument(
        "--output",
        default=None,
        type=Path,
        help="Output file path (default: runs/<run>/figures/<figure>.png)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.viz import render_figure
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )

    try:
        save = render_figure(
            args.sim_ref, args.figure, workspace=args.workspace, output=args.output
        )
    except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    print(f"wrote {save}", file=sys.stderr)
