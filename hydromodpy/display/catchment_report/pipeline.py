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
from hydromodpy.display.catchment_report.postflight import write_figure_postflight_report
from hydromodpy.display.catchment_report.preflight import validate_catchment_report_preflight
from hydromodpy.display.catchment_report.presets import (
    CatchmentReportPreset,
)


@dataclass(frozen=True)
class CatchmentReportPipelineResult:
    overview_config: Path | None
    simulation_config: Path | None
    context_summary: Path | None
    html_report: Path | None
    postflight_report: Path | None = None


@dataclass(frozen=True)
class _PipelineOverrides:
    run_overview: bool | None
    run_simulation: bool | None
    build_context_artifacts: bool | None
    build_report_html: bool | None
    no_lock: bool | None
    stream_run_logs: bool | None
    strict_figure_postflight: bool | None


@dataclass(frozen=True)
class _PipelineOptions:
    run_overview: bool
    run_simulation: bool
    build_context_artifacts: bool
    build_report_html: bool
    no_lock: bool
    stream_run_logs: bool
    strict_figure_postflight: bool


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
    strict_figure_postflight: bool | None = None,
) -> CatchmentReportPipelineResult:
    """Run the selected report-production steps from one report config."""
    inputs = CatchmentReportInputs.from_toml(report_config)
    options = _resolve_pipeline_options(
        inputs,
        _PipelineOverrides(
            run_overview=run_overview,
            run_simulation=run_simulation,
            build_context_artifacts=build_context_artifacts,
            build_report_html=build_report_html,
            no_lock=no_lock,
            stream_run_logs=stream_run_logs,
            strict_figure_postflight=strict_figure_postflight,
        ),
    )
    validate_catchment_report_preflight(
        inputs,
        run_overview=options.run_overview,
        run_simulation=options.run_simulation,
        build_context_artifacts=options.build_context_artifacts,
        build_report_html=options.build_report_html,
    )
    return _run_pipeline_steps(inputs, options, preset=preset)


def _resolve_pipeline_options(
    inputs: CatchmentReportInputs,
    overrides: _PipelineOverrides,
) -> _PipelineOptions:
    return _PipelineOptions(
        run_overview=_override_or_default(
            overrides.run_overview,
            inputs.pipeline_run_overview,
        ),
        run_simulation=_override_or_default(
            overrides.run_simulation,
            inputs.pipeline_run_simulation,
        ),
        build_context_artifacts=_override_or_default(
            overrides.build_context_artifacts,
            inputs.pipeline_build_context_artifacts,
        ),
        build_report_html=_override_or_default(
            overrides.build_report_html,
            inputs.pipeline_build_report_html,
        ),
        no_lock=_override_or_default(overrides.no_lock, inputs.pipeline_no_lock),
        stream_run_logs=_override_or_default(
            overrides.stream_run_logs,
            inputs.pipeline_stream_run_logs,
        ),
        strict_figure_postflight=_override_or_default(
            overrides.strict_figure_postflight,
            inputs.pipeline_strict_figure_postflight,
        ),
    )


def _override_or_default(value: bool | None, default: bool) -> bool:
    return default if value is None else value


def _run_pipeline_steps(
    inputs: CatchmentReportInputs,
    options: _PipelineOptions,
    *,
    preset: CatchmentReportPreset | None,
) -> CatchmentReportPipelineResult:
    overview_config = inputs.overview_config if options.run_overview else None
    simulation_config = inputs.transient_config if options.run_simulation else None
    context_summary = None
    html_report = None
    postflight_report = None

    if options.run_overview:
        _run_overview(inputs, options)
    if options.run_simulation:
        _run_simulation(inputs, options)
    if options.build_context_artifacts:
        context_summary = _build_context_artifacts(inputs)
    if options.build_report_html:
        html_report, postflight_report = _build_report_html(inputs, options, preset=preset)

    return CatchmentReportPipelineResult(
        overview_config=overview_config,
        simulation_config=simulation_config,
        context_summary=context_summary,
        html_report=html_report,
        postflight_report=postflight_report,
    )


def _run_overview(inputs: CatchmentReportInputs, options: _PipelineOptions) -> None:
    _run_hydromodpy(
        inputs.overview_config,
        no_lock=options.no_lock,
        stream_logs=options.stream_run_logs,
    )


def _run_simulation(inputs: CatchmentReportInputs, options: _PipelineOptions) -> None:
    _run_hydromodpy(
        inputs.transient_config,
        no_lock=options.no_lock,
        stream_logs=options.stream_run_logs,
    )
    _validate_simulation_outputs(inputs)


def _build_context_artifacts(inputs: CatchmentReportInputs) -> Path:
    return build_context(inputs)


def _build_report_html(
    inputs: CatchmentReportInputs,
    options: _PipelineOptions,
    *,
    preset: CatchmentReportPreset | None,
) -> tuple[Path, Path]:
    config = CatchmentReportConfig.from_inputs(inputs, preset=preset)
    html_report = build_catchment_report(config)
    postflight_report = write_figure_postflight_report(
        config,
        strict=options.strict_figure_postflight,
    )
    return html_report, postflight_report


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
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if completed.returncode != 0:
        _print_subprocess_tail(completed.stdout, "hydromodpy run stdout")
        _print_subprocess_tail(completed.stderr, "hydromodpy run stderr")
        completed.check_returncode()


def _print_subprocess_tail(text: str | None, label: str, *, max_lines: int = 80) -> None:
    if not text:
        return
    lines = text.splitlines()
    tail = lines[-max_lines:]
    print(
        f"--- {label} (last {len(tail)} lines) ---",
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
    from hydromodpy.display.catchment_report.cli import (
        add_catchment_report_arguments,
        print_catchment_report_result,
        run_catchment_report_from_args,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    add_catchment_report_arguments(
        parser,
        report_config_option=True,
    )
    args = parser.parse_args(argv)
    try:
        result = run_catchment_report_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    print_catchment_report_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
