"""``hmp dev rank`` - thin wrapper around :func:`hydromodpy.rank_simulations`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND

NAME: str = "rank"
HELP: str = "Rank simulations of a project by a metric (top or bottom N)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project label")
    parser.add_argument("--metric", default="nse", help="Metric name (default: nse)")
    parser.add_argument("--workspace", default=None, help="Project catalog root")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--top", type=int, default=None, help="Show the top N simulations")
    group.add_argument("--bottom", type=int, default=None, help="Show the bottom N simulations")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.dev import rank_simulations

    if args.bottom is not None:
        n, top = args.bottom, False
    elif args.top is not None:
        n, top = args.top, True
    else:
        n, top = 1, True
    if not _higher_is_better(args.metric):
        top = not top

    df = rank_simulations(args.project, workspace=args.workspace, metric=args.metric, top=top, n=n)
    if df.empty:
        print(
            f"No simulations with metric '{args.metric}' in project '{args.project}'",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)
    label = "TOP" if args.bottom is None else "BOTTOM"
    for idx, row in enumerate(df.itertuples(index=False), start=1):
        display = row.name or str(row.sim_id)[:8]
        print(
            f"{label}#{idx}: {display}  sim_id={row.sim_id}  solver={row.solver}  "
            f"{args.metric}={row.value:.4f}"
        )


def _higher_is_better(metric: str) -> bool:
    return metric.lower() not in {"rmse", "mae", "mse", "bias", "pbias"}
