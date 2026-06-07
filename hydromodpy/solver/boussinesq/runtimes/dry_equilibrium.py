"""Dry-equilibrium probes for Boussinesq obstacle solves.

The helpers in this module are deliberately small and PETSc-free. They are used
to distinguish a physically dry lower-obstacle equilibrium from a failed Newton
iterate that merely collapsed near the bottom bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly.fluxes import (
    accumulate_internal_flux_residual,
    drainage_outflow_from_head,
    harmonic_conductivity,
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.assembly.inputs import (
    as_cell_vector,
    as_prescribed_head_cell_vector,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

_MIN_DISTANCE_M = 1.0e-12


@dataclass(frozen=True, kw_only=True)
class EffectiveSteadyBalance:
    """Steady balance evaluated with an optional effective-thickness floor."""

    head_m: np.ndarray
    residual_m3_s: np.ndarray
    internal_edge_flux_m3_s: np.ndarray
    drainage_flux_m3_s: np.ndarray
    physical_saturated_thickness_m: np.ndarray
    effective_saturated_thickness_m: np.ndarray
    transmissivity_m2_s: np.ndarray


@dataclass(frozen=True, kw_only=True)
class DryEquilibriumResult:
    """Result of a dry lower-obstacle equilibrium check."""

    candidate_checked: bool
    detected: bool
    rejected_reason: str | None
    positive_forcing_detected: bool
    min_residual_m3_s: float | None
    projected_residual_inf: float | None
    vi_violations_count: int
    minimum_saturated_thickness_m: float
    head_m: np.ndarray
    residual_m3_s: np.ndarray
    internal_edge_flux_m3_s: np.ndarray
    diagnostics: dict[str, Any]


def physical_saturated_thickness(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return the hydrologic saturated thickness, without numerical floor."""
    return saturated_thickness_from_head(mesh, head_m)


def effective_saturated_thickness(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    minimum_saturated_thickness_m: float = 0.0,
) -> np.ndarray:
    """Return the thickness used by a numerical transmissivity regularization."""
    physical = physical_saturated_thickness(mesh, head_m)
    b_min = max(float(minimum_saturated_thickness_m), 0.0)
    if b_min <= 0.0:
        return physical
    max_thickness = np.maximum(
        np.asarray(mesh.z_top_m, dtype=float) - np.asarray(mesh.z_bottom_m, dtype=float),
        0.0,
    )
    floor = np.minimum(max_thickness, b_min)
    return np.maximum(physical, floor)


def saturated_thickness_diagnostics(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    minimum_saturated_thickness_m: float = 0.0,
    dry_tolerance_m: float = 1.0e-12,
) -> dict[str, Any]:
    """Return physical/effective thickness statistics for diagnostics."""
    physical = physical_saturated_thickness(mesh, head_m)
    effective = effective_saturated_thickness(
        mesh,
        head_m,
        minimum_saturated_thickness_m=minimum_saturated_thickness_m,
    )
    b_min = max(float(minimum_saturated_thickness_m), 0.0)
    at_floor = (
        np.isfinite(effective)
        & np.isfinite(physical)
        & (effective > physical + float(dry_tolerance_m))
    )
    dry = np.isfinite(physical) & (physical <= float(dry_tolerance_m))
    return {
        "minimum_saturated_thickness_m": b_min,
        "physical_saturated_thickness_min": _finite_min(physical),
        "physical_saturated_thickness_q01": _finite_quantile(physical, 0.01),
        "physical_saturated_thickness_q50": _finite_quantile(physical, 0.50),
        "physical_saturated_thickness_max": _finite_max(physical),
        "effective_saturated_thickness_min": _finite_min(effective),
        "effective_saturated_thickness_q01": _finite_quantile(effective, 0.01),
        "effective_saturated_thickness_q50": _finite_quantile(effective, 0.50),
        "effective_saturated_thickness_max": _finite_max(effective),
        "cells_physically_dry_count": int(np.count_nonzero(dry)),
        "cells_at_effective_floor_count": int(np.count_nonzero(at_floor)),
    }


def assemble_effective_steady_balance(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    minimum_saturated_thickness_m: float = 0.0,
) -> EffectiveSteadyBalance:
    """Assemble a steady balance using physical or effective transmissivity.

    This intentionally covers the small diagnostic subset needed for dry
    equilibrium probes: internal fluxes, drainage, recharge and cell wells. It
    does not apply prescribed-head constraints.
    """
    head = np.asarray(head_m, dtype=float).reshape(-1)
    if head.size != int(mesh.n_cells):
        raise ValueError(
            f"head_m must have length mesh.n_cells ({head.size} != {int(mesh.n_cells)})."
        )
    recharge = as_cell_vector(recharge_rate_m_s, n_cells=mesh.n_cells, label="recharge_rate_m_s")
    wells = as_cell_vector(well_flux_m3_s, n_cells=mesh.n_cells, label="well_flux_m3_s")
    physical = physical_saturated_thickness(mesh, head)
    effective = effective_saturated_thickness(
        mesh,
        head,
        minimum_saturated_thickness_m=minimum_saturated_thickness_m,
    )
    internal_flux = _internal_edge_flux_from_effective_thickness(mesh, head, effective)
    internal_residual = accumulate_internal_flux_residual(mesh, internal_flux)
    drainage = drainage_outflow_from_head(
        mesh,
        head,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    residual = (
        internal_residual + drainage - np.asarray(mesh.cell_area_m2, dtype=float) * recharge - wells
    )
    return EffectiveSteadyBalance(
        head_m=head.copy(),
        residual_m3_s=residual,
        internal_edge_flux_m3_s=internal_flux,
        drainage_flux_m3_s=drainage,
        physical_saturated_thickness_m=physical,
        effective_saturated_thickness_m=effective,
        transmissivity_m2_s=np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float) * effective,
    )


def detect_dry_equilibrium(
    mesh: BoussinesqMesh,
    *,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    minimum_saturated_thickness_m: float = 0.0,
    tol_bottom_vi: float = 1.0e-12,
    positive_forcing_tol: float = 0.0,
) -> DryEquilibriumResult:
    """Return whether ``h = z_bottom`` is a safe lower-obstacle VI solution."""
    h_dry = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1).copy()
    rejection = _positive_forcing_rejection(
        mesh,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        tol=float(tol_bottom_vi),
        positive_tol=float(positive_forcing_tol),
    )
    balance = assemble_effective_steady_balance(
        mesh,
        h_dry,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        minimum_saturated_thickness_m=minimum_saturated_thickness_m,
    )
    residual = balance.residual_m3_s
    lower_violation = residual < -float(tol_bottom_vi)
    upper_bound_violation = h_dry > np.asarray(mesh.z_top_m, dtype=float) + float(tol_bottom_vi)
    reason = rejection
    if reason is None and np.any(upper_bound_violation):
        reason = "dry head exceeds top elevation"
    if reason is None and np.any(lower_violation):
        reason = "lower-bound VI residual is negative"
    detected = reason is None
    projected = np.minimum(residual, 0.0)
    diagnostics = {
        "dry_equilibrium_candidate_checked": True,
        "dry_equilibrium_detected": bool(detected),
        "dry_equilibrium_rejected_reason": reason,
        "dry_equilibrium_positive_forcing_detected": rejection is not None,
        "dry_equilibrium_min_R": _finite_min(residual),
        "dry_equilibrium_vi_violations_count": int(np.count_nonzero(lower_violation)),
        "dry_equilibrium_max_internal_flux_m3_s": _finite_max(
            np.abs(balance.internal_edge_flux_m3_s)
        ),
        "dry_equilibrium_total_abs_internal_flux_m3_s": _finite_sum(
            np.abs(balance.internal_edge_flux_m3_s)
        ),
        **saturated_thickness_diagnostics(
            mesh,
            h_dry,
            minimum_saturated_thickness_m=minimum_saturated_thickness_m,
        ),
    }
    return DryEquilibriumResult(
        candidate_checked=True,
        detected=bool(detected),
        rejected_reason=reason,
        positive_forcing_detected=rejection is not None,
        min_residual_m3_s=_finite_min(residual),
        projected_residual_inf=_finite_max(np.abs(projected)),
        vi_violations_count=int(np.count_nonzero(lower_violation)),
        minimum_saturated_thickness_m=max(float(minimum_saturated_thickness_m), 0.0),
        head_m=h_dry,
        residual_m3_s=residual,
        internal_edge_flux_m3_s=balance.internal_edge_flux_m3_s,
        diagnostics=diagnostics,
    )


def _internal_edge_flux_from_effective_thickness(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    effective_thickness_m: np.ndarray,
) -> np.ndarray:
    head = np.asarray(head_m, dtype=float)
    thickness = np.asarray(effective_thickness_m, dtype=float)
    internal_flux = np.zeros(int(mesh.n_edges), dtype=float)
    for edge_index in range(int(mesh.n_edges)):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b < 0:
            continue
        conductivity_edge = harmonic_conductivity(
            float(mesh.hydraulic_conductivity_m_s[cell_a]),
            float(mesh.hydraulic_conductivity_m_s[cell_b]),
        )
        thickness_edge = 0.5 * (float(thickness[cell_a]) + float(thickness[cell_b]))
        transmissivity_edge = conductivity_edge * thickness_edge
        distance_m = max(float(mesh.edge_distance_m[edge_index]), _MIN_DISTANCE_M)
        tau = transmissivity_edge * float(mesh.edge_length_m[edge_index]) / distance_m
        internal_flux[edge_index] = -tau * (float(head[cell_b]) - float(head[cell_a]))
    return internal_flux


def _positive_forcing_rejection(
    mesh: BoussinesqMesh,
    *,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    boundary_head_m_by_edge: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    tol: float,
    positive_tol: float,
) -> str | None:
    recharge = as_cell_vector(recharge_rate_m_s, n_cells=mesh.n_cells, label="recharge_rate_m_s")
    forcing_tol = max(float(positive_tol), 0.0)
    if np.any(recharge > forcing_tol):
        return "positive recharge present"
    wells = as_cell_vector(well_flux_m3_s, n_cells=mesh.n_cells, label="well_flux_m3_s")
    if np.any(wells > forcing_tol):
        return "injecting well flux present"
    prescribed = as_prescribed_head_cell_vector(
        prescribed_head_m_by_cell,
        n_cells=mesh.n_cells,
        label="prescribed_head_m_by_cell",
    )
    prescribed_mask = np.isfinite(prescribed)
    if np.any(prescribed_mask & (prescribed > np.asarray(mesh.z_bottom_m, dtype=float) + tol)):
        return "prescribed head above bottom present"
    if boundary_head_m_by_edge is not None and np.any(np.isfinite(boundary_head_m_by_edge)):
        return "boundary head condition present"
    drainage = as_cell_vector(
        drainage_conductance_m2_s,
        n_cells=mesh.n_cells,
        label="drainage_conductance_m2_s",
    )
    if np.any(drainage < -forcing_tol):
        return "negative drainage conductance present"
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


def _finite_sum(values: np.ndarray) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.sum(finite))


def _finite_quantile(values: np.ndarray, q: float) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.quantile(finite, float(q)))


__all__ = [
    "DryEquilibriumResult",
    "EffectiveSteadyBalance",
    "assemble_effective_steady_balance",
    "detect_dry_equilibrium",
    "effective_saturated_thickness",
    "physical_saturated_thickness",
    "saturated_thickness_diagnostics",
]
