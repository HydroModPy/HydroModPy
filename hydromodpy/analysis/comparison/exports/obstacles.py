"""Boussinesq and MF6 VI obstacle diagnostics CSV exports."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.solver_diagnostics import (
    TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
    TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
    TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV,
    VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
    VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
    VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV,
)
from hydromodpy.results.storage.contract import RUN_EXPORTS_DIRNAME
from hydromodpy.results.storage.run_store import SOLVER_DIAGNOSTICS_DIRNAME

from .base import _completed_simulation_summaries, _slug_token, _write_csv
from .budget import (
    BOUSSINESQ_OBSTACLE_DIAGNOSTICS_FIELDS,
    _load_boussinesq_obstacle_diagnostic_rows,
)


def write_boussinesq_obstacle_diagnostics_export(
    *,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write per-snapshot Boussinesq obstacle diagnostics when available."""
    from hydromodpy.analysis.comparison.runtime.run_source import open_run_source

    rows: list[dict[str, Any]] = []
    for summary in _completed_simulation_summaries(simulation_summaries):
        source = open_run_source(summary)
        if source is None:
            continue
        with source:
            rows.extend(
                _load_boussinesq_obstacle_diagnostic_rows(
                    summary, store=source, sim_id=source.sim_id
                )
            )

    artifacts: list[dict[str, Any]] = []
    if not rows:
        return artifacts, rows

    path = comparison_root / "boussinesq_obstacle_diagnostics.csv"
    _write_csv(path, rows, BOUSSINESQ_OBSTACLE_DIAGNOSTICS_FIELDS)
    artifacts.append({"kind": "boussinesq_obstacle_diagnostics_csv", "path": str(path)})
    return artifacts, rows


def _diagnostic_paths(summary: Mapping[str, Any], names: Mapping[str, str]) -> dict[str, Path]:
    """Return the solver diagnostics files the run exported, keyed by role."""
    run_dir_raw = summary.get("run_dir")
    if run_dir_raw in (None, ""):
        return {}
    directory = Path(str(run_dir_raw)) / RUN_EXPORTS_DIRNAME / SOLVER_DIAGNOSTICS_DIRNAME
    if not (directory / names["runtime_summary"]).is_file():
        return {}
    return {key: directory / name for key, name in names.items() if (directory / name).is_file()}


def _vi_obstacle_diagnostic_paths(summary: Mapping[str, Any]) -> dict[str, Path]:
    """Return the VI obstacle diagnostics of one compared run."""
    return _diagnostic_paths(
        summary,
        {
            "runtime_summary": VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
            "period_diagnostics": VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
            "substep_diagnostics": VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV,
        },
    )


def _load_vi_obstacle_runtime_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ts_vi_obstacle_diagnostic_paths(summary: Mapping[str, Any]) -> dict[str, Path]:
    """Return the TS VI obstacle diagnostics of one compared run."""
    return _diagnostic_paths(
        summary,
        {
            "runtime_summary": TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
            "period_diagnostics": TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
            "step_diagnostics": TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV,
        },
    )


def write_vi_obstacle_runtime_diagnostics_export(
    *,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Copy persisted VI obstacle runtime diagnostics into the comparison root."""
    artifacts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for summary in _completed_simulation_summaries(simulation_summaries):
        paths = _vi_obstacle_diagnostic_paths(summary)
        runtime_path = paths.get("runtime_summary")
        if runtime_path is None:
            continue
        simulation_id = str(summary.get("id", "simulation") or "simulation")
        slug = _slug_token(simulation_id)
        runtime_payload = _load_vi_obstacle_runtime_summary(runtime_path)

        copied: dict[str, str] = {}
        for key, filename in (
            ("runtime_summary", VI_OBSTACLE_RUNTIME_SUMMARY_JSON),
            ("period_diagnostics", VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV),
            ("substep_diagnostics", VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV),
        ):
            source = paths.get(key)
            if source is None:
                continue
            destination = comparison_root / f"{slug}__{filename}"
            shutil.copyfile(source, destination)
            copied[key] = str(destination)
            artifacts.append(
                {
                    "kind": f"vi_obstacle_{key}",
                    "simulation_id": simulation_id,
                    "path": str(destination),
                    "source_path": str(source),
                    "summary": runtime_payload if key == "runtime_summary" else {},
                }
            )
        if copied:
            rows.append(
                {
                    "simulation_id": simulation_id,
                    "simulation_label": summary.get("label", simulation_id),
                    "runtime_summary": copied.get("runtime_summary", ""),
                    "period_diagnostics": copied.get("period_diagnostics", ""),
                    "substep_diagnostics": copied.get("substep_diagnostics", ""),
                    **runtime_payload,
                }
            )
    return artifacts, rows


def write_ts_vi_obstacle_runtime_diagnostics_export(
    *,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Copy persisted TS VI obstacle runtime diagnostics into the comparison root."""
    artifacts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for summary in _completed_simulation_summaries(simulation_summaries):
        paths = _ts_vi_obstacle_diagnostic_paths(summary)
        runtime_path = paths.get("runtime_summary")
        if runtime_path is None:
            continue
        simulation_id = str(summary.get("id", "simulation") or "simulation")
        slug = _slug_token(simulation_id)
        runtime_payload = _load_vi_obstacle_runtime_summary(runtime_path)

        copied: dict[str, str] = {}
        for key, filename in (
            ("runtime_summary", TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON),
            ("period_diagnostics", TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV),
            ("step_diagnostics", TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV),
        ):
            source = paths.get(key)
            if source is None:
                continue
            destination = comparison_root / f"{slug}__{filename}"
            shutil.copyfile(source, destination)
            copied[key] = str(destination)
            artifacts.append(
                {
                    "kind": f"ts_vi_obstacle_{key}",
                    "simulation_id": simulation_id,
                    "path": str(destination),
                    "source_path": str(source),
                    "summary": runtime_payload if key == "runtime_summary" else {},
                }
            )
        if copied:
            rows.append(
                {
                    "simulation_id": simulation_id,
                    "simulation_label": summary.get("label", simulation_id),
                    "runtime_summary": copied.get("runtime_summary", ""),
                    "period_diagnostics": copied.get("period_diagnostics", ""),
                    "step_diagnostics": copied.get("step_diagnostics", ""),
                    **runtime_payload,
                }
            )
    return artifacts, rows
