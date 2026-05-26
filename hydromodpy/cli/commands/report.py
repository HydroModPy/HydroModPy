"""``hmp report`` - render HTML reports and pairwise comparisons.

Sub-actions:

- ``hmp report render <session_id>``: render the calibration HTML report for
  a calibration session (UUID full or unambiguous prefix).
- ``hmp report compare <ref_a> <ref_b>``: side-by-side metric comparison of
  two simulations.
- ``hmp report catchment <report_config>``: build a catchment HTML report from
  one catchment report TOML configuration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    find_catalog_root,
)
from hydromodpy.core.state.paths import CATALOG_FILENAME

NAME: str = "report"
HELP: str = "Render HTML reports and pairwise comparisons"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="report_action", metavar="<action>")

    render_p = sub.add_parser(
        "render",
        help="Render an HTML report for a calibration session",
    )
    render_p.add_argument(
        "session_id",
        help="Calibration session UUID (full or unambiguous short prefix)",
    )
    render_p.add_argument(
        "--workspace",
        type=Path,
        default=None,
        metavar="PATH",
        help="Project catalog root (defaults to ancestor of CWD).",
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
    )
    compare_p.add_argument("ref_a", help="First simulation reference (id, prefix, or name)")
    compare_p.add_argument("ref_b", help="Second simulation reference")
    compare_p.add_argument(
        "--workspace",
        default=None,
        help="Project catalog root (default: auto-detect)",
    )
    compare_p.add_argument(
        "--variables",
        default=None,
        help="Comma-separated list of variable names to restrict the comparison",
    )

    catchment_p = sub.add_parser(
        "catchment",
        help="Build a catchment HTML report from one TOML configuration",
    )
    catchment_p.add_argument(
        "report_config",
        type=Path,
        metavar="REPORT_CONFIG",
        help="Catchment report TOML configuration.",
    )
    catchment_p.add_argument(
        "--run-overview",
        action="store_true",
        help="Run the configured overview before building report artifacts.",
    )
    catchment_p.add_argument(
        "--run-simulation",
        action="store_true",
        help="Run the configured simulation before building report artifacts.",
    )
    catchment_p.add_argument(
        "--context-only",
        action="store_true",
        help="Build only the context artifacts, not the final HTML report.",
    )
    catchment_p.add_argument(
        "--report-only",
        action="store_true",
        help="Build only the final HTML report from existing context artifacts.",
    )
    catchment_p.add_argument(
        "--with-lock",
        action="store_true",
        help="Do not pass --no-lock to the optional hydromodpy run steps.",
    )

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
        out_path = hmp.report(args.session_id, workspace=workspace_root)
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
    from hydromodpy.display.catchment_report.pipeline import (
        run_catchment_report_pipeline,
    )

    if args.context_only and args.report_only:
        print(
            "--context-only and --report-only are mutually exclusive.",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    result = run_catchment_report_pipeline(
        args.report_config,
        run_overview=args.run_overview,
        run_simulation=args.run_simulation,
        build_context_artifacts=not args.report_only,
        build_report_html=not args.context_only,
        no_lock=not args.with_lock,
    )
    if result.overview_config is not None:
        print(f"overview_config={result.overview_config}")
    if result.simulation_config is not None:
        print(f"simulation_config={result.simulation_config}")
    if result.context_summary is not None:
        print(f"context_summary={result.context_summary}")
    if result.html_report is not None:
        print(f"html_report={result.html_report}")
