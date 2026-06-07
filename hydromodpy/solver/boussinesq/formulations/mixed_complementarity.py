"""Mixed head-plus-q_ex-plus-q_dry formulation with complementarity closure."""

from __future__ import annotations

from hydromodpy.solver.boussinesq.formulations.common import (
    BoussinesqFormulationSpec,
)

MIXED_COMPLEMENTARITY = BoussinesqFormulationSpec(
    id="mixed_complementarity",
    unknown_layout="head_plus_qex_qdry",
    surface_closure="complementarity",
    steady_residual_label="steady_mixed_complementarity_balance",
    transient_residual_label="transient_mixed_complementarity_balance",
    description=(
        "Mixed formulation with hydraulic head, saturation-excess rate and dry-deficit "
        "rate as unknowns. The algebraic rates enforce upper and lower head obstacles."
    ),
)


__all__ = [
    "MIXED_COMPLEMENTARITY",
]
