"""Diagnostics for the transient hillslope recharge-pulse overflow case."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hydromodpy.physics.flow.history_contract import (
    snapshot_elapsed_seconds_from_payload,
    step_history_from_history,
)
from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
)
from validation_cases.shared.boussinesq_budget import (
    compute_free_control_volume_budget,
)

from .runtime_boussinesq import CASE_DIR, resolve_solver_variant

SECONDS_PER_DAY = 86_400.0
MM_DAY_PER_M_S = 86_400.0 * 1_000.0


@dataclass(frozen=True, slots=True)
class SolverOverflowDiagnostics:
    """Structured diagnostics used by the overflow plotting and summaries."""

    result: ValidationRunResult
    metadata: dict
    solver_name: str
    solver_label: str
    runtime_backend: str
    surface_interaction_model: str
    elapsed_days: np.ndarray
    recharge_mm_day: np.ndarray
    recharge_flux_m3_day: np.ndarray
    x_m: np.ndarray
    topography_profile_m: np.ndarray
    mean_head_profiles_m: np.ndarray
    mean_head_clearance_m: np.ndarray
    mean_saturation_excess_mm_day: np.ndarray
    drainage_flux_m3_day: np.ndarray
    surface_excess_flux_m3_day: np.ndarray
    east_boundary_outflow_m3_day: np.ndarray
    total_outflow_m3_day: np.ndarray
    net_inflow_m3_day: np.ndarray
    storage_change_m3_day: np.ndarray
    residual_m3_day: np.ndarray
    total_overflow_m3_day: np.ndarray
    active_overflow_length_m: np.ndarray
    overflow_front_x_m: np.ndarray
    overflow_centroid_x_m: np.ndarray
    overflow_threshold_mm_day: float
    onset_day: float
    peak_overflow_day: float
    peak_total_overflow_m3_day: float
    peak_active_length_m: float
    max_head_clearance_m: float
    runtime_summary: dict[str, object]


def _load_summary(model_ws: Path) -> dict[str, object]:
    summary_path = model_ws / "_boussinesq_summary.json"
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _load_state_history(model_ws: Path) -> dict[str, np.ndarray]:
    state_path = model_ws / "_boussinesq_state_history.npz"
    with np.load(state_path) as payload:
        return {key: np.asarray(payload[key]) for key in payload.files}


def _load_cell_geometry(bundle_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cells = np.genfromtxt(
        bundle_dir / "cells.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    return (
        np.asarray(cells["centroid_x"], dtype=float).reshape(-1),
        np.asarray(cells["centroid_y"], dtype=float).reshape(-1),
        np.asarray(cells["area_m2"], dtype=float).reshape(-1),
    )


def _load_cell_storage(bundle_dir: Path) -> np.ndarray:
    cells = np.genfromtxt(
        bundle_dir / "cells.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    return np.asarray(cells["storage_coefficient"], dtype=float).reshape(-1)


def aggregate_cell_history_to_grid(
    history_values: np.ndarray,
    *,
    cell_x_m: np.ndarray,
    cell_y_m: np.ndarray,
    nx: int,
    ny: int,
    length_x_m: float,
    width_y_m: float,
) -> np.ndarray:
    """Aggregate one cell-wise time history onto the regular strip grid."""
    values = np.asarray(history_values, dtype=float)
    if values.ndim == 1:
        values = values.reshape(1, -1)

    dx = float(length_x_m) / float(nx)
    dy = float(width_y_m) / float(ny)
    col_index = np.clip(
        np.floor(np.asarray(cell_x_m, dtype=float) / dx).astype(int), 0, int(nx) - 1
    )
    row_index = np.clip(
        np.floor(np.asarray(cell_y_m, dtype=float) / dy).astype(int), 0, int(ny) - 1
    )

    counts = np.zeros((int(ny), int(nx)), dtype=float)
    np.add.at(counts, (row_index, col_index), 1.0)
    if np.any(counts == 0.0):
        raise AssertionError("Every structured strip bin must receive at least one triangle.")

    aggregated = np.zeros((values.shape[0], int(ny), int(nx)), dtype=float)
    for time_index in range(values.shape[0]):
        np.add.at(aggregated[time_index], (row_index, col_index), values[time_index])
    aggregated /= counts[None, :, :]
    return aggregated


def compute_overflow_footprint_metrics(
    saturation_excess_profiles_mm_day: np.ndarray,
    *,
    x_m: np.ndarray,
    threshold_mm_day: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return active length, downstream front, and weighted centroid through time."""
    profiles = np.asarray(saturation_excess_profiles_mm_day, dtype=float)
    x_values = np.asarray(x_m, dtype=float).reshape(-1)
    if profiles.ndim != 2:
        raise ValueError("saturation_excess_profiles_mm_day must be a 2D time-x array.")
    if profiles.shape[1] != x_values.size:
        raise ValueError("Profile width must match the x coordinates.")

    if x_values.size > 1:
        dx = float(np.median(np.diff(x_values)))
    else:
        dx = 0.0

    active_mask = profiles > float(threshold_mm_day)
    active_length_m = np.sum(active_mask, axis=1, dtype=float) * dx
    front_x_m = np.full(profiles.shape[0], np.nan, dtype=float)
    centroid_x_m = np.full(profiles.shape[0], np.nan, dtype=float)

    for time_index in range(profiles.shape[0]):
        if np.any(active_mask[time_index]):
            front_x_m[time_index] = float(x_values[np.where(active_mask[time_index])[0][-1]])
        positive = np.maximum(profiles[time_index], 0.0)
        weight_sum = float(np.sum(positive))
        if weight_sum > 0.0:
            centroid_x_m[time_index] = float(np.sum(positive * x_values) / weight_sum)

    return active_length_m, front_x_m, centroid_x_m


def _topography_profile(x_m: np.ndarray, *, geometry_cfg: dict[str, object]) -> np.ndarray:
    x_values = np.asarray(x_m, dtype=float)
    return float(geometry_cfg["toe_elevation_m"]) + (
        float(geometry_cfg["topography_slope_m_per_m"])
        * (float(geometry_cfg["length_x_m"]) - x_values)
    )


def _infer_structured_shape(
    *,
    head_history_m: np.ndarray,
    cell_y_m: np.ndarray,
    geometry_cfg: dict[str, object],
) -> tuple[int, int]:
    """Infer the effective structured aggregation shape from the run outputs."""
    n_cells = int(np.asarray(head_history_m, dtype=float).shape[1])
    unique_y = np.unique(np.round(np.asarray(cell_y_m, dtype=float), decimals=9))
    ny = int(unique_y.size)
    nx = n_cells // ny if ny > 0 and n_cells % ny == 0 else 0
    if nx <= 0:
        nx = int(geometry_cfg["nx"])
    if ny <= 0:
        ny = int(geometry_cfg["ny"])
    return nx, ny


def _resolve_recharge_series_mm_day(
    *,
    state_history: dict[str, np.ndarray],
    forcing_cfg: dict[str, object],
    cell_area_m2: np.ndarray,
    n_periods: int,
) -> np.ndarray:
    """Return the actual recharge chronology used by the run in mm/day.

    The numerical scenario may override the metadata forcing through presets or
    CLI arguments. The plotting/diagnostic layer therefore prefers the exported
    runtime recharge history over the static metadata payload.
    """
    recharge_history = np.asarray(
        state_history.get("recharge_rate_history_m_s", ()),
        dtype=float,
    )
    if recharge_history.ndim == 2 and int(n_periods) > 0:
        period_rates_m_s = step_history_from_history(
            recharge_history,
            n_steps=int(n_periods),
            name="recharge_rate_history_m_s",
        )
        if period_rates_m_s.size != 0:
            weights = np.asarray(cell_area_m2, dtype=float).reshape(1, -1)
            total_area = float(np.sum(weights))
            if total_area > 0.0 and period_rates_m_s.shape[1] == weights.shape[1]:
                weighted_mean_m_s = np.sum(period_rates_m_s * weights, axis=1) / total_area
                return np.asarray(weighted_mean_m_s * MM_DAY_PER_M_S, dtype=float)
            return np.asarray(np.mean(period_rates_m_s, axis=1) * MM_DAY_PER_M_S, dtype=float)

    return np.asarray(forcing_cfg.get("recharge_mm_day", ()), dtype=float).reshape(-1)


def _align_period_values_to_elapsed_days(
    values: np.ndarray,
    *,
    elapsed_days: np.ndarray,
) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    elapsed = np.asarray(elapsed_days, dtype=float).reshape(-1)
    if array.size == elapsed.size:
        return array
    if array.size == max(0, elapsed.size - 1):
        if array.size == 0:
            return np.zeros_like(elapsed, dtype=float)
        return np.concatenate(([float(array[0])], array))
    raise ValueError(
        f"Value chronology length does not match elapsed days ({array.size} vs {elapsed.size})."
    )


def build_hillslope_overflow_diagnostics(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    overflow_threshold_mm_day: float | None = None,
) -> SolverOverflowDiagnostics:
    """Load one completed overflow run and derive structured diagnostics."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    geometry_cfg = dict(case_metadata.get("geometry", {}))
    forcing_cfg = dict(case_metadata.get("forcing", {}))
    diagnostics_cfg = dict(case_metadata.get("diagnostics", {}))

    summary = _load_summary(result.model_ws)
    state_history = _load_state_history(result.model_ws)

    bundle_dir = result.out_path / "mesh_bundle"
    cell_x_m, cell_y_m, cell_area_m2 = _load_cell_geometry(bundle_dir)
    head_history_m = np.asarray(state_history["head_history_m"], dtype=float)
    nx, ny = _infer_structured_shape(
        head_history_m=head_history_m,
        cell_y_m=cell_y_m,
        geometry_cfg=geometry_cfg,
    )
    length_x_m = float(geometry_cfg["length_x_m"])
    width_y_m = float(geometry_cfg["width_y_m"])
    x_m = (np.arange(nx, dtype=float) + 0.5) * (length_x_m / float(nx))
    head_grid_m = aggregate_cell_history_to_grid(
        head_history_m,
        cell_x_m=cell_x_m,
        cell_y_m=cell_y_m,
        nx=nx,
        ny=ny,
        length_x_m=length_x_m,
        width_y_m=width_y_m,
    )
    mean_head_profiles_m = np.mean(head_grid_m, axis=1)
    topography_profile_m = _topography_profile(x_m, geometry_cfg=geometry_cfg)
    mean_head_clearance_m = mean_head_profiles_m - topography_profile_m[None, :]

    saturation_excess_history_m_s = np.asarray(
        state_history["saturation_excess_history_m_s"],
        dtype=float,
    )
    saturation_excess_grid_m_s = aggregate_cell_history_to_grid(
        saturation_excess_history_m_s,
        cell_x_m=cell_x_m,
        cell_y_m=cell_y_m,
        nx=nx,
        ny=ny,
        length_x_m=length_x_m,
        width_y_m=width_y_m,
    )
    mean_saturation_excess_mm_day = np.mean(saturation_excess_grid_m_s, axis=1) * MM_DAY_PER_M_S
    surface_excess_flux_m3_day = (
        np.sum(saturation_excess_history_m_s * cell_area_m2[None, :], axis=1) * SECONDS_PER_DAY
    )

    resolved_threshold = float(
        diagnostics_cfg.get("overflow_threshold_mm_day", 0.0)
        if overflow_threshold_mm_day is None
        else overflow_threshold_mm_day
    )
    active_overflow_length_m, overflow_front_x_m, overflow_centroid_x_m = (
        compute_overflow_footprint_metrics(
            mean_saturation_excess_mm_day,
            x_m=x_m,
            threshold_mm_day=resolved_threshold,
        )
    )

    elapsed_seconds = snapshot_elapsed_seconds_from_payload(
        state_history,
        n_snapshots=int(np.asarray(state_history["head_history_m"], dtype=float).shape[0]),
    )
    if elapsed_seconds is None:
        raise ValueError(
            "Transient Boussinesq diagnostics require explicit or derivable snapshot times."
        )
    elapsed_days = np.asarray(elapsed_seconds / SECONDS_PER_DAY, dtype=float)
    n_periods = max(int(elapsed_days.size) - 1, 0)
    recharge_mm_day = _resolve_recharge_series_mm_day(
        state_history=state_history,
        forcing_cfg=forcing_cfg,
        cell_area_m2=cell_area_m2,
        n_periods=n_periods,
    )
    recharge_mm_day = _align_period_values_to_elapsed_days(
        recharge_mm_day,
        elapsed_days=elapsed_days,
    )
    budget = compute_free_control_volume_budget(
        bundle_dir=bundle_dir,
        state_history=state_history,
        seconds_per_day=SECONDS_PER_DAY,
        elapsed_days=elapsed_days,
    )
    recharge_flux_m3_day = _align_period_values_to_elapsed_days(
        budget.recharge_flux_m3_day,
        elapsed_days=elapsed_days,
    )
    drainage_flux_m3_day = _align_period_values_to_elapsed_days(
        budget.drainage_flux_m3_day,
        elapsed_days=elapsed_days,
    )
    east_boundary_inflow_m3_day = _align_period_values_to_elapsed_days(
        budget.east_boundary_inflow_m3_day,
        elapsed_days=elapsed_days,
    )
    east_boundary_outflow_m3_day = _align_period_values_to_elapsed_days(
        budget.east_boundary_outflow_m3_day,
        elapsed_days=elapsed_days,
    )
    total_outflow_m3_day = np.asarray(
        drainage_flux_m3_day + east_boundary_outflow_m3_day + surface_excess_flux_m3_day,
        dtype=float,
    )
    net_inflow_m3_day = np.asarray(
        recharge_flux_m3_day + east_boundary_inflow_m3_day - total_outflow_m3_day,
        dtype=float,
    )
    storage_change_m3_day = _align_period_values_to_elapsed_days(
        budget.storage_change_m3_day,
        elapsed_days=elapsed_days,
    )
    residual_m3_day = np.asarray(
        net_inflow_m3_day - storage_change_m3_day,
        dtype=float,
    )

    onset_day = float("nan")
    active_indices = np.flatnonzero(active_overflow_length_m > 0.0)
    if active_indices.size:
        onset_day = float(elapsed_days[active_indices[0]])

    peak_index = int(np.argmax(surface_excess_flux_m3_day))
    variant = resolve_solver_variant(result.solver_name)

    return SolverOverflowDiagnostics(
        result=result,
        metadata=case_metadata,
        solver_name=result.solver_name,
        solver_label=variant.label,
        runtime_backend=str(summary.get("runtime_backend", "unknown")),
        surface_interaction_model=str(summary.get("surface_interaction_model_resolved", "unknown")),
        elapsed_days=elapsed_days,
        recharge_mm_day=recharge_mm_day,
        recharge_flux_m3_day=np.asarray(recharge_flux_m3_day, dtype=float),
        x_m=np.asarray(x_m, dtype=float),
        topography_profile_m=np.asarray(topography_profile_m, dtype=float),
        mean_head_profiles_m=np.asarray(mean_head_profiles_m, dtype=float),
        mean_head_clearance_m=np.asarray(mean_head_clearance_m, dtype=float),
        mean_saturation_excess_mm_day=np.asarray(mean_saturation_excess_mm_day, dtype=float),
        drainage_flux_m3_day=np.asarray(drainage_flux_m3_day, dtype=float),
        surface_excess_flux_m3_day=np.asarray(surface_excess_flux_m3_day, dtype=float),
        east_boundary_outflow_m3_day=np.asarray(east_boundary_outflow_m3_day, dtype=float),
        total_outflow_m3_day=np.asarray(total_outflow_m3_day, dtype=float),
        net_inflow_m3_day=np.asarray(net_inflow_m3_day, dtype=float),
        storage_change_m3_day=np.asarray(storage_change_m3_day, dtype=float),
        residual_m3_day=np.asarray(residual_m3_day, dtype=float),
        total_overflow_m3_day=np.asarray(surface_excess_flux_m3_day, dtype=float),
        active_overflow_length_m=np.asarray(active_overflow_length_m, dtype=float),
        overflow_front_x_m=np.asarray(overflow_front_x_m, dtype=float),
        overflow_centroid_x_m=np.asarray(overflow_centroid_x_m, dtype=float),
        overflow_threshold_mm_day=resolved_threshold,
        onset_day=onset_day,
        peak_overflow_day=float(elapsed_days[peak_index]),
        peak_total_overflow_m3_day=float(surface_excess_flux_m3_day[peak_index]),
        peak_active_length_m=float(np.max(active_overflow_length_m)),
        max_head_clearance_m=float(np.max(mean_head_clearance_m)),
        runtime_summary=summary,
    )


__all__ = [
    "MM_DAY_PER_M_S",
    "SECONDS_PER_DAY",
    "SolverOverflowDiagnostics",
    "aggregate_cell_history_to_grid",
    "build_hillslope_overflow_diagnostics",
    "compute_overflow_footprint_metrics",
]
