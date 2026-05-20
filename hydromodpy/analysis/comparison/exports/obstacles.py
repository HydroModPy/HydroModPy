"""Boussinesq and MF6 VI obstacle diagnostics CSV exports."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.solver_diagnostics import (
    TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
    TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
    TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV,
    VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
    VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
    VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV,
)

from .base import _completed_simulation_summaries, _slug_token, _write_csv
from .budget import (
    BOUSSINESQ_OBSTACLE_DIAGNOSTICS_FIELDS,
    _load_boussinesq_obstacle_diagnostic_rows,
)

if TYPE_CHECKING:
    pass


def write_boussinesq_obstacle_diagnostics_export(
    *,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write per-snapshot Boussinesq obstacle diagnostics when available."""
    from hydromodpy.analysis.comparison.runtime import discover_result_store

    rows: list[dict[str, Any]] = []
    for summary in _completed_simulation_summaries(simulation_summaries):
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(None if preferred_sim_id in (None, "") else str(preferred_sim_id)),
            preferred_name=(None if preferred_run_name in (None, "") else str(preferred_run_name)),
        )
        try:
            rows.extend(
                _load_boussinesq_obstacle_diagnostic_rows(
                    summary,
                    store=store,
                    sim_id=sim_id,
                )
            )
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass

    artifacts: list[dict[str, Any]] = []
    if not rows:
        return artifacts, rows

    path = comparison_root / "boussinesq_obstacle_diagnostics.csv"
    _write_csv(path, rows, BOUSSINESQ_OBSTACLE_DIAGNOSTICS_FIELDS)
    artifacts.append({"kind": "boussinesq_obstacle_diagnostics_csv", "path": str(path)})
    return artifacts, rows


def _vi_obstacle_diagnostic_paths(summary: Mapping[str, Any]) -> dict[str, Path]:
    """Return persisted VI obstacle diagnostics for one simulation summary."""
    raw = summary.get("vi_obstacle_diagnostics")
    paths: dict[str, Path] = {}
    if isinstance(raw, Mapping):
        for key in ("runtime_summary", "period_diagnostics", "substep_diagnostics"):
            value = raw.get(key)
            if value not in (None, ""):
                candidate = Path(str(value))
                if candidate.exists():
                    paths[key] = candidate
    if paths:
        return paths

    run_folder_raw = summary.get("run_folder")
    if run_folder_raw in (None, ""):
        return {}
    run_folder = Path(str(run_folder_raw))
    for runtime_path in run_folder.glob(
        f"exports/*/solver_diagnostics/{VI_OBSTACLE_RUNTIME_SUMMARY_JSON}"
    ):
        directory = runtime_path.parent
        paths["runtime_summary"] = runtime_path
        period_path = directory / VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV
        substep_path = directory / VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV
        if period_path.exists():
            paths["period_diagnostics"] = period_path
        if substep_path.exists():
            paths["substep_diagnostics"] = substep_path
        return paths
    return {}


def _load_vi_obstacle_runtime_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ts_vi_obstacle_diagnostic_paths(summary: Mapping[str, Any]) -> dict[str, Path]:
    """Return persisted TS VI obstacle diagnostics for one simulation summary."""
    raw = summary.get("ts_vi_obstacle_diagnostics")
    paths: dict[str, Path] = {}
    if isinstance(raw, Mapping):
        for key in ("runtime_summary", "period_diagnostics", "step_diagnostics"):
            value = raw.get(key)
            if value not in (None, ""):
                candidate = Path(str(value))
                if candidate.exists():
                    paths[key] = candidate
    if paths:
        return paths

    run_folder_raw = summary.get("run_folder")
    if run_folder_raw in (None, ""):
        return {}
    run_folder = Path(str(run_folder_raw))
    for runtime_path in run_folder.glob(
        f"exports/*/solver_diagnostics/{TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON}"
    ):
        directory = runtime_path.parent
        paths["runtime_summary"] = runtime_path
        period_path = directory / TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV
        step_path = directory / TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV
        if period_path.exists():
            paths["period_diagnostics"] = period_path
        if step_path.exists():
            paths["step_diagnostics"] = step_path
        return paths
    return {}


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
