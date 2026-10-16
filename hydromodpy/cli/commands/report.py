"""``hmp report`` - render HTML reports and pairwise comparisons.

Sub-actions:

- ``hmp report render [session_ref]``: render the calibration HTML report for
  a calibration session. ``session_ref`` is a session id/prefix or a
  calibration run id/prefix (mapped to its parent session); omit it to render
  the most recent session. Federates across every project in the workspace.
- ``hmp report compare <ref> <ref>... [--by site]``: compare N sealed runs of
  one case (diffs, stability, budget closure, maps, series) and render the page
  under ``summary/report/compare/`` of the project, or ``--out``.
- ``hmp report catchment <report_config>``: build a catchment HTML report from
  one catchment report TOML configuration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.cli._conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_VALIDATION,
    apply_verbosity,
)
from hydromodpy.core import progress
from hydromodpy.core.state.paths import resolve_project_root

if TYPE_CHECKING:
    from hydromodpy.display.catchment_report.pipeline import CatchmentReportPipelineResult

NAME: str = "report"
HELP: str = "Render HTML reports and compare sealed runs"

CATCHMENT_PRESETS: tuple[str, ...] = ("generic", "generic_catchment_report")
"""The keys of ``PRESETS_BY_NAME`` in ``hydromodpy/display/catchment_report/presets.py``.

Written out so that building the ``hmp`` parser does not import the catchment
report, and with it ``matplotlib.pyplot``. A test keeps the two lists equal.
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="report_action", metavar="<action>", required=True)

    render_p = sub.add_parser(
        "render",
        help="Render an HTML report for a calibration session",
        parents=[workspace_parser(), verbosity_parser()],
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
        help="Compare sealed runs of one case and render the page",
        parents=[workspace_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp report compare k_low k_high\n"
            "  hmp report compare calage_nm calage_tpe --by site\n"
            "  hmp report compare runs/coarse runs/fine --allow-different-mesh --out ../mesh_study"
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
        help="Compare the runs of each site separately, one page per site.",
    )
    compare_p.add_argument(
        "--variables",
        default=None,
        help=(
            "Comma-separated variables mapped at the last step. Default: the head and "
            "the depth to the water table when every run has them."
        ),
    )
    compare_p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Folder of the comparison. Default: summary/report/compare/<refs>/ of the project.",
    )
    compare_p.add_argument(
        "--allow-different-mesh",
        action="store_true",
        help="Compare runs solved on different meshes of the same site.",
    )

    catchment_p = sub.add_parser(
        "catchment",
        help="Build a catchment HTML report from one TOML configuration",
        parents=[verbosity_parser()],
        epilog="Examples:\n  hmp report catchment report.toml\n  hmp report catchment report.toml --report-only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_catchment_arguments(catchment_p)

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    action = getattr(args, "report_action", None)
    if action == "render":
        _cmd_render(args)
        return
    if action == "compare":
        _cmd_compare(args)
        return
    if action == "catchment":
        _cmd_catchment(args)
        return
    print(
        "Usage: hmp report {render|compare|catchment} [options]. See 'hmp report --help'.",
        file=sys.stderr,
    )
    sys.exit(EXIT_CONFIG)


def _cmd_render(args: argparse.Namespace) -> None:
    import hydromodpy as hmp
    from hydromodpy.core.exceptions import ConfigError, ConfigMissingError

    workspace_root = args.workspace or resolve_project_root(Path.cwd())
    try:
        with progress.status("Rendering calibration report"):
            out_path = hmp.report(args.sim_ref, workspace=workspace_root)
    except ConfigMissingError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    print(f"wrote {out_path}", file=sys.stderr)
    if args.open_browser:
        import webbrowser

        webbrowser.open(out_path.as_uri())


def _cmd_compare(args: argparse.Namespace) -> None:
    from hydromodpy.analysis.comparison.runs import (
        ComparisonCaseError,
        ComparisonReferenceError,
    )
    from hydromodpy.reporting.comparison.compare import compare_runs

    start = Path(args.workspace or Path.cwd()).expanduser().resolve()
    project_root = resolve_project_root(start)
    variables = (
        [item.strip() for item in args.variables.split(",") if item.strip()]
        if args.variables
        else None
    )
    try:
        with progress.status("Comparing runs"):
            pages = compare_runs(
                args.refs,
                project_root=project_root,
                out=args.out,
                by_site=args.by == "site",
                variables=variables,
                allow_different_mesh=args.allow_different_mesh,
            )
    except ComparisonReferenceError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except ComparisonCaseError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_VALIDATION)
    for page in pages:
        print(f"wrote {page}", file=sys.stderr)


def _add_catchment_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the ``hmp report catchment`` arguments to its parser."""
    parser.add_argument(
        "report_config",
        type=Path,
        metavar="REPORT_CONFIG",
        help="Catchment report TOML configuration.",
    )
    parser.add_argument(
        "--run-overview",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run the configured overview before building report artifacts.",
    )
    parser.add_argument(
        "--run-simulation",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run the configured simulation before building report artifacts.",
    )
    parser.add_argument(
        "--context-only",
        action="store_true",
        help="Build only the context artifacts, not the final HTML report.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Build only the final HTML report from existing context artifacts.",
    )
    parser.add_argument(
        "--stream-run-logs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Stream logs from optional hydromodpy run steps.",
    )
    parser.add_argument(
        "--strict-figure-postflight",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Fail when post-render figure completeness checks find missing figures.",
    )
    parser.add_argument(
        "--preset",
        choices=CATCHMENT_PRESETS,
        default=None,
        help="Override the catchment report preset declared in the TOML.",
    )


def _catchment_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Resolve the command flags into the pipeline's optional override values."""
    if args.context_only and args.report_only:
        raise ValueError("--context-only and --report-only are mutually exclusive.")

    run_overview = args.run_overview
    run_simulation = args.run_simulation
    build_context_artifacts = None
    build_report_html = None
    if args.context_only:
        build_context_artifacts = True
        build_report_html = False
    elif args.report_only:
        run_overview = False if run_overview is None else run_overview
        run_simulation = False if run_simulation is None else run_simulation
        build_context_artifacts = False
        build_report_html = True

    return {
        "run_overview": run_overview,
        "run_simulation": run_simulation,
        "build_context_artifacts": build_context_artifacts,
        "build_report_html": build_report_html,
        "stream_run_logs": args.stream_run_logs,
        "strict_figure_postflight": args.strict_figure_postflight,
    }


def _cmd_catchment(args: argparse.Namespace) -> None:
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.display.catchment_report import preset_from_name
    from hydromodpy.display.catchment_report.pipeline import run_catchment_report_pipeline

    try:
        overrides = _catchment_overrides(args)
        result = run_catchment_report_pipeline(
            args.report_config,
            preset=preset_from_name(args.preset) if args.preset else None,
            **overrides,
        )
    except (ValueError, ConfigError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    _print_catchment_result(result)


def _print_catchment_result(result: CatchmentReportPipelineResult) -> None:
    """Print the paths the catchment report wrote, one ``key=path`` per line."""
    if result.overview_config is not None:
        print(f"overview_config={result.overview_config}")
    if result.simulation_config is not None:
        print(f"simulation_config={result.simulation_config}")
    if result.context_summary is not None:
        print(f"context_summary={result.context_summary}")
    if result.html_report is not None:
        print(f"html_report={result.html_report}")
    if result.postflight_report is not None:
        print(f"postflight_report={result.postflight_report}")
