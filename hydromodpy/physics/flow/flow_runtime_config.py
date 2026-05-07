"""Grouped runtime view for Boussinesq solver knobs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


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

    backend: Annotated[Literal["local", "scipy", "scipy_sparse", "petsc"], Profile.DEV] = Field(
        default="local",
        description=("Nonlinear runtime backend used by Boussinesq-style solvers."),
    )
    surface_model: Annotated[
        Literal["auto", "regularized_partition", "complementarity"], Profile.DEV
    ] = Field(
        default="auto",
        description=(
            "Surface-interaction closure selector (Boussinesq). "
            "``regularized_partition`` uses the Marcais-style q_ex = G_r(theta) "
            "R(balance) law; ``complementarity`` uses the PETSc "
            "q_ex-perp-(z_top-h) formulation; ``auto`` keeps the historical "
            "backend-dependent default."
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


__all__ = ["FlowRuntimeConfig"]
