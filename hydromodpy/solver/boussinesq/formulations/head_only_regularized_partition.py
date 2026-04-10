"""Head-only formulation with the regularized-partition surface closure."""

from __future__ import annotations

from hydromodpy.solver.boussinesq.assembly import (
    assemble_steady_residual,
    assemble_transient_residual,
)
from hydromodpy.solver.boussinesq.formulations.common import (
    BoussinesqFormulationSpec,
)

HEAD_ONLY_REGULARIZED_PARTITION = BoussinesqFormulationSpec(
    id="head_only_regularized_partition",
    unknown_layout="head_only",
    surface_closure="regularized_partition",
    steady_residual_label="steady_regularized_partition_head_balance",
    transient_residual_label="transient_regularized_partition_head_balance",
    description=(
        "Head-only residual where saturation excess is reconstructed from the "
        "regularized partition law q_ex = G_r(theta) R(balance)."
    ),
)

assemble_steady_head_only_regularized_partition = assemble_steady_residual
assemble_transient_head_only_regularized_partition = assemble_transient_residual


__all__ = [
    "HEAD_ONLY_REGULARIZED_PARTITION",
    "assemble_steady_head_only_regularized_partition",
    "assemble_transient_head_only_regularized_partition",
]
