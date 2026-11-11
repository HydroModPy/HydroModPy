"""``hmp show`` - read one thing of a run, a session or a project.

One command reads, and ``hydromodpy.project.api.show`` does the reading. Without
a selector it prints the summary: the README of a run with its tags, notes,
deliveries and profile, the rows of a calibration session, or what a project
holds. A selector names another reading.

- ``--profile`` where the time went.
- ``--point`` one variable in one cell of one or several runs.
- ``--rank METRIC`` the best runs of a project (``-n``, ``--worst``).
- ``--figure NAME`` one registered figure (``--time``, ``--opt``).
- ``--report`` the report of a run or of a session.
- ``--table NAME`` one sealed table.

A reference is a run directory, a name in the project (``base.v2``), a session, an
``@``-selector, or ``.`` for the project. Without one, the project of ``-w`` or of
the current directory is shown.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    exit_code_for,
    project_root_of,
    refuse,
)
from hydromodpy.cli.output import emit
from hydromodpy.schema.phrases import LANGS

NAME: str = "show"
HELP: str = "Show a run, a session or a project: summary, profile, point, rank, figure, report"

REPORT_PRESETS: tuple[str, ...] = ("research", "management")
"""The keys of ``PRESETS`` in ``hydromodpy/display/report/presets.py``.

Written out so that building the ``hmp`` parser does not import the report
engine, and with it ``matplotlib``. A test keeps the two lists equal.
"""

REFUSED_REPORT_FILE = (
    "hmp show --report reads a sealed run: play the overview and the simulation with "
    "hmp run, then hmp show <run> --report [--overview <run>]."
)

_EPILOG = """\
Examples:
  hmp show base.v2
  hmp show calage --format json
  hmp show base.v2 --profile
  hmp show base.v2 --figure watertable_depth_map --time 2002-10-15 --to map.png
  hmp show run_a run_b --point --var head --cell 5000 --to point.csv
  hmp show . --rank nse -n 5
  hmp show base.v2 --report --preset management --lang fr
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
        "refs",
        nargs="*",
        metavar="REF",
        help=(
            "A run (directory, name, sim_id prefix or @-selector), a session, or '.' for the "
            "project. Several runs are read by --point only. Default: the project."
        ),
    )
    what = parser.add_mutually_exclusive_group()
    what.add_argument(
        "--profile", action="store_true", help="Print where the time went, not the summary"
    )
    what.add_argument(
        "--point",
        action="store_true",
        help="Read variables in one cell (--var, then --xy or --cell)",
    )
    what.add_argument(
        "--rank",
        default=None,
        metavar="METRIC",
        help="Rank the runs of the project by METRIC, best first (-n, --worst)",
    )
    what.add_argument(
        "--figure",
        default=None,
        metavar="NAME",
        help="Draw one figure, by the names 'hmp config figures' lists",
    )
    what.add_argument(
        "--report", action="store_true", help="Write the report of a run or of a session"
    )
    what.add_argument("--table", default=None, metavar="NAME", help="Print one sealed table")
    parser.add_argument(
        "--detail",
        action="store_true",
        help="With the summary of a run, print the facts of the index and the Zarr layout",
    )
    add_destination(
        parser, help="Write the figure, the point table or the sealed table here", metavar="FILE"
    )

    point = parser.add_argument_group("--point")
    point.add_argument(
        "--var",
        dest="variables",
        metavar="NAME",
        action="append",
        default=[],
        help="Field to read, persisted or virtual. Repeat for several fields.",
    )
    where = point.add_mutually_exclusive_group()
    where.add_argument(
        "--xy", nargs=2, type=float, metavar=("X", "Y"), help="Coordinates in the simulation CRS"
    )
    where.add_argument("--cell", type=int, help="Zero-based cell index")
    vertical = point.add_mutually_exclusive_group()
    vertical.add_argument("--layer", type=int, help="Zero-based layer index")
    vertical.add_argument(
        "--depth", type=float, metavar="METERS", help="Depth below the local model top"
    )
    point.add_argument("--label", help="Name of the point reported in the table")
    point.add_argument(
        "--timestep", type=int, help="Keep a single timestep (negative counts from the end)"
    )

    rank = parser.add_argument_group("--rank")
    rank.add_argument("-n", "--limit", type=int, default=None, help="Rows to show (default: 1)")
    rank.add_argument("--worst", action="store_true", help="The worst runs, not the best")
    rank.add_argument(
        "--mixed-windows",
        action="store_true",
        help="Rank scores computed on different windows, stations or rule versions together",
    )

    figure = parser.add_argument_group("--figure")
    figure.add_argument(
        "--time",
        default=None,
        help='Instant a map draws: a date (2002-10-15), "first" or "last"',
    )
    figure.add_argument(
        "--opt",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        dest="options",
        help=(
            "Figure option, repeatable, as in [display.overrides]: a TOML value "
            '(false, 12, [8, 4], "text") or bare text'
        ),
    )

    report = parser.add_argument_group("--report")
    report.add_argument(
        "--overview",
        default=None,
        metavar="RUN",
        help="The sealed overview of the site. Default: the overview of the same site.",
    )
    report.add_argument(
        "--preset",
        choices=REPORT_PRESETS,
        default=None,
        help="research writes report/ with three levels, management a one-page sheet",
    )
    report.add_argument(
        "--lang", choices=LANGS, default=None, help="Language of the method text and of the sheet"
    )
    report.add_argument(
        "--station",
        default=None,
        metavar="ID",
        help="Station of the report series and metrics, or of the ranking (default: the gauge)",
    )
    report.add_argument(
        "--strict",
        action="store_true",
        help="Fail when the report misses a figure it requires, once it is written",
    )
    report.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the report in the default browser once it is written",
    )
    parser.set_defaults(_handler=run)
    return parser


@dataclass(frozen=True, slots=True)
class Target:
    """What a reference names: the directory, and whether it is a run, a session or the project."""

    directory: Path
    kind: str


def run(args: argparse.Namespace) -> None:
    from hydromodpy.core.exceptions import CommandUsageError

    root = project_root_of(args)
    refs = list(args.refs)
    _refuse_a_selector_that_cannot_hold(args, refs)
    if args.point:
        _point(args, root, refs)
    elif args.rank is not None:
        _rank(args, root, refs)
    elif args.report:
        _report(args, root, refs)
    else:
        if len(refs) > 1:
            raise CommandUsageError("Give one reference: only --point reads several runs.")
        summary = args.figure is None and args.table is None and not args.profile
        target = _target(args, root, refs[0] if refs else ".", session_first=summary)
        if args.figure is not None:
            _figure(args, root, target)
        elif args.table is not None:
            _table(args, root, target)
        elif args.profile:
            _profile(args, root, target)
        else:
            _summary(args, root, target)


def _refuse_a_selector_that_cannot_hold(args: argparse.Namespace, refs: list[str]) -> None:
    from hydromodpy.core.exceptions import CommandUsageError

    writes = args.figure is not None or args.point or args.table is not None
    if args.to and not writes:
        raise CommandUsageError("--to writes a figure (--figure), a point (--point) or a table.")
    if args.point:
        if not refs:
            raise CommandUsageError("--point reads runs: name one or several.")
        if not args.variables:
            raise CommandUsageError("--point needs --var NAME, the field to read.")
        if args.xy is None and args.cell is None:
            raise CommandUsageError("--point needs the cell: --xy X Y, or --cell N.")


def _as_path(ref: str) -> str:
    """Return a reference that is a folder written with a slash as an absolute path."""
    given = Path(ref).expanduser()
    return str(given.resolve()) if "/" in ref and given.is_dir() else ref


def _target(
    args: argparse.Namespace, root: Path, ref: str, *, session_first: bool = False
) -> Target:
    """Return what *ref* names, read from the directories of the project, never from the index.

    ``.`` is the project of ``-w`` or of the current directory, and a bare name that is
    no run and no session may be a project under ``projects/`` of the workspace. With
    ``session_first``, a bare name that a session and a run both carry is the session.
    """
    from hydromodpy.cli.helpers import resolve_project
    from hydromodpy.core.exceptions import ConfigMissingError, HydroModPyError
    from hydromodpy.project.api import status

    if ref == ".":
        return Target(resolve_project(args.workspace), "project")
    if session_first and "/" not in ref and not ref.startswith("@"):
        from hydromodpy.results.session.descriptor import resolve_session_dir

        try:
            return Target(resolve_session_dir(root, ref), "session")
        except ConfigMissingError:
            pass
    try:
        found = status(_as_path(ref), workspace=root)
    except (HydroModPyError, FileNotFoundError) as exc:
        named = _project_named(args, ref)
        if named is not None:
            return Target(named, "project")
        hint = "" if args.workspace else " Name the workspace or the project with -w."
        refuse(f"{exc}{hint}", exit_code_for(exc), cause=exc)
    if isinstance(found, list):
        directory = Path(_as_path(ref)).expanduser().resolve()
        if _is_a_project(directory):
            return Target(directory, "project")
        # A run copied out of its project sits in no project: it is its own folder.
        return Target(directory, "run")
    return Target(found.run_dir, found.kind)


def _project_named(args: argparse.Namespace, ref: str) -> Path | None:
    """Return ``projects/<ref>`` of the workspace, when *ref* names one."""
    from hydromodpy.core.state.layout import PROJECTS_DIRNAME
    from hydromodpy.core.workspace.resolve import find_workspace

    if "/" in ref:
        return None
    workspace = find_workspace(args.workspace)
    if workspace is None:
        return None
    candidate = workspace / PROJECTS_DIRNAME / ref
    return candidate if candidate.is_dir() else None


def _is_a_project(directory: Path) -> bool:
    from hydromodpy.core.state.layout import RUNS_DIRNAME, SESSIONS_DIRNAME, is_project_root

    return (
        is_project_root(directory)
        or (directory / RUNS_DIRNAME).is_dir()
        or (directory / SESSIONS_DIRNAME).is_dir()
    )


def _summary(args: argparse.Namespace, root: Path, target: Target) -> None:
    from hydromodpy.project.api import show

    if target.kind == "run":
        _run_summary(args, root, target.directory)
        return
    payload = show(target.directory, what="summary", workspace=root)
    if target.kind == "project":
        emit(args, "show project", payload, table=lambda: _print_project(payload))
        return
    emit(args, "show", payload, table=lambda: _print_session(target.directory, payload))


def _print_session(directory: Path, payload: dict[str, Any]) -> None:
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.project.api import open as open_path
    from hydromodpy.results.session.summary import session_summary, summary_rows

    try:
        rows = summary_rows(session_summary(open_path(directory)))
    except (HydroModPyError, OSError, ValueError) as exc:
        refuse(f"session {directory.name} cannot be read: {exc}", EXIT_NOT_FOUND, cause=exc)
    width = max(len(label) for label, _ in rows)
    for label, text in rows:
        print(f"{label.ljust(width)} : {text}")
    if payload["report"] is None:
        print(f"report: not written; hmp show {directory.name} --report writes it")
    else:
        print(f"report: {payload['report']}")
    print(f"next: hmp show {directory.name} --report", file=sys.stderr)


def _print_project(payload: dict[str, Any]) -> None:
    """Print what a project holds, for people."""
    from hydromodpy.core.state.layout import (
        CATALOG_FILENAME,
        INTERNAL_DIRNAME,
        PROJECT_MARKER_FILENAME,
    )

    print(f"# project: {payload['name']}")
    print(f"# path   : {payload['path']}")
    state = "present" if payload["has_project_toml"] else "missing"
    print(f"  {PROJECT_MARKER_FILENAME:<24} {state}")
    configs = payload["configs"]
    if configs:
        print(f"  configs ({len(configs)}): {', '.join(configs)}")
    print(f"  runs     : {payload['n_runs']}{_by_status(payload['runs'])}")
    print(f"  sessions : {payload['n_sessions']}{_by_status(payload['sessions'])}")
    if payload["n_trials"]:
        print(f"  kept trials: {payload['n_trials']}")
    print(f"  plan     : {payload['plan'] or 'none'}")
    print(f"  summary  : {'summary/' if payload['has_summary'] else 'none'}")
    print(f"  trash    : {payload['n_trashed']} entr{'y' if payload['n_trashed'] == 1 else 'ies'}")
    index_label = f"{INTERNAL_DIRNAME}/{CATALOG_FILENAME}"
    index_state = "present" if payload["has_index"] else "missing (hmp catalog reindex builds it)"
    print(f"  index    : {index_label} {index_state}")


def _by_status(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    return " (" + ", ".join(f"{status} {n}" for status, n in counts.items()) + ")"


# -- A run ---------------------------------------------------------------------------


def _run_summary(args: argparse.Namespace, root: Path, directory: Path) -> None:
    """Print the README of a run, or the facts the index holds, and end on the profile."""
    from hydromodpy.project.api import show

    if args.format == "table" and not args.detail and _print_readme(directory):
        return
    payload = show(directory, what="summary", workspace=root, detail=args.detail)
    _replay_block(root, payload)
    emit(args, "show run", payload, table=lambda: _print_facts(root, payload, args))


def _print_readme(directory: Path) -> bool:
    """Print the README of the run in *directory*; ``False`` when it carries none."""
    from hydromodpy.results.annotations import read_annotations
    from hydromodpy.results.catalog.listing import copy_entries, delivery_entries, profile_of_run
    from hydromodpy.results.storage.contract import README_FILENAME

    readme = directory / README_FILENAME
    if not readme.is_file():
        return False
    print(readme.read_text(encoding="utf-8").rstrip())
    annotations = read_annotations(directory)
    if annotations.tags:
        print(f"\ntags: {', '.join(annotations.tags)}")
    if annotations.notes:
        print("notes:")
        for note in annotations.notes:
            print(f"  - {note.at:%Y-%m-%d %H:%M} {note.text}")
    deliveries = delivery_entries(directory)
    if deliveries:
        _print_deliveries(deliveries)
    copies = copy_entries(directory)
    if copies:
        _print_copies(copies)
    _print_profile(profile_of_run(directory))
    print(f"\nnext: hmp show {directory.name} --detail | hmp diff {directory.name} <other>")
    return True


def _replay_block(project_root: Path, payload: dict[str, Any]) -> None:
    """Fill ``payload["replay"]`` from the seal of a run that played another one again.

    The index holds no class; the seal of the run holds it. A run with no seal
    to read keeps no replay block.
    """
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.results.record.manifest import read_seal

    rel_dir = payload.get("rel_dir")
    if not rel_dir:
        return
    try:
        replay = read_seal(Path(project_root) / rel_dir).lineage.replay
    except (HydroModPyError, OSError, ValueError):
        return
    if replay is not None:
        payload["replay"] = replay.model_dump(mode="json", by_alias=True)


def _seconds(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f} s"


def _print_deliveries(deliveries: list[dict[str, Any]]) -> None:
    """Print where each file of the run was sent, and what became of it."""
    print(f"Deliveries ({len(deliveries)}):")
    for entry in deliveries:
        state = entry["state"] or "unknown"
        print(
            f"  - {entry['file']} -> {entry['destination']}"
            f"  ({state}, {entry['attempts']} attempt(s))"
        )


def _print_copies(copies: list[dict[str, Any]]) -> None:
    """Print where a copy of the run was published, and when."""
    print(f"Copies ({len(copies)}):")
    for entry in copies:
        print(f"  - {entry['to']}  ({entry['published_at']})")


def _print_profile(profile: dict[str, Any]) -> None:
    """Print the Profile block of one run, from :func:`profile_of_run`."""
    print("\nProfile")
    if not profile["present"]:
        print(f"  {profile['message']}: {_seconds(profile['solve_s'])}")
        return
    attempts = profile["attempts"]
    print(f"  total      : {_seconds(profile['total_s'])} over {attempts} attempt(s)")
    print(f"  start-up   : {_seconds(profile['start_s'])}")
    for solve in profile["solve"]:
        print(f"  solve      : {solve['name']} {_seconds(solve['duration_s'])}")
    longest = profile["longest_steps"]
    if longest:
        print(
            "  longest    : "
            + ", ".join(f"{step['name']} {_seconds(step['duration_s'])}" for step in longest)
        )
    for line in profile["reused"]:
        source = line["reused"] if line["key"] is None else f"{line['reused']} {line['key']}"
        print(f"  reused     : {line['name']} ({source}, attempt {line['attempt']})")
    if profile["max_rss_mb"] is not None:
        print(f"  peak memory: {profile['max_rss_mb']:.0f} MiB")


def _print_facts(project_root: Path, payload: dict[str, Any], args: argparse.Namespace) -> None:
    """Print what the index holds about one run, for people."""
    from hydromodpy.results.catalog import Catalog

    if payload.get("rel_dir") is None:
        # A run copied out of its project has no index: its folder says the rest.
        print(f"Run {payload['name']}")
        print(f"  sim_id    : {payload['sim_id']}")
        if payload.get("deliveries"):
            _print_deliveries(payload["deliveries"])
        if payload.get("copies"):
            _print_copies(payload["copies"])
        _print_profile(payload["profile"])
        return
    name = payload.get("name") or payload["sim_id"][:8]
    print(f"Run {name}")
    print(f"  sim_id    : {payload['sim_id']}")
    print(f"  rel_dir   : {payload['rel_dir']}")
    print(f"  project   : {payload['project']}")
    if payload.get("site"):
        print(f"  site      : {payload['site']}")
    print(f"  case      : {payload['case_id']}")
    print(f"  solver    : {payload['solver']}")
    print(f"  status    : {payload['status']}")
    print(f"  label     : {payload['label']} ({payload['label_date']})")
    if payload.get("nse") is not None:
        print(f"  nse       : {payload['nse']:.3f}")
    if payload.get("version_int") is not None:
        print(f"  version   : v{payload['version_int']}")
    if payload.get("solution_key"):
        print(f"  solution  : {payload['solution_key'][:12]}")
    replay = payload.get("replay")
    if replay:
        print(f"  replay    : {replay['class']} ({replay['basis']}, of {replay['of'][:8]})")
    if payload.get("duration_s") is not None:
        print(f"  duration  : {payload['duration_s']:.1f} s")
    if payload.get("n_cells") is not None:
        print(f"  n_cells   : {payload['n_cells']}")
    if payload.get("n_timesteps") is not None:
        print(f"  n_timesteps: {payload['n_timesteps']}")
    if args.detail:
        zarr_ok = "OK" if payload.get("zarr_exists") else "MISSING"
        print(f"  zarr       : {payload.get('zarr_path', '')} ({zarr_ok})")
        groups = payload.get("zarr_groups", [])
        if groups:
            print("  groups     :")
            for group in groups:
                print(f"    - {group}")

    for kind in ("exports", "figures"):
        entries = payload.get(kind) or []
        if entries:
            print(f"{kind.capitalize()} ({len(entries)}):")
            for entry in entries:
                print(f"  - {entry['file']}  ({entry['producer']})")

    deliveries = payload.get("deliveries") or []
    if deliveries:
        _print_deliveries(deliveries)
    copies = payload.get("copies") or []
    if copies:
        _print_copies(copies)

    with Catalog(project_root) as catalog:
        sim = catalog[payload["sim_id"]]
        tags = sim.tags or []
        if tags:
            print(f"  tags      : {', '.join(tags)}")
        notes = catalog.backend.fetch_all(
            "SELECT note FROM sim_notes WHERE sim_id = ? ORDER BY added_at",
            [payload["sim_id"]],
        )
        if notes:
            print("Notes:")
            for (note,) in notes:
                print(f"  - {note}")
        metrics = sim.metrics
        if not metrics.empty:
            print("Metrics:")
            print(metrics.to_string(index=False))
        params = sim.parameters
        if not params.empty:
            print("Parameters:")
            print(params.to_string())

    _print_profile(payload["profile"])
    ref = payload.get("rel_dir") or payload["sim_id"][:8]
    print(f"next: hmp catalog tag {ref} +pinned | hmp diff {ref} <other>")


# -- The other readings --------------------------------------------------------------


def _profile(args: argparse.Namespace, root: Path, target: Target) -> None:
    from hydromodpy.core.exceptions import CommandUsageError
    from hydromodpy.project.api import show

    if target.kind == "project":
        raise CommandUsageError("--profile reads a run or a session, not the project.")
    profile = show(target.directory, what="profile", workspace=root)
    if target.kind == "run":
        emit(args, "show profile", profile, table=lambda: _print_profile(profile))
        return
    emit(
        args,
        "show profile session",
        profile,
        table=lambda: print("(no profile)" if profile.empty else profile.to_string(index=False)),
    )


def _table(args: argparse.Namespace, root: Path, target: Target) -> None:
    from hydromodpy.project.api import show

    frame = show(target.directory, what="table", name=args.table, workspace=root)
    if args.to:
        from hydromodpy.project.show import write_shown

        write_shown(frame, args.to)
    emit(
        args,
        "show table",
        frame,
        table=lambda: _print_frame(frame, args.to, "(the table is empty)"),
    )


def _print_frame(frame: Any, written: str | None, empty: str) -> None:
    print(empty if frame.empty else frame.to_string(index=False))
    if written:
        print(f"written: {written}")


def _point(args: argparse.Namespace, root: Path, refs: list[str]) -> None:
    import pandas as pd

    from hydromodpy.project.api import show

    x, y = args.xy if args.xy else (None, None)
    place = {
        key: value
        for key, value in {
            "x": x,
            "y": y,
            "cell": args.cell,
            "depth": args.depth,
            "label": args.label,
        }.items()
        if value is not None
    }
    frames = []
    for ref in refs:
        target = _target(args, root, ref)
        frames.append(
            show(
                target.directory,
                what="point",
                workspace=root,
                name=list(args.variables),
                point=place,
                layer=args.layer,
                time=args.timestep,
            )
        )
    frame = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    if args.to:
        from hydromodpy.project.show import write_shown

        write_shown(frame, args.to)
    emit(
        args,
        "show point",
        frame,
        table=lambda: _print_frame(frame, args.to, "(no value at this point)"),
    )


def _rank(args: argparse.Namespace, root: Path, refs: list[str]) -> None:
    from hydromodpy.project.api import show
    from hydromodpy.results.catalog.constants import UnrankedMetricError

    target = _target(args, root, refs[0] if refs else ".")
    if len(refs) > 1 or target.kind != "project":
        from hydromodpy.core.exceptions import CommandUsageError

        raise CommandUsageError("--rank reads the project: give '.', or no reference.")
    best = not args.worst
    try:
        frame = show(
            target.directory,
            what="rank",
            workspace=target.directory,
            metric=args.rank,
            station=args.station,
            best=best,
            limit=1 if args.limit is None else args.limit,
            mixed_windows=args.mixed_windows,
        )
    except UnrankedMetricError as exc:
        refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    if frame.empty and args.format == "table":
        refuse(
            f"No simulations with metric '{args.rank}' in project '{target.directory.name}'",
            EXIT_NOT_FOUND,
        )

    def table() -> None:
        label = "TOP" if best else "BOTTOM"
        for idx, row in enumerate(frame.itertuples(index=False), start=1):
            display = row.name or str(row.sim_id)[:8]
            print(
                f"{label}#{idx}: {display}  sim_id={row.sim_id}  solver={row.solver}  "
                f"station={row.station}  {args.rank}={row.value:.4f}  "
                f"window={_day(row.window_start)}..{_day(row.window_end)}"
            )

    emit(args, "show rank", frame, table=table)


def _day(value: object) -> str:
    """Return a window bound as a date, ``?`` when the score has none."""
    return "?" if value is None or value != value else str(value)[:10]


def _figure(args: argparse.Namespace, root: Path, target: Target) -> None:
    from hydromodpy.core.exceptions import CommandUsageError
    from hydromodpy.display.catalog_figures import parse_figure_options
    from hydromodpy.display.runs import figure_options_from_run, figures_dir_of, record_figure
    from hydromodpy.project.api import open as open_path
    from hydromodpy.project.api import show

    if target.kind == "project":
        raise CommandUsageError("--figure draws a run or a session: give one.")
    try:
        options = parse_figure_options(args.figure, args.options) if args.options else {}
    except (KeyError, ValueError) as exc:
        refuse(str(exc).strip("'\""), EXIT_USAGE, cause=exc)
    subject = open_path(target.directory)
    drawn: dict[str, Any] = {}
    figures_dir = figures_dir_of(target.directory)
    if target.kind == "run":
        # The figure takes the options the run's own [display] gave it, as it was drawn.
        drawn.update(figure_options_from_run(subject, args.figure))
    drawn.update(options)
    save = Path(args.to).expanduser().resolve() if args.to else figures_dir / f"{args.figure}.png"
    if save.suffix == "":
        save = save.with_suffix(".png")
    save.parent.mkdir(parents=True, exist_ok=True)
    written = show(
        subject, what="figure", name=args.figure, time=args.time, options=drawn, save=save
    )
    if target.kind == "run" and save.parent.resolve() == figures_dir.resolve():
        record_figure(save, name=args.figure, options=drawn, sim=subject, figures_dir=figures_dir)
    emit(
        args,
        "show figure",
        {"path": written},
        table=lambda: print(f"wrote {written}", file=sys.stderr),
    )


def _report(args: argparse.Namespace, root: Path, refs: list[str]) -> None:
    import json

    from hydromodpy.core.console import progress
    from hydromodpy.core.exceptions import (
        CommandUsageError,
        ConfigError,
        ConfigMissingError,
        DisplayError,
    )
    from hydromodpy.project.api import show

    if len(refs) > 1:
        raise CommandUsageError("Give one reference: a report is written for one run or session.")
    if refs:
        if Path(refs[0]).expanduser().is_file():
            refuse(REFUSED_REPORT_FILE, EXIT_CONFIG)
        target = _target(args, root, refs[0])
    else:
        # Without a reference, the report of the most recent session of the project.
        from hydromodpy.results.session.descriptor import resolve_session_dir

        try:
            target = Target(resolve_session_dir(root, None), "session")
        except ConfigMissingError as exc:
            refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    if target.kind == "project":
        raise CommandUsageError("--report writes the report of a run or of a session.")
    options = {}
    if args.overview is not None:
        options["overview_dir"] = _overview_dir(args, root, args.overview)
    try:
        with progress.status("Writing the report"):
            page = show(
                target.directory,
                what="report",
                workspace=root,
                preset=args.preset,
                lang=args.lang,
                station=args.station,
                strict=args.strict,
                options=options,
            )
    except (ValueError, ConfigError) as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    except DisplayError as exc:
        refuse(str(exc), exit_code_for(exc), cause=exc)

    if target.kind == "session":
        emit(
            args,
            "show report session",
            {"path": page},
            table=lambda: print(f"wrote {page}", file=sys.stderr),
        )
        if args.open_browser:
            import webbrowser

            webbrowser.open(Path(page).as_uri())
        return
    report_json = page.parent / "report.json"
    missing = json.loads(report_json.read_text(encoding="utf-8")).get("missing", [])
    written = {"html_report": page, "report_json": report_json, "missing": missing}

    def table() -> None:
        print(f"html_report={page}")
        print(f"report_json={report_json}")
        if missing:
            print(f"missing={', '.join(missing)}")

    emit(args, "show report", written, table=table)
    if args.open_browser:
        import webbrowser

        webbrowser.open(Path(page).as_uri())


def _overview_dir(args: argparse.Namespace, root: Path, reference: str) -> Path:
    """Return the folder of the overview *reference* names: a directory, else a run of the project."""
    named = Path(reference).expanduser()
    if named.is_file():
        refuse(REFUSED_REPORT_FILE, EXIT_CONFIG)
    return _target(args, root, reference).directory
