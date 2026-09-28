"""``hmp viz show`` - thin wrapper around :func:`hydromodpy.display.runs.render_figure`.

The figure is drawn with the options the run's own ``[display]`` gave it, so
it redraws the figure the run drew; ``--time`` names another instant. A
figure the run cannot feed is refused with its reason (exit code 1), as
``hmp.figure`` refuses it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, verbosity_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, apply_verbosity

NAME: str = "show"
HELP: str = "Render one figure for a simulation"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[verbosity_parser()])
    add_sim_ref(parser)
    parser.add_argument(
        "figure", help="Figure name from 'hmp viz list' (e.g. watertable_depth_map)"
    )
    parser.add_argument("--workspace", default=None, help="Project catalog root")
    parser.add_argument(
        "--output",
        default=None,
        type=Path,
        help="Output file path (default: runs/<run>/figures/<figure>.png)",
    )
    parser.add_argument(
        "--time",
        default=None,
        help=(
            'Instant a map draws: a date (2002-10-15), "first" or "last". '
            "Default: the one the run's [display] names, else the figure's own"
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.viz import render_figure
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )

    try:
        save = render_figure(
            args.sim_ref,
            args.figure,
            workspace=args.workspace,
            output=args.output,
            time=args.time,
        )
    except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    print(f"wrote {save}", file=sys.stderr)
