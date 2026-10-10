"""Export helpers for the Boussinesq solver."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from hydromodpy.physics.flow.history_contract import (
    build_transient_time_axes,
)
from hydromodpy.solver.boussinesq.core.state import BoussinesqState


def first_period_snapshot(payload: Mapping[str, Any], *, n_snapshots: int) -> int:
    """Return the index of the first snapshot that closes a stress period.

    A transient history starts with the initial state, 0 s after the run start.
    That snapshot closes no period. A store or a series that stamps each period
    at its end, as the MODFLOW extractors do, starts after it. A steady history
    holds its solved state only.
    """
    if int(n_snapshots) <= 1:
        return 0
    elapsed = payload.get("snapshot_elapsed_seconds")
    if elapsed is not None:
        values = np.asarray(elapsed, dtype=float).reshape(-1)
        return 1 if values.size > 0 and float(values[0]) <= 0.0 else 0
    periods = payload.get("period_lengths_seconds")
    if periods is None:
        return 0
    return 1 if np.asarray(periods).size == int(n_snapshots) - 1 else 0


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
    "first_period_snapshot",
]
