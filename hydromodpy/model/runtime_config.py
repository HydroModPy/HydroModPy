"""The settings of the Boussinesq solve, ``[flow.runtime]``.

The MODFLOW solvers read none of these. MODFLOW 6 and MODFLOW-NWT have their own
settings under ``[modflow6.runtime]`` and ``[modflownwt.runtime]``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile

_RUNTIME_BACKENDS = ("auto", "local", "scipy", "scipy_sparse", "petsc")
_SURFACE_MODELS = (
    "auto",
    "regularized_partition",
    "complementarity",
    "vi_obstacle",
    "ts_vi_obstacle",
)
_BOOL_TRUE = {"true", "1", "yes", "on"}
_BOOL_FALSE = {"false", "0", "no", "off"}


def normalize_runtime_backend(value: object) -> str:
    """Normalize the optional Boussinesq runtime backend selector."""
    text = str(value or "auto").strip().lower()
    if text not in _RUNTIME_BACKENDS:
        raise ValueError(
            "flow.runtime.backend must be 'auto', 'local', 'scipy', 'scipy_sparse', or 'petsc'"
        )
    return text


def normalize_surface_interaction_model(value: object) -> str:
    """Normalize the optional Boussinesq surface-interaction selector."""
    text = str(value or "auto").strip().lower() or "auto"
    if text not in _SURFACE_MODELS:
        raise ValueError(
            "flow.runtime.surface_interaction_model must be 'auto', "
            "'regularized_partition', 'complementarity', 'vi_obstacle', "
            "or 'ts_vi_obstacle'"
        )
    return text


def normalize_positive_int(value: object, *, field: str, default: int | None = None) -> int | None:
    """Validate a strictly-positive integer; an empty value takes ``default``."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(f"flow.{field} must be a positive integer")
    numeric = float(str(value).strip())
    if not numeric.is_integer() or numeric <= 0:
        raise ValueError(f"flow.{field} must be a positive integer")
    return int(numeric)


def normalize_bool(value: object, *, field: str) -> bool:
    """Validate a boolean flag accepting common string forms."""
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    raise ValueError(f"flow.{field} must be a boolean")


def normalize_positive_float(
    value: object, *, field: str, default: float | None = None
) -> float | None:
    """Validate a strictly-positive float; an empty value takes ``default``."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(f"flow.{field} must be a positive number")
    numeric = float(str(value).strip())
    if numeric <= 0.0:
        raise ValueError(f"flow.{field} must be a positive number")
    return numeric


DEFAULT_PARTITION_RELEASE_DEPTH_M = 0.05

FLOW_RUNTIME_KEYS: dict[str, str] = {
    "runtime_backend": "backend",
    "surface_interaction_model": "surface_interaction_model",
    "partition_release_depth_m": "partition_release_depth_m",
    "runtime_max_iterations": "max_iterations",
    "runtime_tol_residual_inf": "tol_residual_inf",
    "runtime_tol_state_update_inf": "tol_state_update_inf",
    "vi_substeps_per_period": "vi_substeps_per_period",
    "vi_substep_on_failure": "vi_substep_on_failure",
    "vi_max_adaptive_substeps": "vi_max_adaptive_substeps",
    "ts_vi_steps_per_period": "ts_vi_steps_per_period",
    "ts_vi_adapt": "ts_vi_adapt",
    "ts_vi_dt_min_fraction": "ts_vi_dt_min_fraction",
    "ts_vi_dt_max_fraction": "ts_vi_dt_max_fraction",
    "ts_vi_type": "ts_vi_type",
    "ts_vi_snes_type": "ts_vi_snes_type",
}
"""What a key of [flow] was once called, mapped to its name in [flow.runtime]."""


class FlowRuntimeConfig(HydroModelBase):
    """How the Boussinesq solver runs its nonlinear solve."""

    backend: Annotated[Literal["auto", "local", "scipy", "scipy_sparse", "petsc"], Profile.USER] = (
        Field(
            default="auto",
            description=(
                "Engine the Boussinesq solver uses for its nonlinear solve. 'local' and "
                "'scipy' build a dense matrix and run on at most 400 cells; 'scipy_sparse' "
                "and 'petsc' (it needs petsc4py) have no such limit. 'auto' runs 'local' "
                "up to 400 cells and 'scipy_sparse' above, and logs the choice. The "
                "MODFLOW solvers do not read it."
            ),
            examples=["auto", "scipy_sparse"],
            json_schema_extra=field_metadata(
                stability="experimental", renamed_from=["flow.runtime_backend"]
            ),
        )
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
            "q_ex-perp-(z_top-h) formulation; 'vi_obstacle' uses the PETSc "
            "head-only VI obstacle formulation, and 'ts_vi_obstacle' the same "
            "one integrated by PETSc TS; 'auto' keeps the historical "
            "backend-dependent default."
        ),
        examples=["auto", "regularized_partition"],
        json_schema_extra=field_metadata(
            experimental_values=["complementarity", "vi_obstacle", "ts_vi_obstacle"],
            renamed_from=["flow.surface_interaction_model"],
        ),
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
        json_schema_extra=field_metadata(
            unit="m", stability="experimental", renamed_from=["flow.partition_release_depth_m"]
        ),
    )
    max_iterations: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the nonlinear iteration budget used by the "
            "Boussinesq runtime backend."
        ),
        json_schema_extra=field_metadata(
            widget_type="input",
            unit="-",
            display_min=1,
            display_max=100_000,
            stability="experimental",
            renamed_from=["flow.runtime_max_iterations"],
        ),
    )
    tol_residual_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the infinity-norm residual tolerance used "
            "by the Boussinesq runtime backend."
        ),
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.runtime_tol_residual_inf"]
        ),
    )
    tol_state_update_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the infinity-norm state-update tolerance "
            "used by Boussinesq backends that track it."
        ),
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.runtime_tol_state_update_inf"]
        ),
    )
    vi_substeps_per_period: Annotated[int, Profile.DEV] = Field(
        default=1,
        description=(
            "Fixed number of Backward-Euler substeps per time step for the "
            "PETSc VI obstacle runtime. A stress period holds "
            "simulation.time.substeps_per_period time steps. Rate-based forcing "
            "values are kept unchanged on each substep."
        ),
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.vi_substeps_per_period"], unit="-"
        ),
    )
    vi_substep_on_failure: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description=(
            "When true, retry a failed PETSc VI obstacle time step with increasing substep counts."
        ),
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.vi_substep_on_failure"]
        ),
    )
    vi_max_adaptive_substeps: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Maximum number of PETSc VI obstacle substeps allowed for adaptive failure retries."
        ),
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.vi_max_adaptive_substeps"], unit="-"
        ),
    )
    ts_vi_steps_per_period: Annotated[int, Profile.DEV] = Field(
        default=4,
        description=(
            "Fixed PETSc TS Backward-Euler steps per time step for the "
            "TS VI obstacle runtime. A stress period holds "
            "simulation.time.substeps_per_period time steps."
        ),
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.ts_vi_steps_per_period"], unit="-"
        ),
    )
    ts_vi_adapt: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Enable PETSc TS adaptivity for the TS VI obstacle runtime.",
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.ts_vi_adapt"]
        ),
    )
    ts_vi_dt_min_fraction: Annotated[float, Profile.DEV] = Field(
        default=1.0 / 64.0,
        description="Minimum TS VI step as a fraction of the time-step length.",
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.ts_vi_dt_min_fraction"], unit="-"
        ),
    )
    ts_vi_dt_max_fraction: Annotated[float, Profile.DEV] = Field(
        default=1.0 / 4.0,
        description="Maximum TS VI step as a fraction of the time-step length.",
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.ts_vi_dt_max_fraction"], unit="-"
        ),
    )
    ts_vi_type: Annotated[str, Profile.DEV] = Field(
        default="beuler",
        description="PETSc TS type for the TS VI obstacle runtime.",
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.ts_vi_type"]
        ),
    )
    ts_vi_snes_type: Annotated[str, Profile.DEV] = Field(
        default="vinewtonrsls",
        description="PETSc SNES type for the TS VI obstacle runtime.",
        json_schema_extra=field_metadata(
            stability="experimental", renamed_from=["flow.ts_vi_snes_type"]
        ),
    )

    @field_validator("backend", mode="before")
    @classmethod
    def _validate_backend(cls, value):
        return normalize_runtime_backend(value)

    @field_validator("surface_interaction_model", mode="before")
    @classmethod
    def _validate_surface_interaction_model(cls, value):
        return normalize_surface_interaction_model(value)

    @field_validator("max_iterations", mode="before")
    @classmethod
    def _validate_max_iterations(cls, value):
        return normalize_positive_int(value, field="flow.runtime.max_iterations")

    @field_validator("vi_substeps_per_period", mode="before")
    @classmethod
    def _validate_vi_substeps_per_period(cls, value):
        return normalize_positive_int(value, field="vi_substeps_per_period", default=1)

    @field_validator("vi_substep_on_failure", mode="before")
    @classmethod
    def _validate_vi_substep_on_failure(cls, value):
        return normalize_bool(value, field="vi_substep_on_failure")

    @field_validator("vi_max_adaptive_substeps", mode="before")
    @classmethod
    def _validate_vi_max_adaptive_substeps(cls, value):
        return normalize_positive_int(value, field="vi_max_adaptive_substeps")

    @field_validator("ts_vi_steps_per_period", mode="before")
    @classmethod
    def _validate_ts_vi_steps_per_period(cls, value):
        return normalize_positive_int(value, field="ts_vi_steps_per_period", default=4)

    @field_validator("ts_vi_adapt", mode="before")
    @classmethod
    def _validate_ts_vi_adapt(cls, value):
        return normalize_bool(value, field="ts_vi_adapt")

    @field_validator("ts_vi_dt_min_fraction", "ts_vi_dt_max_fraction", mode="before")
    @classmethod
    def _validate_ts_vi_dt_fraction(cls, value, info):
        default = 1.0 / 64.0 if info.field_name == "ts_vi_dt_min_fraction" else 1.0 / 4.0
        return normalize_positive_float(value, field=info.field_name, default=default)

    @field_validator("tol_residual_inf", "tol_state_update_inf", mode="before")
    @classmethod
    def _validate_tolerances(cls, value, info):
        return normalize_positive_float(value, field=f"flow.runtime.{info.field_name}")


__all__ = ["DEFAULT_PARTITION_RELEASE_DEPTH_M", "FLOW_RUNTIME_KEYS", "FlowRuntimeConfig"]
