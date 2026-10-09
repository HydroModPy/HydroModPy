"""``hmp viz show`` - thin wrapper around :func:`hydromodpy.display.runs.render_figure`.

The figure is drawn with the options the run's own ``[display]`` gave it, so
it redraws the figure the run drew; ``--time`` names another instant and
``--opt NAME=VALUE`` sets any other option of the figure. A
figure the run cannot feed is refused with its reason (exit code 1), as
``hmp.figure`` refuses it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, verbosity_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_USAGE, apply_verbosity

NAME: str = "show"
HELP: str = "Render one figure for a simulation"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp viz show @last flux_timeseries --output flux.png\n"
            "  hmp viz show @last seepage_map --time 2002-10-15 --opt show_run_name=false\n"
            '  hmp viz show @last hydrograph_sim_obs --opt "title=Outlet discharge" '
            "--opt figsize=[8,4]"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    parser.add_argument(
        "--opt",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        dest="options",
        help=(
            "Figure option, repeatable, as in [display.overrides]: a TOML value "
            '(false, 12, [8, 4], "text") or bare text. title= removes the title, '
            "show_run_name=false keeps the run name out of the figure. "
            "'hmp viz list' and the figures reference give each figure's options"
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

    if args.options:
        from hydromodpy.cli._workers.viz import parse_figure_options

        try:
            options = parse_figure_options(args.figure, args.options)
        except (KeyError, ValueError) as exc:
            print(str(exc).strip("'\""), file=sys.stderr)
            sys.exit(EXIT_USAGE)
    else:
        options = {}
    try:
        save = render_figure(
            args.sim_ref,
            args.figure,
            workspace=args.workspace,
            output=args.output,
            time=args.time,
            options=options,
        )
    except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    print(f"wrote {save}", file=sys.stderr)
