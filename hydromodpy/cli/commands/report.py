"""``hmp report`` - render HTML reports and pairwise comparisons.

Sub-actions:

- ``hmp report render [session_ref]``: render the calibration HTML report for
  a calibration session. ``session_ref`` is a session id/prefix or a
  calibration run id/prefix (mapped to its parent session); omit it to render
  the most recent session. Federates across every project in the workspace.
- ``hmp report compare <ref> <ref>... [--by site]``: compare N sealed runs of
  one site (differences, parameters, scores, budget, network, maps, series) and
  write a folder with its README under ``summary/report/compare/`` of the
  project, or ``--to``; ``--by site`` writes one folder per site and joins the
  scores of the references.
- ``hmp report catchment RUN [--overview RUN] [--preset research|management]
  [--lang en|fr] [--station ID] [--strict]``: write the report of a sealed run,
  the three-level ``report/`` or the one-page sheet. It runs no model: ``hmp run``
  does.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_VALIDATION,
    exit_code_for,
    project_root_of,
    refuse,
)
from hydromodpy.cli.output import emit
from hydromodpy.core.console import progress
from hydromodpy.core.state.layout import summary_dir_for
from hydromodpy.core.state.result_dirs import resolve_project_root
from hydromodpy.results.storage.contract import RUN_REPORT_DIRNAME
from hydromodpy.schema.phrases import LANGS

NAME: str = "report"
HELP: str = "Render HTML reports and compare sealed runs"

REPORT_PRESETS: tuple[str, ...] = ("research", "management")
"""The keys of ``PRESETS`` in ``hydromodpy/display/report/presets.py``.

Written out so that building the ``hmp`` parser does not import the report
engine, and with it ``matplotlib.pyplot``. A test keeps the two lists equal.
"""

REFUSED_REPORT_FILE = (
    "hmp report catchment reads a sealed run: play the overview and the simulation with "
    "hmp run, then hmp report catchment <run> [--overview <run>]."
)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="report_action", metavar="<action>", required=True)

    render_p = sub.add_parser(
        "render",
        help="Render an HTML report for a calibration session",
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp report render ab12cd34 --open",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    render_p.add_argument(
        "sim_ref",
        nargs="?",
        default=None,
        metavar="SESSION_REF",
        help=(
            "Calibration session id/prefix, or a calibration run id/prefix "
            "(an iteration or best run, mapped to its session). Omit to render "
            "the most recent session in the workspace."
        ),
    )
    render_p.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the generated HTML in the default browser on completion.",
    )

    compare_p = sub.add_parser(
        "compare",
        help="Compare sealed runs of one site and write a folder with its README",
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp report compare k_low k_high\n"
            "  hmp report compare calage_nm calage_tpe --by site\n"
            "  hmp report compare runs/coarse runs/fine --to ../mesh_study"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    compare_p.add_argument(
        "refs",
        nargs="+",
        metavar="REF",
        help=(
            "A run directory, a run name under runs/ (base.v2), or a recipe "
            "(the latest run of each of its cases). The first run is the reference."
        ),
    )
    compare_p.add_argument(
        "--by",
        choices=("site",),
        default=None,
        help=(
            "Compare the runs of each site separately, one folder per site, and join "
            "their scores in by_site.csv."
        ),
    )
    compare_p.add_argument(
        "--variables",
        default=None,
        help=(
            "Comma-separated variables mapped at the last shared date. Default: the head "
            "and the depth to the water table when every run has them."
        ),
    )
    add_destination(
        compare_p,
        help="Folder of the comparison. Default: summary/report/compare/<refs>/ of the project.",
        metavar="DIR",
    )

    catchment_p = sub.add_parser(
        "catchment",
        help="Write the report of a sealed run",
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n  hmp report catchment base.v2\n"
            "  hmp report catchment base.v2 --overview selune --preset management --lang fr"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_catchment_arguments(catchment_p)

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    {"render": _cmd_render, "compare": _cmd_compare, "catchment": _cmd_catchment}[
        args.report_action
    ](args)


def _cmd_render(args: argparse.Namespace) -> None:
    from hydromodpy.core.exceptions import ConfigError, ConfigMissingError, DisplayError
    from hydromodpy.project.report import report_session
    from hydromodpy.results.session.descriptor import resolve_session_dir

    project_root = project_root_of(args)
    try:
        directory = resolve_session_dir(project_root, args.sim_ref)
        with progress.status("Rendering calibration report"):
            out_path = report_session(directory)
    except ConfigMissingError as exc:
        refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    except ConfigError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    except DisplayError as exc:
        refuse(str(exc), exit_code_for(exc), cause=exc)
    emit(
        args,
        "report render",
        {"path": out_path},
        table=lambda: print(f"wrote {out_path}", file=sys.stderr),
    )
    if args.open_browser:
        import webbrowser

        webbrowser.open(out_path.as_uri())


def compare_folder(refs: list[str], project_root: Path | None) -> Path:
    """Return ``summary/report/compare/<refs>/`` of the project."""
    from hydromodpy.project.compare import ComparisonCaseError

    if project_root is None:
        raise ComparisonCaseError("No project around the runs to write into: pass --out DIR.")
    slugs = [re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(ref).name or ref).strip("_") for ref in refs]
    name = "-vs-".join(slug for slug in slugs if slug)
    if not name or len(name) > 96:
        name = hashlib.sha256("\n".join(refs).encode("utf-8")).hexdigest()[:12]
    return summary_dir_for(project_root) / RUN_REPORT_DIRNAME / "compare" / name


def _cmd_compare(args: argparse.Namespace) -> None:
    from hydromodpy.project.compare import (
        ComparisonCaseError,
        ComparisonReferenceError,
        compare_by_site,
        compare_references,
    )

    start = Path(args.workspace or Path.cwd()).expanduser().resolve()
    project_root = resolve_project_root(start)
    variables = (
        [item.strip() for item in args.variables.split(",") if item.strip()]
        if args.variables
        else None
    )
    try:
        with progress.status("Comparing runs"):
            folder = Path(args.to) if args.to else compare_folder(args.refs, project_root)
            if args.by == "site":
                written = compare_by_site(
                    args.refs, folder, project_root=project_root, variables=variables
                )
            else:
                comparison = compare_references(
                    args.refs, project_root=project_root, variables=variables
                )
                written = comparison.write(folder)
    except ComparisonReferenceError as exc:
        refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    except ComparisonCaseError as exc:
        refuse(str(exc), EXIT_VALIDATION, cause=exc)
    emit(
        args,
        "report compare",
        {"folder": written},
        table=lambda: print(f"wrote {written}", file=sys.stderr),
    )


def _add_catchment_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the ``hmp report catchment`` arguments to its parser."""
    parser.add_argument(
        "run",
        metavar="RUN",
        help="A sealed run: its directory, its name under runs/, or a prefix of its id.",
    )
    parser.add_argument(
        "--overview",
        default=None,
        metavar="RUN",
        help="The sealed overview of the site. Default: the overview of the same site in the project.",
    )
    parser.add_argument(
        "--preset",
        choices=REPORT_PRESETS,
        default="research",
        help="research writes report/ with three levels, management a one-page sheet.",
    )
    parser.add_argument(
        "--lang",
        choices=LANGS,
        default="en",
        help="Language of the method text and of the sheet.",
    )
    parser.add_argument(
        "--station",
        default=None,
        metavar="ID",
        help="Station the page reads its series and metrics from. Default: the gauge of the site.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when the page misses a figure it requires, once it is written.",
    )


def _run_dir_of(args: argparse.Namespace, reference: str) -> Path:
    """Return the folder of the run *reference* names: a directory, else a run of the project."""
    from hydromodpy.results.catalog.discovery import resolve_rel_dir

    named = Path(reference).expanduser()
    if named.is_file():
        refuse(REFUSED_REPORT_FILE, EXIT_CONFIG)
    if named.is_dir():
        return named.resolve()
    project_root = project_root_of(args)
    try:
        return project_root / resolve_rel_dir(project_root, reference)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        refuse(str(exc), exit_code_for(exc), cause=exc)


def _cmd_catchment(args: argparse.Namespace) -> None:
    import json

    from hydromodpy.core.exceptions import ConfigError, DisplayError
    from hydromodpy.project.report import report_run

    run_dir = _run_dir_of(args, args.run)
    overview = None if args.overview is None else _run_dir_of(args, args.overview)
    try:
        with progress.status("Writing the report"):
            page = report_run(
                run_dir,
                preset=args.preset,
                lang=args.lang,
                overview_dir=overview,
                station=args.station,
                strict=args.strict,
            )
    except (ValueError, ConfigError) as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    except DisplayError as exc:
        refuse(str(exc), exit_code_for(exc), cause=exc)

    report_json = page.parent / "report.json"
    missing = json.loads(report_json.read_text(encoding="utf-8")).get("missing", [])
    written = {"html_report": page, "report_json": report_json, "missing": missing}

    def table() -> None:
        print(f"html_report={page}")
        print(f"report_json={report_json}")
        if missing:
            print(f"missing={', '.join(missing)}")

    emit(args, "report catchment", written, table=table)
