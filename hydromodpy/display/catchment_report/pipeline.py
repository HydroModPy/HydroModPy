"""Orchestrate catchment report artifact production from one TOML config."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from hydromodpy.display.catchment_report.build_options import CatchmentReportBuildOptions
from hydromodpy.display.catchment_report.builder import (
    CatchmentReportConfig,
    build_catchment_report,
)
from hydromodpy.display.catchment_report.context import (
    build_context,
    context_artifact_manifest_path,
)
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.postflight import write_figure_postflight_report
from hydromodpy.display.catchment_report.preflight import validate_catchment_report_preflight
from hydromodpy.display.catchment_report.presets import (
    CatchmentReportPreset,
)
from hydromodpy.display.overview.report import overview_artifact_manifest_path
from hydromodpy.display.report_profiles import REPORT_ARTIFACT_MANIFEST_NAME


@dataclass(frozen=True)
class CatchmentReportPipelineResult:
    overview_config: Path | None
    simulation_config: Path | None
    context_summary: Path | None
    html_report: Path | None
    postflight_report: Path | None = None
    context_artifact_manifest: Path | None = None
    overview_artifact_manifest: Path | None = None


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
    source_artifact_manifest: Path | None = None,
    source_artifact_manifests: Iterable[Path] = (),
    simulation_config_path: Path | None = None,
) -> CatchmentReportPipelineResult:
    """Run the selected report-production steps from one report config."""
    inputs = CatchmentReportInputs.from_toml(report_config)
    source_manifests = _source_manifest_paths(
        source_artifact_manifest,
        source_artifact_manifests,
    )
    existing_simulation_manifest = _existing_simulation_artifact_manifest(inputs)
    if existing_simulation_manifest is not None:
        source_manifests = _append_manifest_path(source_manifests, existing_simulation_manifest)
    simulation_source_manifest = _simulation_source_manifest(source_manifests)
    if simulation_source_manifest is not None:
        inputs = _inputs_from_source_artifact_manifest(
            inputs,
            simulation_source_manifest,
            simulation_config_path=simulation_config_path,
        )
    options = CatchmentReportBuildOptions.from_toml(report_config).with_overrides(
        run_overview=run_overview,
        run_simulation=run_simulation,
        build_context_artifacts=build_context_artifacts,
        build_report_html=build_report_html,
        no_lock=no_lock,
        stream_run_logs=stream_run_logs,
        strict_figure_postflight=strict_figure_postflight,
    )
    validate_catchment_report_preflight(
        inputs,
        run_overview=options.run_overview,
        run_simulation=options.run_simulation,
        build_context_artifacts=options.build_context_artifacts,
        build_report_html=options.build_report_html,
    )
    return _run_pipeline_steps(
        inputs,
        options,
        preset=preset,
        upstream_artifact_manifests=source_manifests,
    )


def _source_manifest_paths(
    source_artifact_manifest: Path | None,
    source_artifact_manifests: Iterable[Path],
) -> tuple[Path, ...]:
    paths: list[Path] = []
    if source_artifact_manifest is not None:
        paths.append(Path(source_artifact_manifest))
    paths.extend(Path(path) for path in source_artifact_manifests)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return tuple(deduped)


def _append_manifest_path(paths: tuple[Path, ...], path: Path) -> tuple[Path, ...]:
    resolved = Path(path).expanduser().resolve()
    if resolved in {item.expanduser().resolve() for item in paths}:
        return paths
    return (*paths, resolved)


def _simulation_source_manifest(source_manifests: tuple[Path, ...]) -> Path | None:
    inferred_manifest: Path | None = None
    for path in source_manifests:
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = _mapping(payload.get("metadata"))
        if metadata.get("artifact_scope") == "simulation.display":
            return path
        if metadata.get("artifact_scope"):
            continue
        if metadata.get("simulation_name") or path.parent.parent.name == "figures":
            inferred_manifest = inferred_manifest or path
    return inferred_manifest


def _inputs_from_source_artifact_manifest(
    inputs: CatchmentReportInputs,
    source_artifact_manifest: Path,
    *,
    simulation_config_path: Path | None,
) -> CatchmentReportInputs:
    manifest_path = Path(source_artifact_manifest).expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = _mapping(payload.get("metadata"))
    simulation_figures = manifest_path.parent
    simulation_name = str(metadata.get("simulation_name") or simulation_figures.name)
    inferred_workspace = _infer_workspace_from_figure_dir(simulation_figures)
    updates: dict[str, Any] = {
        "simulation_name": simulation_name,
        "simulation_figures": simulation_figures,
    }
    if inferred_workspace is not None:
        updates.update(
            simulation_workspace_dir=inferred_workspace,
            simulation_export=(
                inferred_workspace / "exports" / simulation_name / "timeseries.csv"
            ),
            generated_network_root=inferred_workspace / "simulations",
        )
    if simulation_config_path is not None:
        updates["transient_config"] = Path(simulation_config_path).expanduser().resolve()
    return replace(inputs, **updates)


def _infer_workspace_from_figure_dir(simulation_figures: Path) -> Path | None:
    figures_root = simulation_figures.parent
    if figures_root.name == "figures":
        return figures_root.parent
    return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _run_pipeline_steps(
    inputs: CatchmentReportInputs,
    options: CatchmentReportBuildOptions,
    *,
    preset: CatchmentReportPreset | None,
    upstream_artifact_manifests: tuple[Path, ...],
) -> CatchmentReportPipelineResult:
    overview_config = inputs.overview_config if options.run_overview else None
    simulation_config = inputs.transient_config if options.run_simulation else None
    context_summary = None
    html_report = None
    postflight_report = None
    context_artifact_manifest = _existing_context_artifact_manifest(inputs)
    overview_artifact_manifest = None

    if options.run_overview:
        _run_overview(inputs, options)
    overview_artifact_manifest = _existing_overview_artifact_manifest(inputs)
    if options.run_simulation:
        _run_simulation(inputs, options)
        simulation_artifact_manifest = _existing_simulation_artifact_manifest(inputs)
        if simulation_artifact_manifest is not None:
            upstream_artifact_manifests = _append_manifest_path(
                upstream_artifact_manifests,
                simulation_artifact_manifest,
            )
    if options.build_context_artifacts:
        context_summary = _build_context_artifacts(inputs)
        context_artifact_manifest = context_artifact_manifest_path(inputs)
        if not context_artifact_manifest.exists():
            context_artifact_manifest = None
    if options.build_report_html:
        html_source_manifests = upstream_artifact_manifests
        if overview_artifact_manifest is not None:
            html_source_manifests = (
                *html_source_manifests,
                overview_artifact_manifest,
            )
        if context_artifact_manifest is not None:
            html_source_manifests = (
                *html_source_manifests,
                context_artifact_manifest,
            )
        html_report, postflight_report = _build_report_html(
            inputs,
            options,
            preset=preset,
            upstream_artifact_manifests=html_source_manifests,
        )

    return CatchmentReportPipelineResult(
        overview_config=overview_config,
        simulation_config=simulation_config,
        context_summary=context_summary,
        html_report=html_report,
        postflight_report=postflight_report,
        context_artifact_manifest=context_artifact_manifest,
        overview_artifact_manifest=overview_artifact_manifest,
    )


def _run_overview(inputs: CatchmentReportInputs, options: CatchmentReportBuildOptions) -> None:
    _run_hydromodpy(
        inputs.overview_config,
        no_lock=options.no_lock,
        stream_logs=options.stream_run_logs,
    )


def _run_simulation(
    inputs: CatchmentReportInputs,
    options: CatchmentReportBuildOptions,
) -> None:
    _run_hydromodpy(
        inputs.transient_config,
        no_lock=options.no_lock,
        stream_logs=options.stream_run_logs,
    )
    _validate_simulation_outputs(inputs)


def _build_context_artifacts(inputs: CatchmentReportInputs) -> Path:
    return build_context(inputs)


def _existing_overview_artifact_manifest(inputs: CatchmentReportInputs) -> Path | None:
    path = overview_artifact_manifest_path(inputs.overview_figures)
    return path if path.exists() else None


def _existing_context_artifact_manifest(inputs: CatchmentReportInputs) -> Path | None:
    path = context_artifact_manifest_path(inputs)
    return path if path.exists() else None


def _existing_simulation_artifact_manifest(inputs: CatchmentReportInputs) -> Path | None:
    path = inputs.simulation_figures / REPORT_ARTIFACT_MANIFEST_NAME
    return path if path.exists() else None


def _build_report_html(
    inputs: CatchmentReportInputs,
    options: CatchmentReportBuildOptions,
    *,
    preset: CatchmentReportPreset | None,
    upstream_artifact_manifests: tuple[Path, ...],
) -> tuple[Path, Path]:
    config = CatchmentReportConfig.from_inputs(
        inputs,
        preset=preset,
        upstream_artifact_manifest=upstream_artifact_manifests[0]
        if upstream_artifact_manifests
        else None,
        upstream_artifact_manifests=upstream_artifact_manifests,
    )
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
