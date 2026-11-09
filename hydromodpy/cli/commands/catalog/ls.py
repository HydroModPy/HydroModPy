"""``hmp catalog ls`` - list the sealed runs recorded in the index.

Each run shows its site, its label, its score and the ``overrides`` its seal
records (what ``--set`` changed), so a ``.v2`` says how it differs.
``--best METRIC`` ranks the runs by that metric, best first; ``--by site``
groups them by site, and with ``--best`` keeps the best run of each site. The
ranking rule is the one of ``hmp campaign collect``: scores computed on
different windows are refused unless ``--mixed-windows``. A site whose runs
are all left out by ``--best`` is named once, with why (no ``[metrics]
window``, or no such metric): on stdout under the table, on stderr beside
``--format json`` or ``csv``, even when no run is left to list, so stdout
always parses.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_USAGE, exit_code_for, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.workspace.resolve import find_workspace_root

NAME: str = "ls"
HELP: str = "List the sealed runs recorded in the project index"

_EPILOG = """\
Examples:
  hmp catalog ls --site my_catchment --label calibrated --format json
  hmp catalog ls --best nse
  hmp catalog ls --by site --best nse --format csv
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


def _readable_facts(run_dir: Path) -> Any:
    """Return the facts of a listed run, or ``None`` after one warning when it does not read."""
    from hydromodpy.results.run.sealed_facts import UnreadableManifestError, read_run_facts
    from hydromodpy.results.storage.json_io import readable, warn_unreadable

    try:
        return readable(read_run_facts, run_dir)
    except UnreadableManifestError as exc:
        warn_unreadable(run_dir, exc)
        return None


def _with_seal_facts(df: Any, workspace_root: Path, metric: str | None) -> Any:
    """Add the ``overrides`` of each run, its score rule, and ``metric`` when not ``nse``.

    Read from the ``manifest.json`` of each listed run.
    """
    from hydromodpy.results.catalog import iter_project_catalog_roots
    from hydromodpy.results.run.sealed_facts import overrides_text

    roots = {path.name: path for path in iter_project_catalog_roots(workspace_root)}
    columns: dict[str, list[Any]] = {
        "overrides": [],
        "score_station": [],
        "score_variable": [],
        "score_window_start": [],
        "score_window_end": [],
        "metric_rule_version": [],
    }
    values: list[Any] = []
    for record in df.to_dict("records"):
        root = roots.get(str(record.get("project")))
        rel_dir = record.get("rel_dir")
        facts = _readable_facts(root / str(rel_dir)) if root is not None and rel_dir else None
        score = None if facts is None else facts.manifest.score
        columns["overrides"].append("" if facts is None else overrides_text(facts.overrides))
        columns["score_station"].append(None if score is None else score.station)
        columns["score_variable"].append(None if score is None else score.variable)
        columns["score_window_start"].append(None if score is None else score.window_start)
        columns["score_window_end"].append(None if score is None else score.window_end)
        columns["metric_rule_version"].append(None if score is None else score.metric_rule_version)
        if metric is not None and metric != "nse":
            values.append(None if facts is None else facts.metrics.get(metric))
    out = df.assign(**columns)
    if metric is not None and metric != "nse":
        out = out.assign(**{metric: values})
    return out


def _left_out_reasons(listed: Any, ranked: Any, metric: str) -> list[str]:
    """Name the sites whose runs ``--best`` left out, and why, one line per reason."""
    from hydromodpy.results.run.ranking import names_text, unscored_reason

    sites = listed["site"].map(_site_of)
    kept = set(ranked["site"].map(_site_of))
    windowed = listed["score_window_start"].notna()
    groups: dict[bool, list[str]] = {}
    for site in sorted(set(sites) - kept):
        groups.setdefault(bool(windowed[sites == site].any()), []).append(site)
    return [
        unscored_reason(names_text(names), listed[sites.isin(names)], metric)
        for _, names in sorted(groups.items())
    ]


def _site_of(value: Any) -> str:
    return value if isinstance(value, str) and value else "(no site)"


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import iter_project_catalog_roots
    from hydromodpy.results.catalog.constants import UnrankedMetricError
    from hydromodpy.results.catalog.listing import list_simulations
    from hydromodpy.results.run.ranking import rank_rows
    from hydromodpy.results.run.sealed import MixedWindowsError

    workspace_root = _resolve_workspace(args.workspace)
    if not iter_project_catalog_roots(workspace_root):
        refuse(
            f"No indexed project found under {workspace_root}; run `hmp catalog reindex` "
            "in a project first",
            EXIT_NOT_FOUND,
        )

    df = list_simulations(
        workspace_root,
        project=args.project,
        solver=args.solver,
        site=args.site,
        status=args.status,
        label=args.label,
        tag=args.tag,
        limit=None if args.best else args.limit,
    )
    if df.empty:
        emit(
            args,
            "catalog ls",
            [],
            table=lambda: print(f"(no sealed run recorded under {workspace_root})"),
        )
        return

    df = _with_seal_facts(df, workspace_root, args.best)
    listed = df
    reasons: list[str] = []
    try:
        if args.best:
            df = rank_rows(df, args.best, by=args.by, mixed_windows=args.mixed_windows)
            reasons = _left_out_reasons(listed, df, args.best)
        elif args.by == "site":
            df = df.sort_values("site", kind="stable", na_position="last")
    except UnrankedMetricError as exc:
        refuse(str(exc), EXIT_USAGE, cause=exc)
    except MixedWindowsError as exc:
        print(str(exc), file=sys.stderr)
        if args.by is None:
            print("--by site ranks the runs of each site apart.", file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if args.best and args.limit is not None:
        df = df.head(int(args.limit))
    if df.empty:
        reasons = [f"(no sealed run under {workspace_root} has a {args.best})", *reasons]
    # A reason is not a row: beside a document it goes to stderr, so stdout parses.
    machine = args.format != "table"
    emit(args, "catalog ls", df, table=lambda: _print_runs(df, args, reasons))
    if machine:
        for line in reasons:
            print(line, file=sys.stderr)


def _print_runs(df: Any, args: argparse.Namespace, reasons: list[str]) -> None:
    """Print the runs for people, by project or by site, then the sites left out."""
    from hydromodpy.results.catalog import short_id

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
