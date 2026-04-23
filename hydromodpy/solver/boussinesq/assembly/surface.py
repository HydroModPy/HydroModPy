"""Surface-interaction helpers for the Boussinesq assembly."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly.fluxes import saturated_thickness_from_head
from hydromodpy.solver.boussinesq.assembly.inputs import as_cell_vector
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def regularized_partition_surface_rate_from_balance(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    lateral_flux_residual_m3_s: np.ndarray,
    surface_input_rate_m_s: np.ndarray | float | None,
    regularization_radius: float,
) -> np.ndarray:
    """Return the Marcais-style regularized partition surface flux."""
    if float(regularization_radius) <= 0.0:
        raise ValueError("regularization_radius must be strictly positive.")

    max_thickness = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    thickness = saturated_thickness_from_head(mesh, head_m)
    saturation_ratio = np.divide(
        thickness,
        max_thickness,
        out=np.zeros(mesh.n_cells, dtype=float),
        where=max_thickness > 0.0,
    )
    surface_input = as_cell_vector(
        surface_input_rate_m_s,
        n_cells=mesh.n_cells,
        label="surface_input_rate_m_s",
    )
    balance_rate = (
        -np.asarray(lateral_flux_residual_m3_s, dtype=float) / mesh.cell_area_m2
    ) + np.maximum(surface_input, 0.0)
    ramp_rate = np.maximum(balance_rate, 0.0)
    regularization = np.exp(
        -(1.0 - np.clip(saturation_ratio, 0.0, 1.0)) / float(regularization_radius)
    )
    return regularization * ramp_rate


def resolve_saturation_excess_rate(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    lateral_flux_residual_m3_s: np.ndarray,
    recharge_rate_m_s: np.ndarray,
    regularization_radius: float,
    saturation_excess_rate_m_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return the saturation-excess rate used by one residual assembly."""
    if saturation_excess_rate_m_s is not None:
        return as_cell_vector(
            saturation_excess_rate_m_s,
            n_cells=mesh.n_cells,
            label="saturation_excess_rate_m_s",
        )
    return regularized_partition_surface_rate_from_balance(
        mesh,
        head_m,
        lateral_flux_residual_m3_s=lateral_flux_residual_m3_s,
        surface_input_rate_m_s=np.maximum(recharge_rate_m_s, 0.0),
        regularization_radius=float(regularization_radius),
    )


__all__ = [
    "regularized_partition_surface_rate_from_balance",
    "resolve_saturation_excess_rate",
]
