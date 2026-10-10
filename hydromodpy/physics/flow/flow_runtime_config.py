"""Grouped runtime view for Boussinesq solver knobs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

DEFAULT_PARTITION_RELEASE_DEPTH_M = 0.05


class FlowRuntimeConfig(HydroModelBase):
    """Grouped view of the Boussinesq runtime fields on :class:`FlowConfig`.

    The spec (``02_config_pydantic.md`` §3.3) groups all runtime-only
    Boussinesq solver knobs under a single ``runtime`` sub-block so that
    user-facing templates do not scatter ``runtime_backend``,
    ``runtime_max_iterations`` and ``runtime_tol_*`` at the top of
    ``[flow]``. We keep the flat flow-config fields for existing
    consumers and expose this dataclass-style view via
    :attr:`FlowConfig.runtime` for new call-sites.
    """

    backend: Annotated[Literal["auto", "local", "scipy", "scipy_sparse", "petsc"], Profile.DEV] = (
        Field(
            default="auto",
            description=("Nonlinear runtime backend used by Boussinesq-style solvers."),
        )
    )
    surface_model: Annotated[
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
            "Surface-interaction closure selector (Boussinesq). "
            "``regularized_partition`` uses the Marcais-style q_ex = G_r(theta) "
            "R(balance) law; ``complementarity`` uses the PETSc "
            "q_ex-perp-(z_top-h) formulation; ``vi_obstacle`` uses the "
            "experimental PETSc head-only VI obstacle formulation; ``auto`` "
            "keeps the historical backend-dependent default."
        ),
    )
    partition_release_depth_m: Annotated[float, Profile.DEV] = Field(
        default=DEFAULT_PARTITION_RELEASE_DEPTH_M,
        gt=0.0,
        description=(
            "Depth scale, in metres, of the regularized partition: the share "
            "exp(-d / depth) of its supply that a cell releases with its water "
            "table d metres below the land surface."
        ),
    )
    max_iterations: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description="Optional override for the nonlinear iteration budget.",
    )
    tol_residual_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description="Optional override for the inf-norm residual tolerance.",
    )
    tol_state_update_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description="Optional override for the inf-norm state-update tolerance.",
    )
    vi_substeps_per_period: Annotated[int, Profile.DEV] = Field(
        default=1,
        description=(
            "Fixed number of Backward-Euler substeps per time step for the "
            "experimental PETSc VI obstacle runtime."
        ),
    )
    vi_substep_on_failure: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description=(
            "Retry failed PETSc VI obstacle time steps with more substeps, up to "
            "vi_max_adaptive_substeps."
        ),
    )
    vi_max_adaptive_substeps: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description="Maximum substeps allowed when PETSc VI adaptive retry is enabled.",
    )
    ts_vi_steps_per_period: Annotated[int, Profile.DEV] = Field(
        default=4,
        description=(
            "Fixed PETSc TS Backward-Euler steps per time step for the "
            "experimental TS VI obstacle runtime."
        ),
    )
    ts_vi_adapt: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Enable experimental PETSc TS time-step adaptivity for TS VI obstacle.",
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
        description="PETSc TS type used by the experimental TS VI obstacle runtime.",
    )
    ts_vi_snes_type: Annotated[str, Profile.DEV] = Field(
        default="vinewtonrsls",
        description="PETSc SNES type used inside the experimental TS VI obstacle runtime.",
    )


__all__ = ["DEFAULT_PARTITION_RELEASE_DEPTH_M", "FlowRuntimeConfig"]
