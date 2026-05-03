"""Mixed head-plus-q_ex formulation with complementarity closure."""

from __future__ import annotations

from hydromodpy.solver.boussinesq.formulations.common import (
    BoussinesqFormulationSpec,
)

MIXED_COMPLEMENTARITY = BoussinesqFormulationSpec(
    id="mixed_complementarity",
    unknown_layout="head_plus_qex",
    surface_closure="complementarity",
    steady_residual_label="steady_mixed_complementarity_balance",
    transient_residual_label="transient_mixed_complementarity_balance",
    description=(
        "Mixed formulation with hydraulic head and saturation-excess rate as "
        "unknowns, linked by the complementarity relation q_ex ⟂ (z_top - h)."
    ),
)


__all__ = [
    "MIXED_COMPLEMENTARITY",
]
