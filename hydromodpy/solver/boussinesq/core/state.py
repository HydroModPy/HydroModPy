"""Normalized in-memory solver state for the Boussinesq backend."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class BoussinesqState:
    """Normalized flow state carried by the Boussinesq runtime.

    The state stores both the current solution and, when available, the short
    histories needed by validation and post-processing helpers.
    """

    head_m: np.ndarray
    saturated_thickness_m: np.ndarray
    recharge_rate_m_s: np.ndarray | None = None
    well_flux_m3_s: np.ndarray | None = None
    saturation_excess_rate_m_s: np.ndarray | None = None
    recharge_rate_history_m_s: np.ndarray | None = None
    well_flux_history_m3_s: np.ndarray | None = None
    head_history_m: np.ndarray | None = None
    saturated_thickness_history_m: np.ndarray | None = None
    saturation_excess_history_m_s: np.ndarray | None = None
    internal_edge_flux_m3_s: np.ndarray | None = None
    internal_edge_flux_history_m3_s: np.ndarray | None = None
    imposed_head_edge_flux_m3_s: np.ndarray | None = None
    imposed_head_edge_flux_history_m3_s: np.ndarray | None = None
    prescribed_head_flux_m3_s: np.ndarray | None = None
    prescribed_head_flux_history_m3_s: np.ndarray | None = None
    prescribed_head_m_by_cell: np.ndarray | None = None
    prescribed_head_history_m_by_cell: np.ndarray | None = None
    drainage_flux_m3_s: np.ndarray | None = None
    drainage_flux_history_m3_s: np.ndarray | None = None
    period_lengths_seconds: tuple[float, ...] = ()
    nonlinear_iterations: tuple[int, ...] = ()
    converged_by_period: tuple[bool, ...] = ()


__all__ = ["BoussinesqState"]
