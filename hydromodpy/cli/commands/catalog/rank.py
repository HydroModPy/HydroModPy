"""``hmp catalog rank`` - rank the runs of a project by a metric.

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

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, project_root_of, refuse
from hydromodpy.cli.output import emit

NAME: str = "rank"
HELP: str = "Rank the runs of a project by a metric (best or worst N)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp catalog rank --metric nse --top 5 -w projects/my_project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project label in the index (default: the name of the project folder)",
    )
    parser.add_argument("--metric", default="nse", help="Metric name (default: nse)")
    parser.add_argument(
        "--station", default=None, help="Rank the scores of one station only (default: all)"
    )
    parser.add_argument(
        "--mixed-windows",
        action="store_true",
        help="Rank scores computed on different windows, stations or rule versions together",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--top", type=int, default=None, help="Show the N best simulations")
    group.add_argument("--bottom", type=int, default=None, help="Show the N worst simulations")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog.constants import UnrankedMetricError
    from hydromodpy.results.catalog.listing import rank_simulations

    if args.bottom is not None:
        n, best = args.bottom, False
    elif args.top is not None:
        n, best = args.top, True
    else:
        n, best = 1, True

    project = args.project or project_root_of(args).name
    try:
        df = rank_simulations(
            project,
            workspace=args.workspace,
            metric=args.metric,
            station=args.station,
            best=best,
            n=n,
            mixed_windows=args.mixed_windows,
        )
    except UnrankedMetricError as exc:
        refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    if df.empty and args.format == "table":
        refuse(f"No simulations with metric '{args.metric}' in project '{project}'", EXIT_NOT_FOUND)

    def table() -> None:
        label = "TOP" if best else "BOTTOM"
        for idx, row in enumerate(df.itertuples(index=False), start=1):
            display = row.name or str(row.sim_id)[:8]
            print(
                f"{label}#{idx}: {display}  sim_id={row.sim_id}  solver={row.solver}  "
                f"station={row.station}  {args.metric}={row.value:.4f}  "
                f"window={_day(row.window_start)}..{_day(row.window_end)}"
            )

    emit(args, "catalog rank", df, table=table)


def _day(value: object) -> str:
    """Return a window bound as a date, ``?`` when the score has none."""
    return "?" if value is None or value != value else str(value)[:10]
