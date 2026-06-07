"""Public residual assembly wrappers on the canonical prescribed-cell path.

Thin facades over the generic residual builders in `residuals.py`. These keep
the call sites concise by hiding the boundary-edge boundary-head argument
which is unused on the canonical path.
"""

from __future__ import annotations

from hydromodpy.solver.boussinesq.assembly.residuals import (
    assemble_steady_residual_generic,
    assemble_steady_residual_with_saturation_excess_generic,
    assemble_transient_residual_generic,
    assemble_transient_residual_with_saturation_excess_generic,
)
from hydromodpy.solver.boussinesq.assembly.types import BoussinesqAssembly
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

__all__ = [
    "assemble_steady_residual",
    "assemble_steady_residual_with_saturation_excess",
    "assemble_transient_residual",
    "assemble_transient_residual_with_saturation_excess",
]


def assemble_transient_residual(
    mesh: BoussinesqMesh,
    *,
    head_m,
    head_prev_m,
    dt_seconds: float,
    recharge_rate_m_s=None,
    well_flux_m3_s=None,
    prescribed_head_m_by_cell=None,
    drainage_conductance_m2_s=None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one transient residual on the canonical prescribed-cell path."""
    return assemble_transient_residual_generic(
        mesh,
        head_m=head_m,
        head_prev_m=head_prev_m,
        dt_seconds=dt_seconds,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=regularization_radius,
    )


def assemble_transient_residual_with_saturation_excess(
    mesh: BoussinesqMesh,
    *,
    head_m,
    head_prev_m,
    dt_seconds: float,
    saturation_excess_rate_m_s,
    recharge_rate_m_s=None,
    well_flux_m3_s=None,
    prescribed_head_m_by_cell=None,
    drainage_conductance_m2_s=None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one transient mixed residual on the canonical prescribed-cell path."""
    return assemble_transient_residual_with_saturation_excess_generic(
        mesh,
        head_m=head_m,
        head_prev_m=head_prev_m,
        dt_seconds=dt_seconds,
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=regularization_radius,
    )


def assemble_steady_residual(
    mesh: BoussinesqMesh,
    *,
    head_m,
    recharge_rate_m_s=None,
    well_flux_m3_s=None,
    prescribed_head_m_by_cell=None,
    drainage_conductance_m2_s=None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble the steady residual on the canonical prescribed-cell path."""
    return assemble_steady_residual_generic(
        mesh,
        head_m=head_m,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=regularization_radius,
    )


def assemble_steady_residual_with_saturation_excess(
    mesh: BoussinesqMesh,
    *,
    head_m,
    saturation_excess_rate_m_s,
    recharge_rate_m_s=None,
    well_flux_m3_s=None,
    prescribed_head_m_by_cell=None,
    drainage_conductance_m2_s=None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one steady mixed residual on the canonical prescribed-cell path."""
    return assemble_steady_residual_with_saturation_excess_generic(
        mesh,
        head_m=head_m,
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=regularization_radius,
    )
