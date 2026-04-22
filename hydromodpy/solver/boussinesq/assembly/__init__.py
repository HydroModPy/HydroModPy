"""Finite-volume assembly helpers shared by all current Boussinesq runtimes.

This module remains the public faÃ§ade of the Boussinesq physical assembly.
The implementation is now split internally into:

- `inputs.py` for runtime input normalization and constraint handling,
- `fluxes.py` for transmissivity and flux operators,
- `surface.py` for surface-interaction closures,
- `residuals.py` for steady/transient residual assembly.
"""

from __future__ import annotations

from hydromodpy.solver.boussinesq.assembly.fluxes import (
    accumulate_boundary_flux_residual,
    accumulate_internal_flux_residual,
    boundary_head_edge_flux_from_head,
    drainage_outflow_from_head,
    internal_edge_flux_from_head,
    saturated_thickness_from_head,
    transmissivity_from_head,
)
from hydromodpy.solver.boussinesq.assembly.inputs import (
    apply_prescribed_head_to_cells,
    resolve_boundary_head_inputs,
)
from hydromodpy.solver.boussinesq.assembly.residuals import (
    assemble_steady_residual_generic as _assemble_steady_residual_generic,
    assemble_steady_residual_with_saturation_excess_generic as _assemble_steady_residual_with_saturation_excess_generic,
    assemble_transient_residual_generic as _assemble_transient_residual_generic,
    assemble_transient_residual_with_saturation_excess_generic as _assemble_transient_residual_with_saturation_excess_generic,
    assemble_spatial_terms as _assemble_spatial_terms,
)
from hydromodpy.solver.boussinesq.assembly.surface import (
    regularized_partition_surface_rate_from_balance,
    saturation_excess_rate_from_balance,
)
from hydromodpy.solver.boussinesq.assembly.types import BoussinesqAssembly
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


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
    return _assemble_transient_residual_generic(
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
    return _assemble_transient_residual_with_saturation_excess_generic(
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
    return _assemble_steady_residual_generic(
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
    return _assemble_steady_residual_with_saturation_excess_generic(
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


__all__ = [
    "BoussinesqAssembly",
    "apply_prescribed_head_to_cells",
    "accumulate_boundary_flux_residual",
    "accumulate_internal_flux_residual",
    "assemble_steady_residual",
    "assemble_steady_residual_with_saturation_excess",
    "assemble_transient_residual",
    "assemble_transient_residual_with_saturation_excess",
    "boundary_head_edge_flux_from_head",
    "drainage_outflow_from_head",
    "internal_edge_flux_from_head",
    "regularized_partition_surface_rate_from_balance",
    "resolve_boundary_head_inputs",
    "saturated_thickness_from_head",
    "saturation_excess_rate_from_balance",
    "transmissivity_from_head",
]
