"""Head-only formulation with PETSc VI upper/lower obstacle closure."""

from __future__ import annotations

from hydromodpy.solver.boussinesq.formulations.common import (
    BoussinesqFormulationSpec,
)

HEAD_ONLY_VI_OBSTACLE = BoussinesqFormulationSpec(
    id="head_only_vi_obstacle",
    unknown_layout="head_only",
    surface_closure="vi_obstacle",
    steady_residual_label="steady_vi_obstacle_head_balance",
    transient_residual_label="transient_vi_obstacle_head_balance",
    description=(
        "Experimental head-only variational-inequality formulation with direct "
        "lower/upper head bounds. Surface-excess and dry-deficit rates are "
        "reconstructed after convergence as obstacle reactions."
    ),
)

HEAD_ONLY_TS_VI_OBSTACLE = BoussinesqFormulationSpec(
    id="head_only_ts_vi_obstacle",
    unknown_layout="head_only",
    surface_closure="ts_vi_obstacle",
    steady_residual_label="steady_vi_obstacle_head_balance",
    transient_residual_label="transient_ts_vi_obstacle_head_balance",
    description=(
        "Experimental head-only variational-inequality formulation integrated "
        "with PETSc TS. Head is bounded directly and surface/bottom reactions "
        "are reconstructed from the implicit TS residual."
    ),
)


__all__ = [
    "HEAD_ONLY_TS_VI_OBSTACLE",
    "HEAD_ONLY_VI_OBSTACLE",
]
