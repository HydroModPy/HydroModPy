"""``hmp ls`` - list the runs of a project, or where its plan stands.

By default it lists the sealed runs recorded in the project index. Each run shows its site, its label, its score and the ``overrides`` its seal
records (what ``--set`` changed), so a ``.v2`` says how it differs.
``--best METRIC`` ranks the runs by that metric, best first; ``--by site``
groups them by site, and with ``--best`` keeps the best run of each site. The
ranking rule is the one of ``hmp campaign collect``: scores computed on
different windows are refused unless ``--mixed-windows``. A site whose runs
are all left out by ``--best`` is named once, with why (no ``[metrics]
window``, or no such metric): on stdout under the table, on stderr beside
``--format json`` or ``csv``, even when no run is left to list, so stdout
always parses.

``--disk`` lists the runs and the sessions from their directories, with the
outcome each one wrote, and needs no index. ``--plan`` says where each case of
the plan of a ``[sites]`` project stands, as ``hydromodpy.project.api.status``
reads it.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.exit_codes import EXIT_NOT_FOUND, EXIT_USAGE, exit_code_for, refuse
from hydromodpy.cli.output import emit, output_of, print_table, table_cell
from hydromodpy.cli.refs import project_root_of
from hydromodpy.core.workspace.resolve import find_workspace_root

NAME: str = "ls"
HELP: str = "List the runs of a project, or where its plan stands"

_EPILOG = """\
Examples:
  hmp ls --site my_catchment --label calibrated --format json
  hmp ls --best nse
  hmp ls --by site --best nse --format csv
  hmp ls --disk
  hmp ls --plan
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Restrict to one project (looks at projects/<name>/.hmp/index.duckdb)",
    )
    parser.add_argument(
        "--solver",
        default=None,
        help="Filter by solver (exact match on the name the run carries)",
    )
    parser.add_argument("--site", default=None, help="Filter by site name (exact match)")
    parser.add_argument(
        "--status",
        default=None,
        help="Filter by status (a sealed run is completed)",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Filter by label (exploratory, calibrated, evaluated, failed)",
    )
    parser.add_argument("--tag", default=None, help="Filter by an exact tag (e.g. pinned)")
    parser.add_argument(
        "--by",
        choices=("site",),
        default=None,
        help="Group the runs by site; with --best, keep the best run of each site",
    )
    parser.add_argument(
        "--best",
        default=None,
        metavar="METRIC",
        help="Rank by METRIC (nse, kge, rmse...), best first; runs without it are left out",
    )
    parser.add_argument(
        "--mixed-windows",
        action="store_true",
        help="With --best, rank scores computed on different windows or rules together",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of rows to print")
    parser.add_argument(
        "--disk",
        action="store_true",
        help="List the runs and the sessions from their directories, with no index",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Say where each case of the plan of a [sites] project stands",
    )
    parser.add_argument(
        "--stale-minutes",
        type=float,
        default=None,
        metavar="MIN",
        help="With --plan, the age of the pulse past which a running case reads as stale (default: 5)",
    )
    parser.set_defaults(_handler=run)
    return parser


def _resolve_workspace(workspace_arg: str | None) -> Path:
    """Resolve what to list: an explicit root, the enclosing project, or the workspace.

    Nothing found stops with :data:`EXIT_NOT_FOUND`: the listing never falls
    back on a default folder.
    """
    from hydromodpy.core.state.layout import catalog_path_for
    from hydromodpy.core.state.result_dirs import resolve_project_root

    if workspace_arg:
        return Path(workspace_arg).expanduser().resolve()
    ws_override = os.environ.get("HMP_WORKSPACE")
    start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
    project_root = resolve_project_root(start)
    if catalog_path_for(project_root).is_file():
        return project_root
    found = find_workspace_root(start)
    if (found / "projects").is_dir() or (found / "data").is_dir():
        return found
    refuse(f"No project index or workspace at or above {start}. Name one with -w.", EXIT_NOT_FOUND)


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog.constants import UnrankedMetricError
    from hydromodpy.results.catalog.discovery import iter_project_catalog_roots
    from hydromodpy.results.catalog.listing import list_runs
    from hydromodpy.results.run.sealed import MixedWindowsError

    if args.plan:
        _plan(args)
        return
    if args.disk:
        _disk(args)
        return
    workspace_root = _resolve_workspace(args.workspace)
    if not iter_project_catalog_roots(workspace_root):
        refuse(
            f"No indexed project found under {workspace_root}; run `hmp catalog reindex` "
            "in a project first, or `hmp ls --disk` to read the directories",
            EXIT_NOT_FOUND,
        )

    try:
        df, reasons = list_runs(
            workspace_root,
            project=args.project,
            solver=args.solver,
            site=args.site,
            status=args.status,
            label=args.label,
            tag=args.tag,
            limit=args.limit,
            best=args.best,
            by=args.by,
            mixed_windows=args.mixed_windows,
        )
    except UnrankedMetricError as exc:
        refuse(str(exc), EXIT_USAGE, cause=exc)
    except MixedWindowsError as exc:
        print(str(exc), file=sys.stderr)
        if args.by is None:
            print("--by site ranks the runs of each site apart.", file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if df.empty and not reasons:
        emit(
            args,
            "ls",
            [],
            table=lambda: print(f"(no sealed run recorded under {workspace_root})"),
        )
        return
    if args.by == "site" and not args.best:
        df = df.sort_values("site", kind="stable", na_position="last")
    if df.empty:
        reasons = [f"(no sealed run under {workspace_root} has a {args.best})", *reasons]
    # A reason is not a row: beside a document it goes to stderr, so stdout parses.
    machine = args.format != "table"
    emit(args, "ls", df, table=lambda: _print_runs(df, args, reasons))
    if machine:
        for line in reasons:
            print(line, file=sys.stderr)


def _print_runs(df: Any, args: argparse.Namespace, reasons: list[str]) -> None:
    """Print the runs for people, by project or by site, then the sites left out."""
    from hydromodpy.results.catalog.discovery import short_id

    group = "site" if args.by == "site" else "project"
    current: Any = object()
    for _, row in df.iterrows():
        key = row.get(group, "")
        if key != current:
            print(f"# {group}: {key if isinstance(key, str) and key else '(none)'}")
            current = key
        sim_id = str(row["sim_id"])
        name = row.get("name", "") or "(no name)"
        site = row.get("site")
        site_str = f"  site={site}" if group != "site" and isinstance(site, str) and site else ""
        project = row.get("project")
        project_str = f"  project={project}" if group == "site" and project else ""
        mesh_engine = row.get("mesh_engine")
        mesh = mesh_engine if isinstance(mesh_engine, str) else "-"
        nse = row.get("nse")
        nse_str = f"  nse={nse:.3f}" if isinstance(nse, float) and nse == nse else ""
        best = row.get(args.best) if args.best and args.best != "nse" else None
        best_str = f"  {args.best}={best:.3f}" if isinstance(best, float) and best == best else ""
        dur = row.get("duration_s")
        dur_str = f" {dur:.1f}s" if isinstance(dur, float) and dur == dur else ""
        overrides = row.get("overrides")
        overrides_str = f"  overrides: {overrides}" if overrides else ""
        print(
            f"  {name}  [{short_id(sim_id)}]{site_str}{project_str}  "
            f"solver={row.get('solver', '')}  mesh={mesh}  label={row.get('label', '')}"
            f"{nse_str}{best_str}{dur_str}{overrides_str}"
        )
    for line in reasons:
        print(line)


def _disk(args: argparse.Namespace) -> None:
    """List the runs and the sessions of the project from their directories."""
    from hydromodpy.project.api import status

    root = project_root_of(args)
    outcomes = status(workspace=root)
    rows = [outcome.to_dict() for outcome in outcomes]
    emit(args, "ls disk", rows, table=lambda: _print_outcomes(rows, root))


def _print_outcomes(rows: list[dict[str, Any]], root: Path) -> None:
    if not rows:
        print(f"(no run or session under {root})")
        return
    for row in rows:
        sim_id = row["sim_id"] or "-"
        print(f"  {row['name']}  [{sim_id[:8]}]  kind={row['kind']}  status={row['status']}")


def _plan(args: argparse.Namespace) -> None:
    """Say where each case of the current plan stands, read from the disk."""
    from hydromodpy.core.state.result_dirs import sites_project_root
    from hydromodpy.project.api import status

    columns = output_of("ls plan").row_fields
    root = sites_project_root(args.workspace or ".")
    stale_after_s = None if args.stale_minutes is None else 60.0 * args.stale_minutes
    report = status(root, plan=True, stale_after_s=stale_after_s)
    records = [
        {column: table_cell(getattr(row, column)) for column in columns} for row in report.rows
    ]

    def table() -> None:
        counts = ", ".join(f"{n} {state}" for state, n in report.counts().items()) or "no case"
        stale = " (the project files changed since: plan again)" if report.plan_stale else ""
        print(f"plan {report.plan_hash}{stale}: {counts}")
        print_table(
            "ls plan",
            records,
            ("case_id", "status", "rel_dir", "step", "host", "pid", "error"),
        )

    emit(
        args,
        "ls plan",
        {
            "plan_hash": report.plan_hash,
            "plan_stale": report.plan_stale,
            "counts": report.counts(),
            "cases": records,
        },
        table=table,
        csv=(columns, records),
    )
