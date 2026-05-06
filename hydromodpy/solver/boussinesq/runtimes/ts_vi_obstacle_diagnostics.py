"""Persistent diagnostics for the experimental PETSc TS VI obstacle runtime."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np


TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON = "ts_vi_obstacle_runtime_summary.json"
TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV = "ts_vi_obstacle_period_diagnostics.csv"
TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV = "ts_vi_obstacle_step_diagnostics.csv"

TS_VI_OBSTACLE_PERIOD_FIELDS = [
    "period_index",
    "t_start_seconds",
    "t_end_seconds",
    "dt_period_seconds",
    "ts_steps_taken",
    "dt_initial_seconds",
    "dt_min_seconds",
    "dt_max_seconds",
    "converged",
    "ts_reason",
    "ts_reason_label",
    "snes_reason_final",
    "snes_reason_label_final",
    "total_snes_iterations",
    "total_ksp_iterations",
    "active_top_count_final",
    "active_bottom_count_final",
    "free_count_final",
    "max_upper_violation_m",
    "max_lower_violation_m",
    "surface_reaction_total_final_m3_s",
    "bottom_reaction_total_final_m3_s",
    "surface_reaction_total_m3",
    "bottom_reaction_total_m3",
]

TS_VI_OBSTACLE_STEP_FIELDS = [
    "period_index",
    "ts_step_index",
    "t_seconds",
    "dt_seconds",
    "converged_or_accepted",
    "ts_reason",
    "ts_reason_label",
    "snes_iterations",
    "ksp_iterations",
    "active_top_count",
    "active_bottom_count",
    "free_count",
    "max_upper_violation_m",
    "max_lower_violation_m",
    "surface_reaction_total_m3_s",
    "bottom_reaction_total_m3_s",
    "surface_reaction_total_m3",
    "bottom_reaction_total_m3",
    "h_min_m",
    "h_max_m",
    "residual_min_m3_s",
    "residual_max_m3_s",
    "snes_type",
    "ksp_type",
    "pc_type",
    "pc_factor_shift_type",
    "pc_factor_shift_amount",
    "petsc_options",
]


def is_ts_vi_obstacle_runtime_summary(summary: Mapping[str, Any]) -> bool:
    """Return True when a Boussinesq summary belongs to the TS VI runtime."""
    markers = {
        str(summary.get("runtime_engine_id", "")),
        str(summary.get("runtime_formulation", "")),
        str(summary.get("surface_interaction_model_resolved", "")),
        str(summary.get("surface_interaction_model_requested", "")),
    }
    return bool(
        "petsc_ts_vi_obstacle" in markers
        or "head_only_ts_vi_obstacle" in markers
        or "ts_vi_obstacle" in markers
    )


def build_ts_vi_obstacle_step_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return one flat row per accepted PETSc TS step."""
    raw_steps = summary.get("runtime_ts_step_diagnostics")
    if not isinstance(raw_steps, list):
        return []
    return [_step_row(raw) for raw in raw_steps if isinstance(raw, Mapping)]


def build_ts_vi_obstacle_period_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return one flat row per HydroModPy stress period."""
    period_diagnostics = summary.get("runtime_period_diagnostics", [])
    if not isinstance(period_diagnostics, list):
        return []
    period_lengths = _float_list(summary.get("period_lengths_seconds"))
    converged_by_period = _bool_list(summary.get("converged_by_period"))
    rows: list[dict[str, Any]] = []
    elapsed_start = 0.0
    for raw in period_diagnostics:
        if not isinstance(raw, Mapping):
            continue
        period_index = _int_value(raw.get("period_index"), len(rows))
        dt_period = _list_get(period_lengths, period_index, raw.get("dt_period_seconds"))
        dt_period_value = _float_value(dt_period, 0.0)
        t_start = sum(period_lengths[:period_index]) if period_lengths else elapsed_start
        t_end = t_start + dt_period_value
        row = {
            "period_index": period_index,
            "t_start_seconds": t_start,
            "t_end_seconds": t_end,
            "dt_period_seconds": dt_period_value,
            "ts_steps_taken": _int_value(raw.get("ts_steps_taken"), 0),
            "dt_initial_seconds": _float_value(raw.get("dt_initial_seconds"), 0.0),
            "dt_min_seconds": _float_value(raw.get("dt_min_seconds"), 0.0),
            "dt_max_seconds": _float_value(raw.get("dt_max_seconds"), 0.0),
            "converged": _list_get(converged_by_period, period_index, True),
            "ts_reason": raw.get("ts_converged_reason"),
            "ts_reason_label": raw.get("ts_converged_reason_label"),
            "snes_reason_final": raw.get("snes_converged_reason"),
            "snes_reason_label_final": raw.get("snes_converged_reason_label"),
            "total_snes_iterations": _int_value(raw.get("total_snes_iterations"), 0),
            "total_ksp_iterations": _int_value(raw.get("total_ksp_iterations"), 0),
            "active_top_count_final": _int_value(raw.get("surface_active_cells"), 0),
            "active_bottom_count_final": _int_value(raw.get("bottom_active_cells"), 0),
            "free_count_final": _int_value(raw.get("free_cells"), 0),
            "max_upper_violation_m": _float_value(raw.get("max_violation_upper_m"), 0.0),
            "max_lower_violation_m": _float_value(raw.get("max_violation_lower_m"), 0.0),
            "surface_reaction_total_final_m3_s": _float_value(
                raw.get("surface_reaction_total_m3_s"),
                0.0,
            ),
            "bottom_reaction_total_final_m3_s": _float_value(
                raw.get("bottom_reaction_total_m3_s"),
                0.0,
            ),
            "surface_reaction_total_m3": raw.get("surface_reaction_total_m3"),
            "bottom_reaction_total_m3": raw.get("bottom_reaction_total_m3"),
        }
        rows.append(_jsonable_mapping(row))
        elapsed_start = t_end
    return rows


def build_ts_vi_obstacle_runtime_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact aggregate summary for persisted TS VI diagnostics."""
    period_rows = build_ts_vi_obstacle_period_rows(summary)
    step_rows = build_ts_vi_obstacle_step_rows(summary)
    total_periods = _int_value(summary.get("n_periods"), len(period_rows))
    failed_periods = [
        int(row["period_index"]) for row in period_rows if not bool(row.get("converged", False))
    ]
    converged_periods = [
        int(row["period_index"]) for row in period_rows if bool(row.get("converged", False))
    ]
    last_period = period_rows[-1] if period_rows else {}
    last_step = step_rows[-1] if step_rows else {}
    runtime = {
        "schema_version": "boussinesq_ts_vi_obstacle_runtime_diagnostics_v1",
        "runtime_backend": summary.get("runtime_backend"),
        "runtime_engine": summary.get("runtime_engine"),
        "runtime_engine_id": summary.get("runtime_engine_id"),
        "runtime_engine_id_expected": "petsc_ts_vi_obstacle",
        "surface_interaction_model": summary.get("surface_interaction_model_resolved"),
        "ts_type": last_period.get("ts_type") or summary.get("ts_vi_type"),
        "ts_adapt_type": last_period.get("ts_adapt_type") or ("none" if not summary.get("ts_vi_adapt") else ""),
        "ts_vi_steps_per_period": _int_value(summary.get("ts_vi_steps_per_period"), 4),
        "ts_vi_adapt": bool(summary.get("ts_vi_adapt", False)),
        "snes_type": last_step.get("snes_type") or summary.get("ts_vi_snes_type"),
        "ksp_type": last_step.get("ksp_type"),
        "pc_type": last_step.get("pc_type"),
        "factor_shift_type": last_step.get("pc_factor_shift_type"),
        "factor_shift_amount": last_step.get("pc_factor_shift_amount"),
        "petsc_options": last_step.get("petsc_options"),
        "total_periods": total_periods,
        "all_periods_converged": len(failed_periods) == 0 and total_periods > 0,
        "converged_periods": converged_periods,
        "failed_periods": failed_periods,
        "total_ts_steps": len(step_rows),
        "total_snes_iterations": _sum_int(period_rows, "total_snes_iterations"),
        "max_snes_iterations_per_ts_step": _max_int(step_rows, "snes_iterations"),
        "total_ksp_iterations": _sum_int(period_rows, "total_ksp_iterations"),
        "max_ksp_iterations_per_ts_step": _max_int(step_rows, "ksp_iterations"),
        "max_upper_violation": _max_float(period_rows, "max_upper_violation_m"),
        "max_lower_violation": _max_float(period_rows, "max_lower_violation_m"),
        "max_active_top_count": _max_int(period_rows, "active_top_count_final"),
        "max_active_bottom_count": _max_int(period_rows, "active_bottom_count_final"),
        "final_active_top_count": last_period.get("active_top_count_final"),
        "final_active_bottom_count": last_period.get("active_bottom_count_final"),
        "final_free_count": last_period.get("free_count_final"),
        "period_diagnostic_count": len(period_rows),
        "step_diagnostic_count": len(step_rows),
    }
    return _jsonable_mapping(runtime)


def write_ts_vi_obstacle_diagnostic_files(
    output_dir: Path,
    summary: Mapping[str, Any],
) -> dict[str, str]:
    """Write persistent TS VI diagnostics and return generated paths."""
    if not is_ts_vi_obstacle_runtime_summary(summary):
        return {}
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_summary = build_ts_vi_obstacle_runtime_summary(summary)
    period_rows = build_ts_vi_obstacle_period_rows(summary)
    step_rows = build_ts_vi_obstacle_step_rows(summary)
    runtime_path = output_dir / TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON
    period_path = output_dir / TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV
    step_path = output_dir / TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV
    runtime_path.write_text(
        json.dumps(runtime_summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(period_path, period_rows, TS_VI_OBSTACLE_PERIOD_FIELDS)
    _write_csv(step_path, step_rows, TS_VI_OBSTACLE_STEP_FIELDS)
    return {
        "runtime_summary": str(runtime_path),
        "period_diagnostics": str(period_path),
        "step_diagnostics": str(step_path),
    }


def _step_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    return _jsonable_mapping(
        {
            "period_index": _int_value(raw.get("period_index"), 0),
            "ts_step_index": _int_value(raw.get("ts_step_index"), 0),
            "t_seconds": _float_value(raw.get("t_seconds"), 0.0),
            "dt_seconds": _float_value(raw.get("dt_seconds"), 0.0),
            "converged_or_accepted": bool(raw.get("converged_or_accepted", False)),
            "ts_reason": raw.get("ts_reason"),
            "ts_reason_label": raw.get("ts_reason_label"),
            "snes_iterations": _int_value(raw.get("snes_iterations"), 0),
            "ksp_iterations": _int_value(raw.get("ksp_iterations"), 0),
            "active_top_count": _int_value(raw.get("active_top_count"), 0),
            "active_bottom_count": _int_value(raw.get("active_bottom_count"), 0),
            "free_count": _int_value(raw.get("free_count"), 0),
            "max_upper_violation_m": _float_value(raw.get("max_upper_violation_m"), 0.0),
            "max_lower_violation_m": _float_value(raw.get("max_lower_violation_m"), 0.0),
            "surface_reaction_total_m3_s": _float_value(
                raw.get("surface_reaction_total_m3_s"),
                0.0,
            ),
            "bottom_reaction_total_m3_s": _float_value(
                raw.get("bottom_reaction_total_m3_s"),
                0.0,
            ),
            "surface_reaction_total_m3": raw.get("surface_reaction_total_m3"),
            "bottom_reaction_total_m3": raw.get("bottom_reaction_total_m3"),
            "h_min_m": raw.get("h_min_m"),
            "h_max_m": raw.get("h_max_m"),
            "residual_min_m3_s": raw.get("residual_min_m3_s"),
            "residual_max_m3_s": raw.get("residual_max_m3_s"),
            "snes_type": raw.get("snes_type"),
            "ksp_type": raw.get("ksp_type"),
            "pc_type": raw.get("pc_type"),
            "pc_factor_shift_type": raw.get("pc_factor_shift_type"),
            "pc_factor_shift_amount": raw.get("pc_factor_shift_amount"),
            "petsc_options": raw.get("petsc_options"),
        }
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool | int | float | str):
        return value
    return json.dumps(_jsonable(value), ensure_ascii=True)


def _jsonable_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _jsonable(value) for key, value in values.items()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list | tuple):
        return []
    return [_float_value(item, math.nan) for item in value]


def _bool_list(value: Any) -> list[bool]:
    if not isinstance(value, list | tuple):
        return []
    return [bool(item) for item in value]


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _float_value(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _sum_int(rows: list[Mapping[str, Any]], key: str) -> int:
    return int(sum(_int_value(row.get(key), 0) for row in rows))


def _max_int(rows: list[Mapping[str, Any]], key: str) -> int:
    values = [_int_value(row.get(key), 0) for row in rows]
    return int(max(values)) if values else 0


def _max_float(rows: list[Mapping[str, Any]], key: str) -> float:
    values = [_float_value(row.get(key), 0.0) for row in rows]
    return float(max(values)) if values else 0.0


def _list_get(values: list[Any], index: int, default: Any = None) -> Any:
    if 0 <= int(index) < len(values):
        return values[int(index)]
    return default


__all__ = [
    "TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV",
    "TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON",
    "TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV",
    "build_ts_vi_obstacle_period_rows",
    "build_ts_vi_obstacle_runtime_summary",
    "build_ts_vi_obstacle_step_rows",
    "is_ts_vi_obstacle_runtime_summary",
    "write_ts_vi_obstacle_diagnostic_files",
]
