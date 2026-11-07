"""Orchestrate catchment report artifact production from one TOML config."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import DataContractViolation, NothingThereError
from hydromodpy.display.catchment_report.artifacts import (
    REPO_ROOT,
    draw_missing_run_figures,
    rel,
)
from hydromodpy.display.catchment_report.blocks import optional_figure_ids
from hydromodpy.display.catchment_report.builder import (
    CatchmentReportConfig,
    CatchmentReportPreset,
    build_catchment_report,
)
from hydromodpy.display.catchment_report.context import build_context
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs


@dataclass(frozen=True)
class MissingCatchmentReportInput:
    label: str
    path: Path
    kind: str


class CatchmentReportPreflightError(NothingThereError):
    """Raised when the selected catchment report steps cannot start safely."""

    def __init__(self, missing: tuple[MissingCatchmentReportInput, ...]) -> None:
        self.missing = missing
        details = "\n".join(f"- {item.label}: {item.path}" for item in missing)
        super().__init__(
            f"Catchment report preflight failed. Required inputs were not found:\n{details}"
        )


def validate_catchment_report_preflight(
    inputs: CatchmentReportInputs,
    *,
    run_overview: bool,
    run_simulation: bool,
    build_context_artifacts: bool,
    build_report_html: bool,
) -> None:
    """Validate required existing inputs for the selected pipeline steps."""
    missing: list[MissingCatchmentReportInput] = []

    if run_overview:
        _require_file(missing, "overview config", inputs.overview_config)
    if run_simulation or build_context_artifacts or build_report_html:
        _require_file(missing, "simulation config", inputs.transient_config)

    # The context and the page are written into the run: it must exist first.
    if (build_context_artifacts or build_report_html) and not run_simulation:
        _require_simulation_run(missing, inputs)

    if build_report_html:
        if not build_context_artifacts:
            _require_file(missing, "context summary", inputs.context_summary)

    if missing:
        raise CatchmentReportPreflightError(_dedupe(missing))


def _require_file(
    missing: list[MissingCatchmentReportInput],
    label: str,
    path: Path,
) -> None:
    if not path.is_file():
        missing.append(MissingCatchmentReportInput(label, path, "file"))


def _require_simulation_run(
    missing: list[MissingCatchmentReportInput],
    inputs: CatchmentReportInputs,
) -> None:
    """Require the run itself, which is what the report reads its series from."""
    from hydromodpy.display.catchment_report.simulation_source import simulation_run_exists

    if not simulation_run_exists(inputs):
        missing.append(
            MissingCatchmentReportInput(
                f"simulation run '{inputs.simulation_name}'",
                inputs.run_dir,
                "completed run",
            )
        )


def _dedupe(
    missing: list[MissingCatchmentReportInput],
) -> tuple[MissingCatchmentReportInput, ...]:
    seen: set[tuple[str, Path, str]] = set()
    deduped: list[MissingCatchmentReportInput] = []
    for item in missing:
        key = (item.label, item.path, item.kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return tuple(deduped)


class CatchmentReportPostflightError(DataContractViolation, RuntimeError):
    """Raised when strict figure postflight detects incomplete report figures.

    A :class:`DataContractViolation`, so the command exits with the code of a
    refused input (16), not the generic 1. Still a ``RuntimeError``, for the
    callers written when this was one.
    """

    def __init__(self, postflight_path: Path, missing: tuple[str, ...]) -> None:
        self.postflight_path = postflight_path
        self.missing = missing
        details = "\n".join(f"- {figure_id}" for figure_id in missing)
        super().__init__(
            "Catchment report figure postflight failed. Missing expected figures:\n"
            f"{details}\nPostflight report: {postflight_path}"
        )


def write_figure_postflight_report(
    config: Any,
    *,
    strict: bool,
) -> Path:
    """Write a figure-completeness report and optionally fail on missing figures."""
    manifest_path = config.output_dir / "block_report_manifest.json"
    postflight_path = config.output_dir / "block_report_postflight.json"
    manifest = _load_manifest(manifest_path)
    expected = _expected_figure_ids(config, manifest)
    copied = _copied_figures(manifest)
    present = tuple(sorted(figure_id for figure_id in expected if figure_id in copied))
    missing = tuple(sorted(figure_id for figure_id in expected if figure_id not in copied))
    dangling = tuple(
        sorted(figure_id for figure_id, path in copied.items() if not _resolve_path(path).exists())
    )
    payload = {
        "report_type": "catchment_report_figure_postflight",
        "strict": strict,
        "manifest": rel(manifest_path),
        "expected_count": len(expected),
        "copied_count": len(copied),
        "present_count": len(present),
        "missing_count": len(missing),
        "dangling_count": len(dangling),
        "expected_figures": list(expected),
        "present_figures": list(present),
        "missing_figures": list(missing),
        "dangling_figures": list(dangling),
        "copied_figures": copied,
    }
    postflight_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    failures = tuple(sorted({*missing, *dangling}))
    if strict and failures:
        raise CatchmentReportPostflightError(postflight_path, failures)
    return postflight_path


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _expected_figure_ids(config: Any, manifest: dict[str, Any]) -> tuple[str, ...]:
    from_manifest = manifest.get("expected_figure_ids")
    if isinstance(from_manifest, list):
        return tuple(sorted(str(item) for item in from_manifest))
    specs = (
        config.artifact_specs if config.artifact_specs is not None else config.preset.artifact_specs
    )
    block_specs = getattr(config, "block_specs", None)
    if block_specs is None:
        block_specs = config.preset.block_specs
    optional = optional_figure_ids(block_specs)
    return tuple(sorted(spec.figure_id for spec in specs if spec.figure_id not in optional))


def _copied_figures(manifest: dict[str, Any]) -> dict[str, str]:
    copied = manifest.get("copied_figures")
    if not isinstance(copied, dict):
        return {}
    return {str(key): str(value) for key, value in copied.items()}


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


@dataclass(frozen=True)
class CatchmentReportPipelineResult:
    overview_config: Path | None
    simulation_config: Path | None
    context_summary: Path | None
    html_report: Path | None
    postflight_report: Path | None = None


def run_catchment_report_pipeline(
    report_config: Path,
    *,
    preset: CatchmentReportPreset | None = None,
    run_overview: bool | None = None,
    run_simulation: bool | None = None,
    build_context_artifacts: bool | None = None,
    build_report_html: bool | None = None,
    stream_run_logs: bool | None = None,
    strict_figure_postflight: bool | None = None,
) -> CatchmentReportPipelineResult:
    """Run the selected report-production steps from one report config.

    A step given here wins over the ``[pipeline]`` table of the report file;
    one left at None keeps what the file says.
    """
    steps = {
        "run_overview": run_overview,
        "run_simulation": run_simulation,
        "build_context_artifacts": build_context_artifacts,
        "build_report_html": build_report_html,
        "stream_run_logs": stream_run_logs,
        "strict_figure_postflight": strict_figure_postflight,
    }
    inputs = replace(
        CatchmentReportInputs.from_toml(report_config),
        **{f"pipeline_{name}": value for name, value in steps.items() if value is not None},
    )
    validate_catchment_report_preflight(
        inputs,
        run_overview=inputs.pipeline_run_overview,
        run_simulation=inputs.pipeline_run_simulation,
        build_context_artifacts=inputs.pipeline_build_context_artifacts,
        build_report_html=inputs.pipeline_build_report_html,
    )
    overview_config = inputs.overview_config if inputs.pipeline_run_overview else None
    simulation_config = inputs.transient_config if inputs.pipeline_run_simulation else None
    context_summary = None
    html_report = None
    postflight_report = None

    if inputs.pipeline_run_overview:
        _run_hydromodpy(inputs.overview_config, stream_logs=inputs.pipeline_stream_run_logs)
    if inputs.pipeline_run_simulation:
        _run_hydromodpy(inputs.transient_config, stream_logs=inputs.pipeline_stream_run_logs)
        _validate_simulation_outputs(_newest_report_run(inputs))
    # A rerun, or a run after a failed one that kept the name, registers as
    # `<name>.vN`: the report describes the newest completed run of the name.
    inputs = _newest_report_run(inputs)
    if inputs.pipeline_build_context_artifacts or inputs.pipeline_build_report_html:
        # The context and the page copy the run figures: draw the ones it lacks first.
        draw_missing_run_figures(inputs)
    if inputs.pipeline_build_context_artifacts:
        context_summary = build_context(inputs)
    if inputs.pipeline_build_report_html:
        config = CatchmentReportConfig.from_inputs(inputs, preset=preset)
        html_report = build_catchment_report(config)
        postflight_report = write_figure_postflight_report(
            config, strict=inputs.pipeline_strict_figure_postflight
        )

    return CatchmentReportPipelineResult(
        overview_config=overview_config,
        simulation_config=simulation_config,
        context_summary=context_summary,
        html_report=html_report,
        postflight_report=postflight_report,
    )


def _newest_report_run(inputs: CatchmentReportInputs) -> CatchmentReportInputs:
    from hydromodpy.display.catchment_report.simulation_source import newest_completed_run_name

    name = newest_completed_run_name(inputs)
    return inputs if name is None else inputs.with_simulation_name(name)


def _run_hydromodpy(config_path: Path, *, stream_logs: bool) -> None:
    command = [sys.executable, "-m", "hydromodpy", "run", str(config_path)]
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
    from hydromodpy.display.catchment_report.simulation_source import simulation_run_exists

    missing = []
    if not simulation_run_exists(inputs):
        missing.append(f"completed simulation run '{inputs.simulation_name}': {inputs.run_dir}")
    if not inputs.simulation_figures.exists():
        missing.append(f"simulation figures directory: {inputs.simulation_figures}")
    if missing:
        details = "\n".join(f"- {item}" for item in missing)
        raise FileNotFoundError(
            "Simulation completed but the catchment report expected outputs "
            f"were not found:\n{details}"
        )
