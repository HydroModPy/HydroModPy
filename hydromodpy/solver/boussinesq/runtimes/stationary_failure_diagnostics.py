"""Persistent diagnostics for failed Boussinesq stationary solves."""

from __future__ import annotations

import csv
import json
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.solver_diagnostics import (
    STATIONARY_FAILURE_ACTIVE_SET_SUMMARY_CSV,
    STATIONARY_FAILURE_CELLS_TOP_RESIDUAL_CSV,
    STATIONARY_FAILURE_FIELD_STATS_JSON,
    STATIONARY_FAILURE_SUMMARY_JSON,
)
from hydromodpy.solver.boussinesq.assembly import BoussinesqAssembly
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    RuntimeSolveResult,
)
from hydromodpy.solver.boussinesq.runtimes.dry_equilibrium import (
    detect_dry_equilibrium,
    effective_saturated_thickness,
    physical_saturated_thickness,
    saturated_thickness_diagnostics,
)

_DEFAULT_TOP_N_RESIDUAL_CELLS = 500
_OBSTACLE_ACTIVE_TOL_M = 1.0e-9

STATIONARY_FAILURE_CELL_FIELDS = [
    "cell_id",
    "x",
    "y",
    "area",
    "K",
    "z_bottom",
    "z_top",
    "h",
    "h_minus_z_top",
    "h_minus_z_bottom",
    "residual",
    "projected_residual",
    "active_state",
    "saturated_thickness",
    "transmissivity",
    "drainage_rate",
    "surface_reaction",
    "bottom_reaction",
    "n_neighbors",
    "local_mesh_quality",
]

STATIONARY_FAILURE_ACTIVE_SET_FIELDS = [
    "active_state",
    "count",
    "fraction",
    "max_abs_residual",
    "max_abs_projected_residual",
    "area_min",
    "area_max",
    "K_min",
    "K_max",
    "saturated_thickness_min",
    "saturated_thickness_max",
]


def write_stationary_failure_diagnostics(
    output_dir: Path,
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    runtime_backend: object,
    options: NonlinearRuntimeOptions,
    runtime_summary: Mapping[str, Any],
    case_id: str | None = None,
    simulation_id: str | None = None,
    initialization_strategy: Mapping[str, Any] | None = None,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    top_n_cells: int = _DEFAULT_TOP_N_RESIDUAL_CELLS,
) -> dict[str, str]:
    """Write stationary failure diagnostics and return generated paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary, cell_rows, active_rows, field_stats = build_stationary_failure_diagnostics(
        mesh=mesh,
        result=result,
        runtime_backend=runtime_backend,
        options=options,
        runtime_summary=runtime_summary,
        case_id=case_id,
        simulation_id=simulation_id,
        initialization_strategy=initialization_strategy,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        top_n_cells=top_n_cells,
    )

    summary_path = output_dir / STATIONARY_FAILURE_SUMMARY_JSON
    cells_path = output_dir / STATIONARY_FAILURE_CELLS_TOP_RESIDUAL_CSV
    active_path = output_dir / STATIONARY_FAILURE_ACTIVE_SET_SUMMARY_CSV
    stats_path = output_dir / STATIONARY_FAILURE_FIELD_STATS_JSON

    summary_path.write_text(
        json.dumps(_jsonable(summary), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(cells_path, cell_rows, STATIONARY_FAILURE_CELL_FIELDS)
    _write_csv(active_path, active_rows, STATIONARY_FAILURE_ACTIVE_SET_FIELDS)
    stats_path.write_text(
        json.dumps(_jsonable(field_stats), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return {
        "summary": str(summary_path),
        "cells_top_residual": str(cells_path),
        "active_set_summary": str(active_path),
        "field_stats": str(stats_path),
    }


def build_stationary_failure_diagnostics(
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    runtime_backend: object,
    options: NonlinearRuntimeOptions,
    runtime_summary: Mapping[str, Any],
    case_id: str | None = None,
    simulation_id: str | None = None,
    initialization_strategy: Mapping[str, Any] | None = None,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    top_n_cells: int = _DEFAULT_TOP_N_RESIDUAL_CELLS,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return summary, per-cell rows, active-set rows and field stats."""
    assembly = result.assembly
    head = _array(result.head_m, mesh.n_cells, default=np.nan)
    z_bottom = _array(mesh.z_bottom_m, mesh.n_cells, default=np.nan)
    z_top = _array(mesh.z_top_m, mesh.n_cells, default=np.nan)
    area = _array(mesh.cell_area_m2, mesh.n_cells, default=np.nan)
    hydraulic_conductivity = _array(mesh.hydraulic_conductivity_m_s, mesh.n_cells, default=np.nan)
    residual = _array(assembly.solver_residual, mesh.n_cells, default=np.nan)
    saturated_thickness = _array(assembly.saturated_thickness_m, mesh.n_cells, default=np.nan)
    transmissivity = _array(assembly.transmissivity_m2_s, mesh.n_cells, default=np.nan)
    minimum_saturated_thickness_m = _diagnostic_float(
        result.diagnostics,
        runtime_summary,
        keys=("minimum_saturated_thickness_m", "b_min_m"),
        default=0.0,
    )
    physical_thickness = physical_saturated_thickness(mesh, head)
    effective_thickness = effective_saturated_thickness(
        mesh,
        head,
        minimum_saturated_thickness_m=minimum_saturated_thickness_m,
    )
    thickness_diag = saturated_thickness_diagnostics(
        mesh,
        head,
        minimum_saturated_thickness_m=minimum_saturated_thickness_m,
    )
    dry_equilibrium = detect_dry_equilibrium(
        mesh,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        minimum_saturated_thickness_m=minimum_saturated_thickness_m,
        tol_bottom_vi=max(float(options.tol_residual_inf), 1.0e-12),
    )
    prescribed = _prescribed_array(prescribed_head_m_by_cell, mesh.n_cells)
    prescribed_mask = np.isfinite(prescribed)
    drainage_conductance = _broadcast_optional(drainage_conductance_m2_s, mesh.n_cells)
    drainage_rate = _rate_from_flux(assembly.drainage_flux_m3_s, area)
    surface_reaction = _surface_reaction(assembly, area)
    bottom_reaction = _bottom_reaction(assembly, area)
    neighbor_count = _neighbor_count(mesh)

    tol_h = max(_OBSTACLE_ACTIVE_TOL_M, 10.0 * float(options.tol_state_update_inf))
    lower_violation = np.maximum(z_bottom - head, 0.0)
    upper_violation = np.maximum(head - z_top, 0.0)
    active_drain = (~prescribed_mask) & (drainage_conductance > 0.0) & (head > z_top + tol_h)
    active_bottom = (~prescribed_mask) & ((head <= z_bottom + tol_h) | (bottom_reaction > 0.0))
    active_top = (
        (~prescribed_mask)
        & (~active_drain)
        & (~active_bottom)
        & ((head >= z_top - tol_h) | (surface_reaction > 0.0))
    )
    projected_residual = _projected_vi_residual(
        residual=residual,
        head_m=head,
        lower_m=z_bottom,
        upper_m=z_top,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    active_state = _active_state(
        head_m=head,
        z_bottom_m=z_bottom,
        z_top_m=z_top,
        prescribed_mask=prescribed_mask,
        drainage_conductance_m2_s=drainage_conductance,
        surface_reaction_m3_s=surface_reaction,
        bottom_reaction_m3_s=bottom_reaction,
        tol_h=tol_h,
    )
    top_indices = _top_residual_indices(
        projected_residual=projected_residual,
        residual=residual,
        top_n_cells=top_n_cells,
    )
    cell_rows = [
        _cell_row(
            mesh=mesh,
            index=int(index),
            head=head,
            z_bottom=z_bottom,
            z_top=z_top,
            area=area,
            hydraulic_conductivity=hydraulic_conductivity,
            residual=residual,
            projected_residual=projected_residual,
            active_state=active_state,
            saturated_thickness=saturated_thickness,
            transmissivity=transmissivity,
            drainage_rate=drainage_rate,
            surface_reaction=surface_reaction,
            bottom_reaction=bottom_reaction,
            neighbor_count=neighbor_count,
        )
        for index in top_indices
    ]
    active_rows = _active_set_rows(
        active_state=active_state,
        residual=residual,
        projected_residual=projected_residual,
        area=area,
        hydraulic_conductivity=hydraulic_conductivity,
        saturated_thickness=saturated_thickness,
    )
    field_stats = _field_stats(
        head=head,
        z_bottom=z_bottom,
        z_top=z_top,
        area=area,
        hydraulic_conductivity=hydraulic_conductivity,
        residual=residual,
        projected_residual=projected_residual,
        saturated_thickness=saturated_thickness,
        transmissivity=transmissivity,
        physical_saturated_thickness=physical_thickness,
        effective_saturated_thickness=effective_thickness,
        drainage_rate=drainage_rate,
        surface_reaction=surface_reaction,
        bottom_reaction=bottom_reaction,
        recharge_rate_m_s=_broadcast_optional(recharge_rate_m_s, mesh.n_cells),
        well_flux_m3_s=_broadcast_optional(well_flux_m3_s, mesh.n_cells),
    )
    backend_method = getattr(getattr(runtime_backend, "method", None), "id", None)
    summary = {
        "schema_version": "boussinesq_stationary_failure_diagnostics_v1",
        "case_id": case_id,
        "simulation_id": simulation_id,
        "runtime_backend": getattr(runtime_backend, "name", runtime_summary.get("runtime_backend")),
        "runtime_engine_id": getattr(
            runtime_backend,
            "engine_id",
            runtime_summary.get("runtime_engine_id"),
        ),
        "surface_interaction_model": runtime_summary.get("surface_interaction_model_resolved"),
        "initialization_strategy": initialization_strategy,
        "stationarity_method": backend_method or runtime_summary.get("runtime_formulation"),
        "petsc_options": (
            runtime_summary.get("steady_petsc_options")
            or runtime_summary.get("last_petsc_options")
            or runtime_summary.get("petsc_options")
            or os.environ.get("PETSC_OPTIONS")
        ),
        "snes_type": runtime_summary.get("steady_snes_type") or runtime_summary.get("snes_type"),
        "ksp_type": runtime_summary.get("steady_ksp_type") or runtime_summary.get("ksp_type"),
        "pc_type": runtime_summary.get("steady_pc_type") or runtime_summary.get("pc_type"),
        "factor_shift_type": (
            runtime_summary.get("steady_pc_factor_shift_type")
            or runtime_summary.get("pc_factor_shift_type")
        ),
        "factor_shift_amount": (
            runtime_summary.get("steady_pc_factor_shift_amount")
            or runtime_summary.get("pc_factor_shift_amount")
        ),
        "snes_reason": _reason_label(runtime_summary, "snes", result.termination_reason),
        "ksp_reason": _reason_label(runtime_summary, "ksp", result.termination_reason),
        "pc_reason": runtime_summary.get("steady_pc_reason") or runtime_summary.get("pc_reason"),
        "snes_iterations": _first_non_none(
            runtime_summary.get("steady_snes_iterations"),
            runtime_summary.get("steady_nonlinear_iterations"),
            result.iterations,
        ),
        "ksp_iterations": _first_non_none(
            runtime_summary.get("steady_ksp_iterations"),
            runtime_summary.get("last_ksp_iterations"),
        ),
        "residual_norm_final": float(result.residual_norm_inf),
        "projected_residual_norm_final": _finite_norm_inf(projected_residual),
        "tolerance": float(options.tol_residual_inf),
        "dry_equilibrium_candidate_checked": dry_equilibrium.candidate_checked,
        "dry_equilibrium_detected": dry_equilibrium.detected,
        "dry_equilibrium_rejected_reason": dry_equilibrium.rejected_reason,
        "dry_equilibrium_positive_forcing_detected": (dry_equilibrium.positive_forcing_detected),
        "dry_equilibrium_min_R": dry_equilibrium.min_residual_m3_s,
        "dry_equilibrium_projected_residual_inf": dry_equilibrium.projected_residual_inf,
        "dry_equilibrium_vi_violations_count": dry_equilibrium.vi_violations_count,
        "converged": bool(result.converged),
        "termination_reason": str(result.termination_reason),
        "n_cells": int(mesh.n_cells),
        "h_min": _finite_min(head),
        "h_max": _finite_max(head),
        "z_bottom_min": _finite_min(z_bottom),
        "z_top_max": _finite_max(z_top),
        "max_upper_violation": _finite_max(upper_violation),
        "max_lower_violation": _finite_max(lower_violation),
        "active_top_count": int(np.count_nonzero(active_top)),
        "active_bottom_count": int(np.count_nonzero(active_bottom)),
        "free_count": int(np.count_nonzero((~prescribed_mask) & ~(active_top | active_bottom))),
        "cells_above_top_count": int(np.count_nonzero(upper_violation > tol_h)),
        "cells_below_bottom_count": int(np.count_nonzero(lower_violation > tol_h)),
        "drainage_positive_count": int(np.count_nonzero(drainage_rate > 0.0)),
        "surface_reaction_total": _finite_sum(surface_reaction),
        "bottom_reaction_total": _finite_sum(bottom_reaction),
        "K_min": _finite_min(hydraulic_conductivity),
        "K_max": _finite_max(hydraulic_conductivity),
        "area_min": _finite_min(area),
        "area_max": _finite_max(area),
        "saturated_thickness_min": _finite_min(saturated_thickness),
        "saturated_thickness_max": _finite_max(saturated_thickness),
        "saturated_thickness_quantiles": _quantiles(saturated_thickness),
        "minimum_saturated_thickness_m": minimum_saturated_thickness_m,
        "physical_saturated_thickness_min": thickness_diag["physical_saturated_thickness_min"],
        "physical_saturated_thickness_q01": thickness_diag["physical_saturated_thickness_q01"],
        "physical_saturated_thickness_q50": thickness_diag["physical_saturated_thickness_q50"],
        "physical_saturated_thickness_max": thickness_diag["physical_saturated_thickness_max"],
        "effective_saturated_thickness_min": thickness_diag["effective_saturated_thickness_min"],
        "effective_saturated_thickness_q01": thickness_diag["effective_saturated_thickness_q01"],
        "effective_saturated_thickness_q50": thickness_diag["effective_saturated_thickness_q50"],
        "effective_saturated_thickness_max": thickness_diag["effective_saturated_thickness_max"],
        "cells_physically_dry_count": thickness_diag["cells_physically_dry_count"],
        "cells_at_effective_floor_count": thickness_diag["cells_at_effective_floor_count"],
        "transmissivity_min": _finite_min(transmissivity),
        "transmissivity_max": _finite_max(transmissivity),
        "transmissivity_quantiles": _quantiles(transmissivity),
    }
    return (
        _jsonable_mapping(summary),
        [_jsonable_mapping(row) for row in cell_rows],
        [_jsonable_mapping(row) for row in active_rows],
        _jsonable_mapping(field_stats),
    )


def _cell_row(
    *,
    mesh: BoussinesqMesh,
    index: int,
    head: np.ndarray,
    z_bottom: np.ndarray,
    z_top: np.ndarray,
    area: np.ndarray,
    hydraulic_conductivity: np.ndarray,
    residual: np.ndarray,
    projected_residual: np.ndarray,
    active_state: np.ndarray,
    saturated_thickness: np.ndarray,
    transmissivity: np.ndarray,
    drainage_rate: np.ndarray,
    surface_reaction: np.ndarray,
    bottom_reaction: np.ndarray,
    neighbor_count: np.ndarray,
) -> dict[str, Any]:
    return {
        "cell_id": _int_or_none(mesh.cell_ids[index]),
        "x": _float_or_none(mesh.cell_centroid_x_m[index]),
        "y": _float_or_none(mesh.cell_centroid_y_m[index]),
        "area": _float_or_none(area[index]),
        "K": _float_or_none(hydraulic_conductivity[index]),
        "z_bottom": _float_or_none(z_bottom[index]),
        "z_top": _float_or_none(z_top[index]),
        "h": _float_or_none(head[index]),
        "h_minus_z_top": _float_or_none(head[index] - z_top[index]),
        "h_minus_z_bottom": _float_or_none(head[index] - z_bottom[index]),
        "residual": _float_or_none(residual[index]),
        "projected_residual": _float_or_none(projected_residual[index]),
        "active_state": str(active_state[index]),
        "saturated_thickness": _float_or_none(saturated_thickness[index]),
        "transmissivity": _float_or_none(transmissivity[index]),
        "drainage_rate": _float_or_none(drainage_rate[index]),
        "surface_reaction": _float_or_none(surface_reaction[index]),
        "bottom_reaction": _float_or_none(bottom_reaction[index]),
        "n_neighbors": _int_or_none(neighbor_count[index]),
        "local_mesh_quality": None,
    }


def _active_set_rows(
    *,
    active_state: np.ndarray,
    residual: np.ndarray,
    projected_residual: np.ndarray,
    area: np.ndarray,
    hydraulic_conductivity: np.ndarray,
    saturated_thickness: np.ndarray,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = max(int(active_state.size), 1)
    for state in ("free", "top", "bottom", "drain", "prescribed", "unknown"):
        mask = active_state == state
        if not np.any(mask):
            continue
        rows.append(
            {
                "active_state": state,
                "count": int(np.count_nonzero(mask)),
                "fraction": float(np.count_nonzero(mask) / total),
                "max_abs_residual": _finite_max(np.abs(residual[mask])),
                "max_abs_projected_residual": _finite_max(np.abs(projected_residual[mask])),
                "area_min": _finite_min(area[mask]),
                "area_max": _finite_max(area[mask]),
                "K_min": _finite_min(hydraulic_conductivity[mask]),
                "K_max": _finite_max(hydraulic_conductivity[mask]),
                "saturated_thickness_min": _finite_min(saturated_thickness[mask]),
                "saturated_thickness_max": _finite_max(saturated_thickness[mask]),
            }
        )
    return rows


def _field_stats(**fields: np.ndarray) -> dict[str, Any]:
    return {
        name: {
            "min": _finite_min(values),
            "max": _finite_max(values),
            "mean": _finite_mean(values),
            "sum": _finite_sum(values),
            "quantiles": _quantiles(values),
        }
        for name, values in fields.items()
    }


def _diagnostic_float(
    diagnostics: Mapping[str, Any] | None,
    runtime_summary: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
    default: float,
) -> float:
    for source in (diagnostics or {}, runtime_summary):
        for key in keys:
            value = _float_or_none(source.get(key))
            if value is not None:
                return value
    return float(default)


def _active_state(
    *,
    head_m: np.ndarray,
    z_bottom_m: np.ndarray,
    z_top_m: np.ndarray,
    prescribed_mask: np.ndarray,
    drainage_conductance_m2_s: np.ndarray,
    surface_reaction_m3_s: np.ndarray,
    bottom_reaction_m3_s: np.ndarray,
    tol_h: float,
) -> np.ndarray:
    head = np.asarray(head_m, dtype=float)
    state = np.full(head.shape, "free", dtype=object)
    state[~np.isfinite(head)] = "unknown"
    state[prescribed_mask] = "prescribed"
    bottom = (~prescribed_mask) & (head <= z_bottom_m + float(tol_h))
    bottom = bottom | ((~prescribed_mask) & (np.asarray(bottom_reaction_m3_s) > 0.0))
    drain = (
        (~prescribed_mask)
        & (np.asarray(drainage_conductance_m2_s, dtype=float) > 0.0)
        & (head > z_top_m + float(tol_h))
    )
    top = (
        (~prescribed_mask)
        & (~drain)
        & (~bottom)
        & ((head >= z_top_m - float(tol_h)) | (np.asarray(surface_reaction_m3_s) > 0.0))
    )
    state[bottom] = "bottom"
    state[top] = "top"
    state[drain] = "drain"
    return state.astype(str)


def _projected_vi_residual(
    *,
    residual: np.ndarray,
    head_m: np.ndarray,
    lower_m: np.ndarray,
    upper_m: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> np.ndarray:
    values = np.asarray(residual, dtype=float).reshape(-1)
    head = np.asarray(head_m, dtype=float).reshape(-1)
    lower = np.asarray(lower_m, dtype=float).reshape(-1)
    upper = np.asarray(upper_m, dtype=float).reshape(-1)
    projected = values.copy()
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    lower_active = free & (head <= lower + float(tol_h))
    upper_active = free & (head >= upper - float(tol_h))
    interior = free & ~(lower_active | upper_active)
    projected[interior] = values[interior]
    projected[lower_active] = np.minimum(values[lower_active], 0.0)
    projected[upper_active] = np.maximum(values[upper_active], 0.0)
    return projected


def _top_residual_indices(
    *,
    projected_residual: np.ndarray,
    residual: np.ndarray,
    top_n_cells: int,
) -> np.ndarray:
    score = np.abs(np.asarray(projected_residual, dtype=float))
    if not np.any(np.isfinite(score) & (score > 0.0)):
        score = np.abs(np.asarray(residual, dtype=float))
    score = np.nan_to_num(score, nan=-math.inf, posinf=math.inf, neginf=math.inf)
    count = min(max(int(top_n_cells), 0), score.size)
    if count == 0:
        return np.asarray([], dtype=int)
    return np.argsort(score)[::-1][:count].astype(int, copy=False)


def _surface_reaction(assembly: BoussinesqAssembly, area: np.ndarray) -> np.ndarray:
    rate = _array(assembly.saturation_excess_rate_m_s, area.size, default=0.0)
    return np.maximum(rate, 0.0) * np.asarray(area, dtype=float)


def _bottom_reaction(assembly: BoussinesqAssembly, area: np.ndarray) -> np.ndarray:
    rate = _array(assembly.dry_deficit_rate_m_s, area.size, default=0.0)
    return np.maximum(rate, 0.0) * np.asarray(area, dtype=float)


def _rate_from_flux(flux: np.ndarray, area: np.ndarray) -> np.ndarray:
    values = _array(flux, area.size, default=0.0)
    return np.divide(values, area, out=np.zeros(area.size, dtype=float), where=area > 0.0)


def _neighbor_count(mesh: BoussinesqMesh) -> np.ndarray:
    counts = np.zeros(int(mesh.n_cells), dtype=int)
    cell_a = np.asarray(mesh.edge_cell_a, dtype=int).reshape(-1)
    cell_b = np.asarray(mesh.edge_cell_b, dtype=int).reshape(-1)
    interior = (cell_a >= 0) & (cell_b >= 0)
    np.add.at(counts, cell_a[interior], 1)
    np.add.at(counts, cell_b[interior], 1)
    return counts


def _prescribed_array(value: np.ndarray | None, size: int) -> np.ndarray:
    if value is None:
        return np.full(int(size), np.nan, dtype=float)
    return _array(value, size, default=np.nan)


def _array(value: Any, size: int, *, default: float) -> np.ndarray:
    if value is None:
        return np.full(int(size), float(default), dtype=float)
    array = np.asarray(value, dtype=float).reshape(-1)
    if array.size == 1:
        return np.full(int(size), float(array[0]), dtype=float)
    if array.size != int(size):
        return np.resize(array, int(size)).astype(float, copy=False)
    return array.astype(float, copy=False)


def _broadcast_optional(value: np.ndarray | float | None, size: int) -> np.ndarray:
    return _array(value, size, default=0.0)


def _reason_label(summary: Mapping[str, Any], kind: str, termination_reason: str) -> Any:
    label = (
        summary.get(f"steady_{kind}_converged_reason_label")
        or summary.get(f"last_{kind}_converged_reason_label")
        or summary.get(f"{kind}_converged_reason_label")
    )
    if label not in (None, ""):
        return label
    pattern = "SNES_[A-Z_]+" if kind == "snes" else "KSP_[A-Z_]+"
    match = re.search(pattern, str(termination_reason or ""))
    return match.group(0) if match else None


def _first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _finite_values(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    return array[np.isfinite(array)]


def _finite_min(values: np.ndarray) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.min(finite))


def _finite_max(values: np.ndarray) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.max(finite))


def _finite_mean(values: np.ndarray) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.mean(finite))


def _finite_sum(values: np.ndarray) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.sum(finite))


def _finite_norm_inf(values: np.ndarray) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.linalg.norm(finite, ord=np.inf))


def _quantiles(values: np.ndarray) -> dict[str, float | None]:
    finite = _finite_values(values)
    if finite.size == 0:
        return {"p00": None, "p05": None, "p50": None, "p95": None, "p100": None}
    levels = (0.0, 0.05, 0.5, 0.95, 1.0)
    labels = ("p00", "p05", "p50", "p95", "p100")
    result = np.quantile(finite, np.asarray(levels, dtype=float))
    return {label: float(value) for label, value in zip(labels, result, strict=True)}


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if math.isfinite(parsed) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


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


__all__ = [
    "STATIONARY_FAILURE_ACTIVE_SET_FIELDS",
    "STATIONARY_FAILURE_CELL_FIELDS",
    "build_stationary_failure_diagnostics",
    "write_stationary_failure_diagnostics",
]
