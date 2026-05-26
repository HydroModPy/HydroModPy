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
    run_overview: bool | None = None,
    run_simulation: bool | None = None,
    build_context_artifacts: bool | None = None,
    build_report_html: bool | None = None,
    no_lock: bool | None = None,
    stream_run_logs: bool | None = None,
) -> CatchmentReportPipelineResult:
    """Run the selected report-production steps from one report config."""
    inputs = CatchmentReportInputs.from_toml(report_config)
    effective_run_overview = inputs.pipeline_run_overview if run_overview is None else run_overview
    effective_run_simulation = (
        inputs.pipeline_run_simulation if run_simulation is None else run_simulation
    )
    effective_build_context_artifacts = (
        inputs.pipeline_build_context_artifacts
        if build_context_artifacts is None
        else build_context_artifacts
    )
    effective_build_report_html = (
        inputs.pipeline_build_report_html if build_report_html is None else build_report_html
    )
    effective_no_lock = inputs.pipeline_no_lock if no_lock is None else no_lock
    effective_stream_run_logs = (
        inputs.pipeline_stream_run_logs if stream_run_logs is None else stream_run_logs
    )
    overview_config = inputs.overview_config if effective_run_overview else None
    simulation_config = inputs.transient_config if effective_run_simulation else None
    context_summary = None
    html_report = None

    if effective_run_overview:
        _run_hydromodpy(
            inputs.overview_config,
            no_lock=effective_no_lock,
            stream_logs=effective_stream_run_logs,
        )
    if effective_run_simulation:
        _run_hydromodpy(
            inputs.transient_config,
            no_lock=effective_no_lock,
            stream_logs=effective_stream_run_logs,
        )
        _validate_simulation_outputs(inputs)
    if effective_build_context_artifacts:
        context_summary = build_context(inputs)
    if effective_build_report_html:
        html_report = build_catchment_report(
            CatchmentReportConfig.from_inputs(inputs, preset=preset)
        )

    return CatchmentReportPipelineResult(
        overview_config=overview_config,
        simulation_config=simulation_config,
        context_summary=context_summary,
        html_report=html_report,
    )


def _run_hydromodpy(config_path: Path, *, no_lock: bool, stream_logs: bool) -> None:
    command = [sys.executable, "-m", "hydromodpy", "run", str(config_path)]
    if no_lock:
        command.append("--no-lock")
    if stream_logs:
        subprocess.run(command, check=True)
        return

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        _print_subprocess_tail(completed.stdout, "stdout")
        _print_subprocess_tail(completed.stderr, "stderr")
        completed.check_returncode()


def _print_subprocess_tail(text: str | None, label: str, *, max_lines: int = 80) -> None:
    if not text:
        return
    lines = text.splitlines()
    tail = lines[-max_lines:]
    print(
        f"--- hydromodpy run {label} (last {len(tail)} lines) ---",
        file=sys.stderr,
    )
    print("\n".join(tail), file=sys.stderr)


def _validate_simulation_outputs(inputs: CatchmentReportInputs) -> None:
    missing = []
    if not inputs.simulation_export.exists():
        missing.append(f"simulation export: {inputs.simulation_export}")
    if not inputs.simulation_figures.exists():
        missing.append(f"simulation figures directory: {inputs.simulation_figures}")
    if missing:
        details = "\n".join(f"- {item}" for item in missing)
        raise FileNotFoundError(
            "Simulation completed but the catchment report expected outputs "
            f"were not found:\n{details}"
        )


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
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run the configured overview before building context/report artifacts.",
    )
    parser.add_argument(
        "--run-simulation",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run the configured simulation before building context/report artifacts.",
    )
    parser.add_argument(
        "--no-context",
        dest="build_context_artifacts",
        action="store_false",
        default=None,
        help="Skip context artifact generation.",
    )
    parser.add_argument(
        "--no-report",
        dest="build_report_html",
        action="store_false",
        default=None,
        help="Skip final HTML report generation.",
    )
    parser.add_argument(
        "--with-lock",
        dest="no_lock",
        action="store_false",
        default=None,
        help="Do not pass --no-lock to hydromodpy run.",
    )
    parser.add_argument(
        "--stream-run-logs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Stream logs from optional hydromodpy run steps.",
    )
    args = parser.parse_args(argv)
    result = run_catchment_report_pipeline(
        args.report_config,
        preset=preset_from_name(args.preset) if args.preset else None,
        run_overview=args.run_overview,
        run_simulation=args.run_simulation,
        build_context_artifacts=args.build_context_artifacts,
        build_report_html=args.build_report_html,
        no_lock=args.no_lock,
        stream_run_logs=args.stream_run_logs,
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
