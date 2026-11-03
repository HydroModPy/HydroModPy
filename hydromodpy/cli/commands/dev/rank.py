"""``hmp dev rank`` - rank the runs of a project by a metric.

Best and worst follow the direction of the metric, read from
:data:`hydromodpy.results.catalog.constants.METRIC_SENSE`: the top of ``nse`` is
its highest value, the top of ``rmse`` its lowest, the top of ``bias`` the value
closest to zero. Scores computed on different windows, at different stations or
under different rule versions are not comparable: the command refuses them,
naming each rule, unless ``--mixed-windows``. ``--station`` narrows the ranking
to one gauge, and then only the window and the rule version must agree.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for

NAME: str = "rank"
HELP: str = "Rank simulations of a project by a metric (best or worst N)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        epilog="Example:\n  hmp dev rank my_project --metric nse --top 5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", help="Project label")
    parser.add_argument("--metric", default="nse", help="Metric name (default: nse)")
    parser.add_argument(
        "--station", default=None, help="Rank the scores of one station only (default: all)"
    )
    parser.add_argument(
        "--mixed-windows",
        action="store_true",
        help="Rank scores computed on different windows, stations or rule versions together",
    )
    parser.add_argument("-w", "--workspace", default=None, help="Project root")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--top", type=int, default=None, help="Show the N best simulations")
    group.add_argument("--bottom", type=int, default=None, help="Show the N worst simulations")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.dev import rank_simulations
    from hydromodpy.results.catalog.constants import UnrankedMetricError
    from hydromodpy.results.run.sealed import MixedWindowsError

    if args.bottom is not None:
        n, best = args.bottom, False
    elif args.top is not None:
        n, best = args.top, True
    else:
        n, best = 1, True

    try:
        df = rank_simulations(
            args.project,
            workspace=args.workspace,
            metric=args.metric,
            station=args.station,
            best=best,
            n=n,
            mixed_windows=args.mixed_windows,
        )
    except UnrankedMetricError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except MixedWindowsError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if df.empty:
        print(
            f"No simulations with metric '{args.metric}' in project '{args.project}'",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)
    label = "TOP" if best else "BOTTOM"
    for idx, row in enumerate(df.itertuples(index=False), start=1):
        display = row.name or str(row.sim_id)[:8]
        print(
            f"{label}#{idx}: {display}  sim_id={row.sim_id}  solver={row.solver}  "
            f"station={row.station}  {args.metric}={row.value:.4f}  "
            f"window={_day(row.window_start)}..{_day(row.window_end)}"
        )


def _day(value: object) -> str:
    """Return a window bound as a date, ``?`` when the score has none."""
    return "?" if value is None or value != value else str(value)[:10]
