"""Finite-volume assembly helpers shared by all current Boussinesq runtimes.

Public facade. Implementation is split across:

- `inputs.py` for runtime input normalization and constraint handling,
- `fluxes.py` for transmissivity and flux operators,
- `surface.py` for surface-interaction closures,
- `residuals.py` for steady/transient residual assembly,
- `residual_facade.py` for the canonical prescribed-cell path wrappers.
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
from hydromodpy.solver.boussinesq.assembly.residual_facade import (
    assemble_steady_residual,
    assemble_steady_residual_with_saturation_excess,
    assemble_transient_residual,
    assemble_transient_residual_with_saturation_excess,
)
from hydromodpy.solver.boussinesq.assembly.surface import (
    regularized_partition_surface_rate_from_balance,
)
from hydromodpy.solver.boussinesq.assembly.types import BoussinesqAssembly

__all__ = [
    "BoussinesqAssembly",
    "accumulate_boundary_flux_residual",
    "accumulate_internal_flux_residual",
    "apply_prescribed_head_to_cells",
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
    "transmissivity_from_head",
]
