"""Field declarations for the Boussinesq runtime knobs on FlowConfig.

This mixin exposes the flat ``runtime_*`` / ``vi_*`` / ``ts_vi_*``
fields kept on :class:`FlowConfig` for backward-compatible TOML
payloads. The mixin keeps the field declarations isolated so
``flow_config.py`` focuses on the user-facing payload (``param_list``,
``param``, ``bc``, ``ic``, ``sinks_sources``).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.flow.flow_runtime_config import (
    DEFAULT_PARTITION_RELEASE_DEPTH_M,
    FlowRuntimeConfig,
)


class FlowRuntimeFields(HydroModelBase):
    """Flat runtime fields kept on :class:`FlowConfig` for TOML compat."""

    runtime_backend: Annotated[
        Literal["auto", "local", "scipy", "scipy_sparse", "petsc"], Profile.USER
    ] = Field(
        default="auto",
        description=(
            "Engine the Boussinesq solver uses for its nonlinear solve. 'local' and "
            "'scipy' build a dense matrix and run on at most 400 cells; 'scipy_sparse' "
            "and 'petsc' (it needs petsc4py) have no such limit. 'auto' runs 'local' "
            "up to 400 cells and 'scipy_sparse' above, and logs the choice. The "
            "MODFLOW solvers do not read it."
        ),
        examples=["auto", "scipy_sparse"],
        json_schema_extra=field_metadata(stability="experimental"),
    )
    surface_interaction_model: Annotated[
        Literal[
            "auto",
            "regularized_partition",
            "complementarity",
            "vi_obstacle",
            "ts_vi_obstacle",
        ],
        Profile.DEV,
    ] = Field(
        default="auto",
        description=(
            "Optional Boussinesq surface-interaction closure selector. "
            "'regularized_partition' uses the Marcais-style q_ex = G_r(theta) "
            "R(balance) law; 'complementarity' uses the mixed PETSc "
            "q_ex-perp-(z_top-h) formulation; 'vi_obstacle' uses the "
            "experimental PETSc head-only VI obstacle formulation; 'auto' "
            "keeps the historical backend-dependent default."
        ),
        examples=["auto", "regularized_partition"],
        json_schema_extra=field_metadata(stability="experimental"),
    )
    partition_release_depth_m: Annotated[float, Profile.USER] = Field(
        default=DEFAULT_PARTITION_RELEASE_DEPTH_M,
        gt=0.0,
        description=(
            "Depth scale, in metres, of the regularized partition, the surface "
            "closure the Boussinesq solver uses by default on every engine but "
            "petsc. A cell whose water table lies d metres below "
            "the land surface releases at the surface the share exp(-d / depth) "
            "of the water it receives, its lateral inflow plus its recharge and "
            "wells: all of it with the water table at the surface, 37 % at one "
            "depth scale, 2e-9 at 1 m with the default 0.05 m. It stands for the "
            "microtopography over which seepage starts, and smooths the onset of "
            "seepage for the Newton solve. A smaller value comes closer to the "
            "exact threshold of the complementarity closure and makes the solve "
            "stiffer. The other closures and the MODFLOW solvers do not read it."
        ),
        examples=[0.05, 0.02],
        json_schema_extra=field_metadata(unit="m"),
    )
    runtime_max_iterations: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the nonlinear iteration budget used by the "
            "Boussinesq runtime backend."
        ),
        json_schema_extra=field_metadata(
            widget_type="input",
            unit="-",
            display_name_fr="Itérations max (solveur)",
            help_text_fr="Budget d'itérations non-linéaires pour le solveur.",
            display_min=1,
            display_max=100_000,
        ),
    )
    runtime_tol_residual_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the infinity-norm residual tolerance used "
            "by the Boussinesq runtime backend."
        ),
    )
    runtime_tol_state_update_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the infinity-norm state-update tolerance "
            "used by Boussinesq backends that track it."
        ),
    )
    vi_substeps_per_period: Annotated[int, Profile.DEV] = Field(
        default=1,
        description=(
            "Fixed number of Backward-Euler substeps per time step for the "
            "experimental PETSc VI obstacle runtime. A stress period holds "
            "simulation.time.substeps_per_period time steps. Rate-based forcing "
            "values are kept unchanged on each substep."
        ),
    )
    vi_substep_on_failure: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description=(
            "When true, retry a failed PETSc VI obstacle time step with increasing substep counts."
        ),
    )
    vi_max_adaptive_substeps: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Maximum number of PETSc VI obstacle substeps allowed for adaptive failure retries."
        ),
    )
    ts_vi_steps_per_period: Annotated[int, Profile.DEV] = Field(
        default=4,
        description=(
            "Fixed PETSc TS Backward-Euler steps per time step for the "
            "experimental TS VI obstacle runtime. A stress period holds "
            "simulation.time.substeps_per_period time steps."
        ),
    )
    ts_vi_adapt: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Enable experimental PETSc TS adaptivity for the TS VI obstacle runtime.",
    )
    ts_vi_dt_min_fraction: Annotated[float, Profile.DEV] = Field(
        default=1.0 / 64.0,
        description="Minimum TS VI step as a fraction of the time-step length.",
    )
    ts_vi_dt_max_fraction: Annotated[float, Profile.DEV] = Field(
        default=1.0 / 4.0,
        description="Maximum TS VI step as a fraction of the time-step length.",
    )
    ts_vi_type: Annotated[str, Profile.DEV] = Field(
        default="beuler",
        description="PETSc TS type for the experimental TS VI obstacle runtime.",
    )
    ts_vi_snes_type: Annotated[str, Profile.DEV] = Field(
        default="vinewtonrsls",
        description="PETSc SNES type for the experimental TS VI obstacle runtime.",
    )

    @property
    def runtime(self) -> FlowRuntimeConfig:
        """Return a grouped Boussinesq runtime view assembled on demand."""
        return FlowRuntimeConfig(
            backend=self.runtime_backend,
            surface_model=self.surface_interaction_model,
            partition_release_depth_m=self.partition_release_depth_m,
            max_iterations=self.runtime_max_iterations,
            tol_residual_inf=self.runtime_tol_residual_inf,
            tol_state_update_inf=self.runtime_tol_state_update_inf,
            vi_substeps_per_period=self.vi_substeps_per_period,
            vi_substep_on_failure=self.vi_substep_on_failure,
            vi_max_adaptive_substeps=self.vi_max_adaptive_substeps,
            ts_vi_steps_per_period=self.ts_vi_steps_per_period,
            ts_vi_adapt=self.ts_vi_adapt,
            ts_vi_dt_min_fraction=self.ts_vi_dt_min_fraction,
            ts_vi_dt_max_fraction=self.ts_vi_dt_max_fraction,
            ts_vi_type=self.ts_vi_type,
            ts_vi_snes_type=self.ts_vi_snes_type,
        )


__all__ = ["FlowRuntimeFields"]
