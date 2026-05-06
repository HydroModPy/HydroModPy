"""Persistent diagnostics for the experimental PETSc VI obstacle runtime."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.solver_diagnostics import (
    VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
    VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
    VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV,
)

VI_OBSTACLE_PERIOD_FIELDS = [
    "period_index",
    "period_label",
    "dt_period_seconds",
    "converged",
    "substeps_requested",
    "substeps_used",
    "adaptive_used",
    "attempts_count",
    "attempted_substeps_list",
    "failed_attempts_count",
    "final_snes_reason",
    "final_snes_reason_label",
    "final_ksp_reason",
    "final_ksp_reason_label",
    "total_snes_iterations",
    "max_snes_iterations_substep",
    "total_ksp_iterations",
    "max_ksp_iterations_substep",
    "active_top_count_final",
    "active_bottom_count_final",
    "free_count_final",
    "max_upper_violation_m",
    "max_lower_violation_m",
    "surface_reaction_total_final_m3_s",
    "bottom_reaction_total_final_m3_s",
    "surface_reaction_total_final_m3",
    "bottom_reaction_total_final_m3",
    "residual_norm_free_final",
    "residual_norm_projected_final",
]

VI_OBSTACLE_SUBSTEP_FIELDS = [
    "period_index",
    "attempt_index",
    "substep_index",
    "n_substeps_attempted",
    "dt_sub_seconds",
    "converged",
    "snes_reason",
    "snes_reason_label",
    "ksp_reason",
    "ksp_reason_label",
    "snes_type",
    "ksp_type",
    "pc_type",
    "pc_factor_shift_type",
    "pc_factor_shift_amount",
    "petsc_options",
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
    "residual_norm_free",
    "residual_norm_projected",
    "h_min_m",
    "h_max_m",
    "residual_min_m3_s",
    "residual_max_m3_s",
]


def is_vi_obstacle_runtime_summary(summary: Mapping[str, Any]) -> bool:
    """Return True when a Boussinesq summary belongs to the VI obstacle runtime."""
    markers = {
        str(summary.get("runtime_engine_id", "")),
        str(summary.get("runtime_formulation", "")),
        str(summary.get("surface_interaction_model_resolved", "")),
        str(summary.get("surface_interaction_model_requested", "")),
    }
    return bool(
        "petsc_vi_obstacle_snes" in markers
        or "head_only_vi_obstacle" in markers
        or "vi_obstacle" in markers
    )


def build_vi_obstacle_period_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return one flat row per period from a Boussinesq runtime summary."""
    period_diagnostics = summary.get("runtime_period_diagnostics", [])
    if not isinstance(period_diagnostics, list):
        return []
    period_lengths = _float_list(summary.get("period_lengths_seconds"))
    converged_by_period = _bool_list(summary.get("converged_by_period"))
    rows: list[dict[str, Any]] = []
    for raw in period_diagnostics:
        if not isinstance(raw, Mapping):
            continue
        period_index = _int_value(raw.get("period_index"), len(rows))
        substeps = _substep_records_from_period(raw)
        attempted = _int_list(raw.get("vi_substep_attempts"))
        failed_attempts = _failed_attempts(raw)
        row = {
            "period_index": period_index,
            "period_label": _period_label(period_index, period_lengths),
            "dt_period_seconds": _list_get(period_lengths, period_index),
            "converged": _list_get(converged_by_period, period_index, True),
            "substeps_requested": _int_value(raw.get("vi_substeps_requested"), 1),
            "substeps_used": _int_value(raw.get("vi_substeps_used"), 1),
            "adaptive_used": bool(raw.get("vi_substep_adaptive_used", False)),
            "attempts_count": len(attempted) if attempted else _attempt_count(raw),
            "attempted_substeps_list": attempted,
            "failed_attempts_count": len(failed_attempts),
            "final_snes_reason": raw.get("snes_converged_reason"),
            "final_snes_reason_label": raw.get("snes_converged_reason_label"),
            "final_ksp_reason": raw.get("ksp_converged_reason"),
            "final_ksp_reason_label": raw.get("ksp_converged_reason_label"),
            "total_snes_iterations": _int_value(
                raw.get("vi_substep_total_snes_iterations"),
                _sum_int(substeps, "snes_iterations"),
            ),
            "max_snes_iterations_substep": _max_int(substeps, "snes_iterations"),
            "total_ksp_iterations": _int_value(
                raw.get("vi_substep_total_ksp_iterations"),
                _sum_int(substeps, "ksp_iterations"),
            ),
            "max_ksp_iterations_substep": _max_int(substeps, "ksp_iterations"),
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
            "surface_reaction_total_final_m3": raw.get("surface_reaction_total_m3"),
            "bottom_reaction_total_final_m3": raw.get("bottom_reaction_total_m3"),
            "residual_norm_free_final": raw.get("free_residual_norm_inf"),
            "residual_norm_projected_final": raw.get("projected_vi_residual_norm_inf"),
        }
        rows.append(_jsonable_mapping(row))
    return rows


def build_vi_obstacle_substep_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return one flat row per attempted substep from a Boussinesq summary."""
    explicit = summary.get("runtime_substep_diagnostics")
    if isinstance(explicit, list) and explicit:
        return [_substep_row_from_raw(raw) for raw in explicit if isinstance(raw, Mapping)]

    rows: list[dict[str, Any]] = []
    period_diagnostics = summary.get("runtime_period_diagnostics", [])
    if not isinstance(period_diagnostics, list):
        return rows
    for period_offset, period in enumerate(period_diagnostics):
        if not isinstance(period, Mapping):
            continue
        period_index = _int_value(period.get("period_index"), period_offset)
        for raw in _substep_records_from_period(period):
            item = dict(raw)
            item.setdefault("period_index", period_index)
            rows.append(_substep_row_from_raw(item))
    return rows


def build_vi_obstacle_runtime_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact aggregate summary for persisted VI diagnostics."""
    period_rows = build_vi_obstacle_period_rows(summary)
    substep_rows = build_vi_obstacle_substep_rows(summary)
    total_periods = _int_value(summary.get("n_periods"), len(period_rows))
    converged_periods = [
        int(row["period_index"]) for row in period_rows if bool(row.get("converged", False))
    ]
    failed_periods = [
        int(row["period_index"]) for row in period_rows if not bool(row.get("converged", False))
    ]
    if not period_rows:
        converged_by_period = _bool_list(summary.get("converged_by_period"))
        converged_periods = [index for index, value in enumerate(converged_by_period) if value]
        failed_periods = [index for index, value in enumerate(converged_by_period) if not value]
    last_period = period_rows[-1] if period_rows else {}
    last_substep = substep_rows[-1] if substep_rows else {}
    petsc_options = last_substep.get("petsc_options") or summary.get("petsc_options")
    factor_shift_type = (
        last_substep.get("pc_factor_shift_type")
        or summary.get("pc_factor_shift_type")
        or _petsc_option_value(petsc_options, "-pc_factor_shift_type")
    )
    factor_shift_amount = last_substep.get("pc_factor_shift_amount") or summary.get(
        "pc_factor_shift_amount"
    )
    if factor_shift_amount in (None, ""):
        raw_shift_amount = _petsc_option_value(petsc_options, "-pc_factor_shift_amount")
        factor_shift_amount = (
            None if raw_shift_amount is None else _float_value(raw_shift_amount, math.nan)
        )
        if isinstance(factor_shift_amount, float) and not math.isfinite(factor_shift_amount):
            factor_shift_amount = None

    runtime = {
        "schema_version": "boussinesq_vi_obstacle_runtime_diagnostics_v1",
        "runtime_backend": summary.get("runtime_backend"),
        "runtime_engine": summary.get("runtime_engine"),
        "runtime_engine_id": summary.get("runtime_engine_id"),
        "surface_interaction_model": summary.get("surface_interaction_model_resolved"),
        "surface_interaction_model_requested": summary.get(
            "surface_interaction_model_requested"
        ),
        "snes_type": last_substep.get("snes_type") or summary.get("snes_type"),
        "ksp_type": last_substep.get("ksp_type") or summary.get("ksp_type"),
        "pc_type": last_substep.get("pc_type") or summary.get("pc_type"),
        "factor_shift_type": factor_shift_type,
        "factor_shift_amount": factor_shift_amount,
        "petsc_options": petsc_options,
        "vi_substeps_per_period": _int_value(summary.get("vi_substeps_per_period"), 1),
        "vi_substep_on_failure": bool(summary.get("vi_substep_on_failure", False)),
        "vi_max_adaptive_substeps": _int_value(summary.get("vi_max_adaptive_substeps"), 1),
        "total_periods": total_periods,
        "converged_periods": converged_periods,
        "failed_periods": failed_periods,
        "all_periods_converged": len(failed_periods) == 0 and total_periods > 0,
        "max_substeps_used": _max_int(period_rows, "substeps_used"),
        "adaptive_substepping_used_any": any(
            bool(row.get("adaptive_used", False)) for row in period_rows
        ),
        "total_snes_iterations": _sum_int(period_rows, "total_snes_iterations"),
        "max_snes_iterations_per_substep": _max_int(substep_rows, "snes_iterations"),
        "total_ksp_iterations": _sum_int(period_rows, "total_ksp_iterations"),
        "max_ksp_iterations_per_substep": _max_int(substep_rows, "ksp_iterations"),
        "max_upper_violation": _max_float(period_rows, "max_upper_violation_m"),
        "max_lower_violation": _max_float(period_rows, "max_lower_violation_m"),
        "max_active_top_count": _max_int(period_rows, "active_top_count_final"),
        "max_active_bottom_count": _max_int(period_rows, "active_bottom_count_final"),
        "final_active_top_count": last_period.get("active_top_count_final"),
        "final_active_bottom_count": last_period.get("active_bottom_count_final"),
        "final_free_count": last_period.get("free_count_final"),
        "period_diagnostic_count": len(period_rows),
        "substep_diagnostic_count": len(substep_rows),
    }
    return _jsonable_mapping(runtime)


def write_vi_obstacle_diagnostic_files(
    output_dir: Path,
    summary: Mapping[str, Any],
) -> dict[str, str]:
    """Write persistent VI obstacle diagnostics and return the generated paths."""
    if not is_vi_obstacle_runtime_summary(summary):
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_summary = build_vi_obstacle_runtime_summary(summary)
    period_rows = build_vi_obstacle_period_rows(summary)
    substep_rows = build_vi_obstacle_substep_rows(summary)

    runtime_path = output_dir / VI_OBSTACLE_RUNTIME_SUMMARY_JSON
    period_path = output_dir / VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV
    substep_path = output_dir / VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV

    runtime_path.write_text(
        json.dumps(runtime_summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(period_path, period_rows, VI_OBSTACLE_PERIOD_FIELDS)
    _write_csv(substep_path, substep_rows, VI_OBSTACLE_SUBSTEP_FIELDS)
    return {
        "runtime_summary": str(runtime_path),
        "period_diagnostics": str(period_path),
        "substep_diagnostics": str(substep_path),
    }


def _substep_row_from_raw(raw: Mapping[str, Any]) -> dict[str, Any]:
    return _jsonable_mapping(
        {
            "period_index": _int_value(raw.get("period_index"), 0),
            "attempt_index": _int_value(raw.get("attempt_index"), 0),
            "substep_index": _int_value(raw.get("substep_index"), 0),
            "n_substeps_attempted": _int_value(raw.get("n_substeps_attempted"), 1),
            "dt_sub_seconds": _float_value(raw.get("dt_sub_seconds"), 0.0),
            "converged": bool(raw.get("success", raw.get("converged", False))),
            "snes_reason": raw.get("snes_reason"),
            "snes_reason_label": raw.get("snes_reason_label"),
            "ksp_reason": raw.get("ksp_reason"),
            "ksp_reason_label": raw.get("ksp_reason_label"),
            "snes_type": raw.get("snes_type"),
            "ksp_type": raw.get("ksp_type"),
            "pc_type": raw.get("pc_type"),
            "pc_factor_shift_type": raw.get("pc_factor_shift_type"),
            "pc_factor_shift_amount": raw.get("pc_factor_shift_amount"),
            "petsc_options": raw.get("petsc_options"),
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
            "residual_norm_free": raw.get("residual_norm_free"),
            "residual_norm_projected": raw.get("residual_norm_projected"),
            "h_min_m": raw.get("h_min_m"),
            "h_max_m": raw.get("h_max_m"),
            "residual_min_m3_s": raw.get("residual_min_m3_s"),
            "residual_max_m3_s": raw.get("residual_max_m3_s"),
        }
    )


def _substep_records_from_period(period: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = period.get("vi_substep_details")
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    return []


def _failed_attempts(period: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    attempts = period.get("vi_substep_attempt_details")
    if not isinstance(attempts, list):
        return []
    return [
        item
        for item in attempts
        if isinstance(item, Mapping) and not bool(item.get("success", False))
    ]


def _attempt_count(period: Mapping[str, Any]) -> int:
    attempts = period.get("vi_substep_attempt_details")
    return len(attempts) if isinstance(attempts, list) else 1


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


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list | tuple):
        return []
    return [_int_value(item, 0) for item in value]


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


def _period_label(period_index: int, period_lengths: list[float]) -> str:
    if not period_lengths or period_index >= len(period_lengths):
        return str(period_index)
    elapsed = float(sum(period_lengths[: period_index + 1]))
    return f"{elapsed / 86400.0:.1f} d"


def _petsc_option_value(options: Any, flag: str) -> str | None:
    if not isinstance(options, str) or options.strip() == "":
        return None
    tokens = options.split()
    for index, token in enumerate(tokens):
        if token != flag:
            continue
        if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
            return tokens[index + 1]
        return ""
    return None


__all__ = [
    "VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV",
    "VI_OBSTACLE_RUNTIME_SUMMARY_JSON",
    "VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV",
    "build_vi_obstacle_period_rows",
    "build_vi_obstacle_runtime_summary",
    "build_vi_obstacle_substep_rows",
    "is_vi_obstacle_runtime_summary",
    "write_vi_obstacle_diagnostic_files",
]
