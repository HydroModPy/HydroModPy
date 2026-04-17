"""Shared Boussinesq budget helpers for prescribed-cell control volumes.

These helpers reconstruct one consistent control-volume budget for the current
cell-centred Boussinesq runs:

- the external east-boundary flux is measured on the interior interface between
  free cells and prescribed Dirichlet cells,
- volumetric terms are integrated only on the free-cell control volume,
- prescribed cells are excluded from recharge, drainage, saturation excess, and
  storage-change bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hydromodpy.solver.boussinesq.history_contract import step_history_from_history


@dataclass(frozen=True, slots=True)
class BoussinesqFreeControlVolumeBudget:
    """Budget terms integrated on the free-cell control volume."""

    free_cell_mask: np.ndarray
    recharge_flux_m3_day: np.ndarray
    drainage_flux_m3_day: np.ndarray
    surface_excess_flux_m3_day: np.ndarray
    east_boundary_inflow_m3_day: np.ndarray
    east_boundary_outflow_m3_day: np.ndarray
    storage_change_m3_day: np.ndarray


def load_bundle_cell_table(bundle_dir: Path) -> np.ndarray:
    """Load the exported cell table once as one named NumPy array."""
    return np.genfromtxt(
        bundle_dir / "cells.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )


def prescribed_cell_mask_from_history(
    prescribed_head_history_m_by_cell: np.ndarray,
) -> np.ndarray:
    """Return the prescribed-cell mask resolved on the last saved step."""
    history = np.asarray(prescribed_head_history_m_by_cell, dtype=float)
    if history.ndim != 2:
        raise ValueError("prescribed_head_history_m_by_cell must be a 2D time-cell array.")
    return np.isfinite(history[-1])


def load_east_interface_edge_data(
    bundle_dir: Path,
    *,
    prescribed_cell_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return interface edges plus outward sign from free cells to prescribed cells."""
    edges = np.genfromtxt(
        bundle_dir / "edges.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    edge_cell_a = np.asarray(edges["cell_a"], dtype=int).reshape(-1)
    edge_cell_b = np.asarray(edges["cell_b"], dtype=int).reshape(-1)
    prescribed = np.asarray(prescribed_cell_mask, dtype=bool).reshape(-1)

    cell_a_prescribed = edge_cell_a >= 0
    cell_a_prescribed[cell_a_prescribed] = prescribed[edge_cell_a[cell_a_prescribed]]
    cell_b_prescribed = edge_cell_b >= 0
    cell_b_prescribed[cell_b_prescribed] = prescribed[edge_cell_b[cell_b_prescribed]]

    interface_mask = np.asarray(cell_a_prescribed ^ cell_b_prescribed, dtype=bool)
    outward_sign = np.zeros(edge_cell_a.size, dtype=float)
    outward_sign[interface_mask & (~cell_a_prescribed)] = 1.0
    outward_sign[interface_mask & (~cell_b_prescribed)] = -1.0
    return (
        np.flatnonzero(interface_mask).astype(int, copy=False),
        outward_sign[interface_mask].astype(float, copy=False),
    )


def compute_east_interface_flux_m3_day(
    *,
    bundle_dir: Path,
    internal_edge_flux_history_m3_s: np.ndarray,
    prescribed_head_history_m_by_cell: np.ndarray,
    seconds_per_day: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return east inflow/outflow reconstructed on the free/prescribed interface."""
    edge_history = np.asarray(internal_edge_flux_history_m3_s, dtype=float)
    prescribed_history = np.asarray(prescribed_head_history_m_by_cell, dtype=float)
    prescribed_cell_mask = prescribed_cell_mask_from_history(prescribed_history)
    interface_edges, outward_sign = load_east_interface_edge_data(
        bundle_dir,
        prescribed_cell_mask=prescribed_cell_mask,
    )
    if interface_edges.size == 0:
        zeros = np.zeros(edge_history.shape[0], dtype=float)
        return zeros, zeros
    outward_flux_m3_s = edge_history[:, interface_edges] * outward_sign.reshape(1, -1)
    east_boundary_outflow_m3_day = (
        np.sum(np.maximum(outward_flux_m3_s, 0.0), axis=1, dtype=float)
        * float(seconds_per_day)
    )
    east_boundary_inflow_m3_day = (
        -np.sum(np.minimum(outward_flux_m3_s, 0.0), axis=1, dtype=float)
        * float(seconds_per_day)
    )
    return (
        np.asarray(east_boundary_inflow_m3_day, dtype=float),
        np.asarray(east_boundary_outflow_m3_day, dtype=float),
    )


def compute_storage_change_flux_m3_day(
    *,
    head_history_m: np.ndarray,
    cell_area_m2: np.ndarray,
    cell_storage_coefficient: np.ndarray,
    dt_days: float | None = None,
    elapsed_days: np.ndarray | None = None,
    cell_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Return storage-change rate integrated on one optional cell mask."""
    head_history = np.asarray(head_history_m, dtype=float)
    area = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    storage = np.asarray(cell_storage_coefficient, dtype=float).reshape(-1)
    mask = (
        np.ones(area.size, dtype=bool)
        if cell_mask is None
        else np.asarray(cell_mask, dtype=bool).reshape(-1)
    )
    if head_history.ndim != 2:
        raise ValueError("head_history_m must be a 2D time-cell array.")
    if head_history.shape[1] != area.size:
        raise ValueError("head_history_m cell count does not match the bundle cell count.")
    delta_head_m = np.diff(head_history, axis=0)
    if elapsed_days is not None:
        step_days = np.diff(np.asarray(elapsed_days, dtype=float).reshape(-1))
    elif dt_days is not None:
        step_days = np.full(delta_head_m.shape[0], float(dt_days), dtype=float)
    else:
        raise ValueError("Either dt_days or elapsed_days must be provided.")
    if delta_head_m.shape[0] != step_days.size:
        raise ValueError("head history and step durations are inconsistent.")
    storage_change_per_step_m3 = np.sum(
        delta_head_m[:, mask]
        * area[mask].reshape(1, -1)
        * storage[mask].reshape(1, -1),
        axis=1,
        dtype=float,
    )
    return np.asarray(storage_change_per_step_m3 / step_days, dtype=float)


def compute_free_control_volume_budget(
    *,
    bundle_dir: Path,
    state_history: dict[str, np.ndarray],
    seconds_per_day: float,
    dt_days: float | None = None,
    elapsed_days: np.ndarray | None = None,
) -> BoussinesqFreeControlVolumeBudget:
    """Reconstruct the free-cell control-volume budget from one exported run."""
    cells = load_bundle_cell_table(bundle_dir)
    cell_area_m2 = np.asarray(cells["area_m2"], dtype=float).reshape(-1)
    cell_storage = np.asarray(cells["storage_coefficient"], dtype=float).reshape(-1)
    head_history = np.asarray(state_history["head_history_m"], dtype=float)
    if head_history.ndim != 2:
        raise ValueError("head_history_m must be a 2D time-cell array.")
    period_lengths_seconds = np.asarray(
        state_history.get("period_lengths_seconds", ()),
        dtype=float,
    ).reshape(-1)
    n_steps = int(period_lengths_seconds.size)
    if n_steps <= 0:
        n_steps = max(int(head_history.shape[0]) - 1, 0)

    prescribed_head_history = np.asarray(
        state_history["prescribed_head_history_m_by_cell"],
        dtype=float,
    )
    prescribed_mask = prescribed_cell_mask_from_history(prescribed_head_history)
    free_mask = ~prescribed_mask

    recharge_history = step_history_from_history(
        state_history["recharge_rate_history_m_s"],
        n_steps=n_steps,
        name="recharge_rate_history_m_s",
    )
    drainage_history = step_history_from_history(
        state_history["drainage_flux_history_m3_s"],
        n_steps=n_steps,
        name="drainage_flux_history_m3_s",
    )
    saturation_excess_history = step_history_from_history(
        state_history["saturation_excess_history_m_s"],
        n_steps=n_steps,
        name="saturation_excess_history_m_s",
    )
    recharge_flux_m3_day = (
        np.sum(
            recharge_history[:, free_mask] * cell_area_m2[free_mask].reshape(1, -1),
            axis=1,
            dtype=float,
        )
        * float(seconds_per_day)
    )
    drainage_flux_m3_day = (
        np.sum(drainage_history[:, free_mask], axis=1, dtype=float) * float(seconds_per_day)
    )
    surface_excess_flux_m3_day = (
        np.sum(
            saturation_excess_history[:, free_mask]
            * cell_area_m2[free_mask].reshape(1, -1),
            axis=1,
            dtype=float,
        )
        * float(seconds_per_day)
    )
    east_boundary_inflow_m3_day, east_boundary_outflow_m3_day = (
        compute_east_interface_flux_m3_day(
            bundle_dir=bundle_dir,
            internal_edge_flux_history_m3_s=step_history_from_history(
                state_history["internal_edge_flux_history_m3_s"],
                n_steps=n_steps,
                name="internal_edge_flux_history_m3_s",
            ),
            prescribed_head_history_m_by_cell=step_history_from_history(
                prescribed_head_history,
                n_steps=n_steps,
                name="prescribed_head_history_m_by_cell",
            ),
            seconds_per_day=seconds_per_day,
        )
    )
    storage_change_m3_day = compute_storage_change_flux_m3_day(
        head_history_m=head_history,
        cell_area_m2=cell_area_m2,
        cell_storage_coefficient=cell_storage,
        dt_days=dt_days,
        elapsed_days=elapsed_days,
        cell_mask=free_mask,
    )
    return BoussinesqFreeControlVolumeBudget(
        free_cell_mask=free_mask,
        recharge_flux_m3_day=np.asarray(recharge_flux_m3_day, dtype=float),
        drainage_flux_m3_day=np.asarray(drainage_flux_m3_day, dtype=float),
        surface_excess_flux_m3_day=np.asarray(surface_excess_flux_m3_day, dtype=float),
        east_boundary_inflow_m3_day=np.asarray(east_boundary_inflow_m3_day, dtype=float),
        east_boundary_outflow_m3_day=np.asarray(east_boundary_outflow_m3_day, dtype=float),
        storage_change_m3_day=np.asarray(storage_change_m3_day, dtype=float),
    )


__all__ = [
    "BoussinesqFreeControlVolumeBudget",
    "compute_east_interface_flux_m3_day",
    "compute_free_control_volume_budget",
    "compute_storage_change_flux_m3_day",
    "load_bundle_cell_table",
    "load_east_interface_edge_data",
    "prescribed_cell_mask_from_history",
]
