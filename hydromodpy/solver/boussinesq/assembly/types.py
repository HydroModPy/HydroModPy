"""Internal data containers used by the Boussinesq assembly façade."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BoussinesqAssembly:
    """Fully assembled nonlinear state for one candidate head field."""

    head_m: np.ndarray
    saturated_thickness_m: np.ndarray
    transmissivity_m2_s: np.ndarray
    recharge_rate_m_s: np.ndarray
    well_flux_m3_s: np.ndarray
    saturation_excess_rate_m_s: np.ndarray
    internal_edge_flux_m3_s: np.ndarray
    prescribed_head_flux_m3_s: np.ndarray
    prescribed_head_m_by_cell: np.ndarray
    head_constraint_residual_m: np.ndarray
    boundary_edge_flux_m3_s: np.ndarray
    drainage_flux_m3_s: np.ndarray
    flow_residual_m3_s: np.ndarray
    solver_residual: np.ndarray
    residual_m3_s: np.ndarray


@dataclass(frozen=True)
class _BoussinesqSpatialTerms:
    """Spatial contributions shared by steady and transient assembly."""

    head_m: np.ndarray
    saturated_thickness_m: np.ndarray
    transmissivity_m2_s: np.ndarray
    recharge_rate_m_s: np.ndarray
    well_flux_m3_s: np.ndarray
    saturation_excess_rate_m_s: np.ndarray
    internal_edge_flux_m3_s: np.ndarray
    internal_flux_residual_m3_s: np.ndarray
    boundary_edge_flux_m3_s: np.ndarray
    boundary_head_flux_residual_m3_s: np.ndarray
    drainage_flux_m3_s: np.ndarray


@dataclass(frozen=True)
class _BoundaryHeadInputs:
    """Normalized boundary-head inputs used internally by assembly/Jacobian code."""

    head_m: np.ndarray
    boundary_head_m_by_edge: np.ndarray
    prescribed_head_m_by_cell: np.ndarray
    prescribed_mask: np.ndarray


__all__ = [
    "BoussinesqAssembly",
    "_BoundaryHeadInputs",
    "_BoussinesqSpatialTerms",
]
