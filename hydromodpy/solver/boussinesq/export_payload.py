"""Export helpers for the Boussinesq solver."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def as_export_array(values: np.ndarray | None) -> np.ndarray:
    """Normalize optional arrays before writing them to disk."""
    if values is None:
        return np.asarray([], dtype=float)
    return np.asarray(values, dtype=float)


def build_state_history_export_payload(
    state: BoussinesqState,
) -> dict[str, np.ndarray]:
    """Return the canonical Boussinesq state-history export payload."""
    return {
        "recharge_rate_history_m_s": as_export_array(state.recharge_rate_history_m_s),
        "well_flux_history_m3_s": as_export_array(state.well_flux_history_m3_s),
        "head_history_m": as_export_array(state.head_history_m),
        "saturated_thickness_history_m": as_export_array(
            state.saturated_thickness_history_m
        ),
        "saturation_excess_history_m_s": as_export_array(
            state.saturation_excess_history_m_s
        ),
        "final_head_m": np.asarray(state.head_m, dtype=float),
        "final_saturated_thickness_m": np.asarray(
            state.saturated_thickness_m,
            dtype=float,
        ),
        "final_recharge_rate_m_s": as_export_array(state.recharge_rate_m_s),
        "final_well_flux_m3_s": as_export_array(state.well_flux_m3_s),
        "final_saturation_excess_rate_m_s": as_export_array(
            state.saturation_excess_rate_m_s
        ),
        "internal_edge_flux_m3_s": as_export_array(state.internal_edge_flux_m3_s),
        "internal_edge_flux_history_m3_s": as_export_array(
            state.internal_edge_flux_history_m3_s
        ),
        "prescribed_head_flux_m3_s": as_export_array(state.prescribed_head_flux_m3_s),
        "prescribed_head_flux_history_m3_s": as_export_array(
            state.prescribed_head_flux_history_m3_s
        ),
        "prescribed_head_m_by_cell": as_export_array(state.prescribed_head_m_by_cell),
        "prescribed_head_history_m_by_cell": as_export_array(
            state.prescribed_head_history_m_by_cell
        ),
        "imposed_head_edge_flux_m3_s": as_export_array(
            state.imposed_head_edge_flux_m3_s
        ),
        "imposed_head_edge_flux_history_m3_s": as_export_array(
            state.imposed_head_edge_flux_history_m3_s
        ),
        "drainage_flux_m3_s": as_export_array(state.drainage_flux_m3_s),
        "drainage_flux_history_m3_s": as_export_array(
            state.drainage_flux_history_m3_s
        ),
        "period_lengths_seconds": np.asarray(
            state.period_lengths_seconds,
            dtype=float,
        ),
    }


def write_standard_postprocess_outputs(
    *,
    full_path: Path,
    mesh: BoussinesqMesh,
    state: BoussinesqState,
) -> None:
    """Export the canonical `_postprocess` arrays expected by validation helpers."""
    postprocess_dir = full_path / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)

    raw_head_history = state.head_history_m
    if raw_head_history is None:
        head_history = np.asarray(state.head_m, dtype=float).reshape(1, -1)
    else:
        head_history = np.asarray(raw_head_history, dtype=float)
        if head_history.ndim == 1:
            head_history = head_history.reshape(1, -1)
        if head_history.size == 0:
            head_history = np.asarray(state.head_m, dtype=float).reshape(1, -1)

    z_top = np.asarray(mesh.z_top_m, dtype=float).reshape(1, -1)
    watertable_elevation = {
        int(index): np.asarray(head_values, dtype=float)
        for index, head_values in enumerate(head_history)
    }
    watertable_depth = {
        int(index): np.maximum(z_top[0] - np.asarray(head_values, dtype=float), 0.0)
        for index, head_values in enumerate(head_history)
    }

    np.save(postprocess_dir / "watertable_elevation.npy", watertable_elevation)
    np.save(postprocess_dir / "watertable_depth.npy", watertable_depth)


__all__ = [
    "as_export_array",
    "build_state_history_export_payload",
    "write_standard_postprocess_outputs",
]
