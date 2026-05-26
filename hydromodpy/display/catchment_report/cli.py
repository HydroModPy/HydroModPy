"""Shared command-line helpers for catchment report generation."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from hydromodpy.display.catchment_report.pipeline import CatchmentReportPipelineResult


PRESET_CHOICES = ("generic", "generic_catchment_report", "nancon", "nancon_reference")


@dataclass(frozen=True)
class CatchmentReportCommandOptions:
    report_config: Path
    preset_name: str | None
    run_overview: bool | None
    run_simulation: bool | None
    build_context_artifacts: bool | None
    build_report_html: bool | None
    no_lock: bool | None
    stream_run_logs: bool | None
    strict_figure_postflight: bool | None


def add_catchment_report_arguments(
    parser: argparse.ArgumentParser,
    *,
    report_config_option: bool,
    include_legacy_skip_aliases: bool = False,
) -> None:
    """Add the shared catchment report CLI arguments to a parser."""
    if report_config_option:
        parser.add_argument("--report-config", type=Path, required=True)
    else:
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
    if include_legacy_skip_aliases:
        parser.add_argument(
            "--no-context",
            action="store_true",
            dest="report_only",
            help=argparse.SUPPRESS,
        )
        parser.add_argument(
            "--no-report",
            action="store_true",
            dest="context_only",
            help=argparse.SUPPRESS,
        )
    parser.add_argument(
        "--with-lock",
        action="store_true",
        help="Do not pass --no-lock to the optional hydromodpy run steps.",
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
        choices=PRESET_CHOICES,
        default=None,
        help="Override the catchment report preset declared in the TOML.",
    )


def options_from_args(args: argparse.Namespace) -> CatchmentReportCommandOptions:
    """Resolve CLI-only aliases into the pipeline's optional override values."""
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

    return CatchmentReportCommandOptions(
        report_config=args.report_config,
        preset_name=args.preset,
        run_overview=run_overview,
        run_simulation=run_simulation,
        build_context_artifacts=build_context_artifacts,
        build_report_html=build_report_html,
        no_lock=False if args.with_lock else None,
        stream_run_logs=args.stream_run_logs,
        strict_figure_postflight=args.strict_figure_postflight,
    )


def run_catchment_report_from_args(
    args: argparse.Namespace,
) -> CatchmentReportPipelineResult:
    """Run the catchment report pipeline from parsed CLI arguments."""
    from hydromodpy.display.catchment_report.pipeline import run_catchment_report_pipeline
    from hydromodpy.display.catchment_report.presets import preset_from_name

    options = options_from_args(args)
    return run_catchment_report_pipeline(
        options.report_config,
        preset=preset_from_name(options.preset_name) if options.preset_name else None,
        run_overview=options.run_overview,
        run_simulation=options.run_simulation,
        build_context_artifacts=options.build_context_artifacts,
        build_report_html=options.build_report_html,
        no_lock=options.no_lock,
        stream_run_logs=options.stream_run_logs,
        strict_figure_postflight=options.strict_figure_postflight,
    )


def print_catchment_report_result(
    result: CatchmentReportPipelineResult,
    *,
    file: TextIO | None = None,
) -> None:
    """Print generated artifact paths in the public CLI format."""
    stream = file or sys.stdout
    if result.overview_config is not None:
        print(f"overview_config={result.overview_config}", file=stream)
    if result.simulation_config is not None:
        print(f"simulation_config={result.simulation_config}", file=stream)
    if result.context_summary is not None:
        print(f"context_summary={result.context_summary}", file=stream)
    if result.html_report is not None:
        print(f"html_report={result.html_report}", file=stream)
    if result.postflight_report is not None:
        print(f"postflight_report={result.postflight_report}", file=stream)
