"""Orchestrate catchment report artifact production from one TOML config."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.display.catchment_report.builder import (
    CatchmentReportConfig,
    build_catchment_report,
)
from hydromodpy.display.catchment_report.context import build_context
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.presets import (
    CatchmentReportPreset,
    preset_from_name,
)


@dataclass(frozen=True)
class CatchmentReportPipelineResult:
    overview_config: Path | None
    simulation_config: Path | None
    context_summary: Path | None
    html_report: Path | None


def run_catchment_report_pipeline(
    report_config: Path,
    *,
    preset: CatchmentReportPreset | None = None,
    run_overview: bool = False,
    run_simulation: bool = False,
    build_context_artifacts: bool = True,
    build_report_html: bool = True,
    no_lock: bool = True,
) -> CatchmentReportPipelineResult:
    """Run the selected report-production steps from one report config."""
    inputs = CatchmentReportInputs.from_toml(report_config)
    overview_config = inputs.overview_config if run_overview else None
    simulation_config = inputs.transient_config if run_simulation else None
    context_summary = None
    html_report = None

    if run_overview:
        _run_hydromodpy(inputs.overview_config, no_lock=no_lock)
    if run_simulation:
        _run_hydromodpy(inputs.transient_config, no_lock=no_lock)
    if build_context_artifacts:
        context_summary = build_context(inputs)
    if build_report_html:
        html_report = build_catchment_report(
            CatchmentReportConfig.from_inputs(inputs, preset=preset)
        )

    return CatchmentReportPipelineResult(
        overview_config=overview_config,
        simulation_config=simulation_config,
        context_summary=context_summary,
        html_report=html_report,
    )


def _run_hydromodpy(config_path: Path, *, no_lock: bool) -> None:
    command = [sys.executable, "-m", "hydromodpy", "run", str(config_path)]
    if no_lock:
        command.append("--no-lock")
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-config", type=Path, required=True)
    parser.add_argument(
        "--preset",
        choices=sorted({"generic_catchment_report", "nancon_reference", "generic", "nancon"}),
        default=None,
        help="Override the catchment report preset declared in the TOML.",
    )
    parser.add_argument(
        "--run-overview",
        action="store_true",
        help="Run the configured overview before building context/report artifacts.",
    )
    parser.add_argument(
        "--run-simulation",
        action="store_true",
        help="Run the configured simulation before building context/report artifacts.",
    )
    parser.add_argument(
        "--no-context",
        action="store_true",
        help="Skip context artifact generation.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip final HTML report generation.",
    )
    parser.add_argument(
        "--with-lock",
        action="store_true",
        help="Do not pass --no-lock to hydromodpy run.",
    )
    args = parser.parse_args(argv)
    result = run_catchment_report_pipeline(
        args.report_config,
        preset=preset_from_name(args.preset) if args.preset else None,
        run_overview=args.run_overview,
        run_simulation=args.run_simulation,
        build_context_artifacts=not args.no_context,
        build_report_html=not args.no_report,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
