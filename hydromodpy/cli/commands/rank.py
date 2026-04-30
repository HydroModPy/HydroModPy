"""``hmp rank`` - rank simulations of a project by a metric."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_workspace_root

NAME: str = "rank"
HELP: str = "Rank simulations of a project by a metric (top or bottom N)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project label")
    parser.add_argument("--metric", default="nse", help="Metric name (default: nse)")
    parser.add_argument("--workspace", default=None, help="Workspace root (default: auto-detect)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--top", type=int, default=None, help="Show the top N simulations")
    group.add_argument("--bottom", type=int, default=None, help="Show the bottom N simulations")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    if args.bottom is not None:
        n, ascending_choice = args.bottom, True
    elif args.top is not None:
        n, ascending_choice = args.top, False
    else:
        n, ascending_choice = 1, False

    higher_is_better = _higher_is_better(args.metric)
    ascending = ascending_choice if higher_is_better else not ascending_choice
    order = "ASC" if ascending else "DESC"

    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = find_workspace_root(Path(args.workspace or Path.cwd()).expanduser().resolve())
    if not (workspace_root / "hydromodpy.duckdb").exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    with SimulationCatalog(workspace_root) as catalog:
        rows = catalog._connection.execute(
            f"""
            SELECT s.sim_id, s.name, s.solver, s.status, m.value
            FROM simulations s
            JOIN metrics m ON s.sim_id = m.sim_id
            WHERE s.project = ? AND m.metric_name = ?
            ORDER BY m.value {order}
            LIMIT ?
            """,
            [args.project, args.metric, n],
        ).fetchall()
        if not rows:
            print(
                f"No simulations with metric '{args.metric}' in project '{args.project}'",
                file=sys.stderr,
            )
            sys.exit(EXIT_NOT_FOUND)
        label = "BOTTOM" if ascending_choice else "TOP"
        for rank_idx, (sim_id, name, solver, status, value) in enumerate(rows, start=1):
            display_name = name or str(sim_id)[:8]
            print(
                f"{label}#{rank_idx}: {display_name}  sim_id={sim_id}  solver={solver}  "
                f"status={status}  {args.metric}={value:.4f}"
            )


def _higher_is_better(metric: str) -> bool:
    metric = metric.lower()
    if metric in {"rmse", "mae", "mse", "bias", "pbias"}:
        return False
    return True
