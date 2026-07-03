"""``hmp report`` - render HTML reports and pairwise comparisons.

Sub-actions:

- ``hmp report render [session_ref]``: render the calibration HTML report for
  a calibration session. ``session_ref`` is a session id/prefix or a
  calibration run id/prefix (mapped to its parent session); omit it to render
  the most recent session. Federates across every project in the workspace.
- ``hmp report compare <ref_a> <ref_b>``: side-by-side metric comparison of
  two simulations.
- ``hmp report catchment <report_config>``: build a catchment HTML report from
  one catchment report TOML configuration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    find_catalog_root,
)
from hydromodpy.core import progress
from hydromodpy.core.state.paths import CATALOG_FILENAME
from hydromodpy.display.catchment_report.cli import add_catchment_report_arguments

NAME: str = "report"
HELP: str = "Render HTML reports and pairwise comparisons"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="report_action", metavar="<action>", required=True)

    render_p = sub.add_parser(
        "render",
        help="Render an HTML report for a calibration session",
        parents=[workspace_parser()],
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
        help="Compare two simulations side-by-side",
        parents=[workspace_parser()],
        epilog="Example:\n  hmp report compare ab12cd34 ef56gh78",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    compare_p.add_argument("ref_a", help="First simulation reference (id, prefix, or name)")
    compare_p.add_argument("ref_b", help="Second simulation reference")
    compare_p.add_argument(
        "--variables",
        default=None,
        help="Comma-separated list of variable names to restrict the comparison",
    )

    catchment_p = sub.add_parser(
        "catchment",
        help="Build a catchment HTML report from one TOML configuration",
    )
    add_catchment_report_arguments(catchment_p, report_config_option=False)

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
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

    workspace_root = args.workspace or find_catalog_root(Path.cwd())
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
    import hydromodpy as hmp
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not (workspace_root / CATALOG_FILENAME).exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        df = hmp.compare_pair(args.ref_a, args.ref_b, workspace=workspace_root)
    except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if args.variables:
        keep = {v.strip() for v in args.variables.split(",") if v.strip()}
        if "metric_name" in df.columns:
            df = df[df["metric_name"].isin(keep)]
        elif "variable" in df.columns:
            df = df[df["variable"].isin(keep)]

    if df.empty:
        print("(no metrics recorded for either simulation)")
        return
    print(df.to_string())


def _cmd_catchment(args: argparse.Namespace) -> None:
    from hydromodpy.display.catchment_report.cli import (
        print_catchment_report_result,
        run_catchment_report_from_args,
    )

    try:
        result = run_catchment_report_from_args(args)
    except ValueError as exc:
        print(
            str(exc),
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    print_catchment_report_result(result)
