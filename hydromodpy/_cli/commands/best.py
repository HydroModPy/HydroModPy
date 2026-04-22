"""``hmp best`` — show the best simulation for a project."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy._cli.helpers import EXIT_NOT_FOUND, find_workspace_root

NAME = "best"
HELP = "Show the top simulation for a project ranked by a metric"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project label")
    parser.add_argument("--metric", default="nse", help="Metric name (default: nse)")
    parser.add_argument("--workspace", default=None, help="Workspace root (default: auto-detect)")
    parser.set_defaults(_handler=run)
    _register_order_mode(parser, "best")
    return parser


def _register_order_mode(parser: argparse.ArgumentParser, mode: str) -> None:
    parser.set_defaults(_rank_mode=mode)


def run(args: argparse.Namespace) -> None:
    _rank_and_print(args, mode=getattr(args, "_rank_mode", "best"))


def _rank_and_print(args: argparse.Namespace, *, mode: str) -> None:
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = find_workspace_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not (workspace_root / "hydromodpy.duckdb").exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    higher_is_better = _higher_is_better(args.metric)
    order = "DESC" if higher_is_better else "ASC"
    if mode == "worst":
        order = "ASC" if higher_is_better else "DESC"

    with SimulationCatalog(workspace_root) as catalog:
        conn = catalog.connection
        row = conn.execute(
            f"""
            SELECT s.sim_id, s.name, s.solver, s.status, m.value
            FROM simulations s
            JOIN metrics m ON s.sim_id = m.sim_id
            WHERE s.project = ? AND m.metric_name = ?
            ORDER BY m.value {order}
            LIMIT 1
            """,
            [args.project, args.metric],
        ).fetchone()
        if row is None:
            print(
                f"No simulations with metric '{args.metric}' in project '{args.project}'",
                file=sys.stderr,
            )
            sys.exit(EXIT_NOT_FOUND)
        sim_id, name, solver, status, value = row
        label = name or str(sim_id)[:8]
        print(
            f"{mode.upper()}: {label}  sim_id={sim_id}  solver={solver}  "
            f"status={status}  {args.metric}={value:.4f}"
        )


def _higher_is_better(metric: str) -> bool:
    metric = metric.lower()
    if metric in {"rmse", "mae", "mse", "bias", "pbias"}:
        return False
    return True
