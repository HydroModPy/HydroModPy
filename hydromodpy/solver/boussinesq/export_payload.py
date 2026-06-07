"""Export helpers for the Boussinesq solver."""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.flow.history_contract import (
    build_transient_time_axes,
)
from hydromodpy.solver.boussinesq.core.state import BoussinesqState


def as_export_array(values: np.ndarray | None) -> np.ndarray:
    """Normalize optional arrays before writing them to disk."""
    if values is None:
        return np.asarray([], dtype=float)
    return np.asarray(values, dtype=float)


def build_state_history_export_payload(
    state: BoussinesqState,
) -> dict[str, np.ndarray]:
    """Return the canonical Boussinesq state-history export payload."""
    time_axes = build_transient_time_axes(state.period_lengths_seconds)
    return {
        "recharge_rate_history_m_s": as_export_array(state.recharge_rate_history_m_s),
        "well_flux_history_m3_s": as_export_array(state.well_flux_history_m3_s),
        "head_history_m": as_export_array(state.head_history_m),
        "saturated_thickness_history_m": as_export_array(state.saturated_thickness_history_m),
        "saturation_excess_history_m_s": as_export_array(state.saturation_excess_history_m_s),
        "dry_deficit_history_m_s": as_export_array(state.dry_deficit_history_m_s),
        "final_head_m": np.asarray(state.head_m, dtype=float),
        "final_saturated_thickness_m": np.asarray(
            state.saturated_thickness_m,
            dtype=float,
        ),
        "final_recharge_rate_m_s": as_export_array(state.recharge_rate_m_s),
        "final_well_flux_m3_s": as_export_array(state.well_flux_m3_s),
        "final_saturation_excess_rate_m_s": as_export_array(state.saturation_excess_rate_m_s),
        "final_dry_deficit_rate_m_s": as_export_array(state.dry_deficit_rate_m_s),
        "internal_edge_flux_m3_s": as_export_array(state.internal_edge_flux_m3_s),
        "internal_edge_flux_history_m3_s": as_export_array(state.internal_edge_flux_history_m3_s),
        "prescribed_head_flux_m3_s": as_export_array(state.prescribed_head_flux_m3_s),
        "prescribed_head_flux_history_m3_s": as_export_array(
            state.prescribed_head_flux_history_m3_s
        ),
        "prescribed_head_m_by_cell": as_export_array(state.prescribed_head_m_by_cell),
        "prescribed_head_history_m_by_cell": as_export_array(
            state.prescribed_head_history_m_by_cell
        ),
        "boundary_edge_flux_m3_s": as_export_array(state.boundary_edge_flux_m3_s),
        "boundary_edge_flux_history_m3_s": as_export_array(state.boundary_edge_flux_history_m3_s),
        "drainage_flux_m3_s": as_export_array(state.drainage_flux_m3_s),
        "drainage_flux_history_m3_s": as_export_array(state.drainage_flux_history_m3_s),
        "residual_history_m3_s": as_export_array(state.residual_history_m3_s),
        "period_lengths_seconds": np.asarray(
            state.period_lengths_seconds,
            dtype=float,
        ),
        "snapshot_elapsed_seconds": np.asarray(
            time_axes.snapshot_elapsed_seconds,
            dtype=float,
        ),
        "step_end_elapsed_seconds": np.asarray(
            time_axes.step_end_elapsed_seconds,
            dtype=float,
        ),
    }


__all__ = [
    "as_export_array",
    "build_state_history_export_payload",
]
