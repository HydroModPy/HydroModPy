"""
Pydantic chronicle schema for the transient 1D groundwater case.

The goal is to keep all user-facing case parameters in one validated place:
- domain and true hydraulic properties,
- boundary/recharge forcing controls,
- synthetic observation setup,
- nonlinear solver controls.
"""

from __future__ import annotations

from typing import Annotated, Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.analysis.calibration.cases.groundwater_1d.model import SUPPORTED_FORMULATIONS
from hydromodpy.core.config.param_level import ParamLevel


SUPPORTED_RECHARGE_MODES = ("hydro_step", "reservoir_chronicle")


class Groundwater1DChronicleSchema(BaseModel):
    """
    Schema for `[chronicle]` in the groundwater_1d case.
    """

    model_config = ConfigDict(extra="forbid")

    n_days: Annotated[int, ParamLevel("dev")] = Field(
        default=120, description="Number of simulation days."
    )
    dt_days: Annotated[float, ParamLevel("dev")] = Field(
        default=1.0, description="Time step size in days."
    )
    L_m: Annotated[float, ParamLevel("dev")] = Field(
        default=500.0, description="Domain length in metres."
    )
    xi_true_m: Annotated[float, ParamLevel("dev")] = Field(
        default=220.0, description="True interface position in metres."
    )
    nx: Annotated[int, ParamLevel("dev")] = Field(
        default=101, description="Number of spatial cells."
    )

    formulation_true: Annotated[str, ParamLevel("dev")] = Field(
        default="boussinesq", description="True formulation type for the 1D model."
    )
    H_linearized_m: Annotated[float, ParamLevel("dev")] = Field(
        default=12.0, description="Linearized reference head in metres."
    )

    Kam_true_m_per_day: Annotated[float, ParamLevel("dev")] = Field(
        default=5.0, description="True amont hydraulic conductivity in m/day."
    )
    Kav_true_m_per_day: Annotated[float, ParamLevel("dev")] = Field(
        default=1.2, description="True aval hydraulic conductivity in m/day."
    )
    Syam_true: Annotated[float, ParamLevel("dev")] = Field(
        default=0.18, description="True amont specific yield."
    )
    Syav_true: Annotated[float, ParamLevel("dev")] = Field(
        default=0.10, description="True aval specific yield."
    )

    h0_m: Annotated[float, ParamLevel("dev")] = Field(
        default=6.0, description="Initial head in metres."
    )

    recharge_mode: Annotated[str, ParamLevel("dev")] = Field(
        default="hydro_step", description="Recharge generation mode ('constant', 'seasonal', 'weather')."
    )
    recharge_wet_m_per_day: Annotated[float, ParamLevel("dev")] = Field(
        default=0.003, description="Wet-season recharge rate in m/day."
    )
    recharge_dry_m_per_day: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0004, description="Dry-season recharge rate in m/day."
    )
    recharge_wet_months: Annotated[list[int], ParamLevel("dev")] = Field(
        default_factory=lambda: [10, 11, 12, 1, 2, 3],
        description="Months considered as wet season.",
    )

    start_year: Annotated[int, ParamLevel("dev")] = Field(
        default=2000, description="Start year for weather-based recharge."
    )
    target_annual_precip_mm: Annotated[float, ParamLevel("dev")] = Field(
        default=800.0, description="Target annual precipitation in mm."
    )
    precip_seed: Annotated[int, ParamLevel("dev")] = Field(
        default=42, description="Random seed for precipitation generation."
    )
    runoff_coeff: Annotated[float, ParamLevel("dev")] = Field(
        default=0.15, description="Runoff coefficient."
    )
    losses_mm_day: Annotated[float, ParamLevel("dev")] = Field(
        default=1.5, description="Daily loss rate in mm/day."
    )
    losses_months: Annotated[list[int], ParamLevel("dev")] = Field(
        default_factory=lambda: [4, 5, 6, 7, 8, 9],
        description="Months where losses are applied.",
    )

    obs_x_m: Annotated[list[float], ParamLevel("dev")] = Field(
        default_factory=list, description="Observation locations along x in metres."
    )
    obs_t_stride: Annotated[int, ParamLevel("dev")] = Field(
        default=2, description="Temporal stride for observations."
    )
    obs_noise_std_m: Annotated[float, ParamLevel("dev")] = Field(
        default=0.03, description="Observation noise standard deviation in metres."
    )
    obs_seed: Annotated[int, ParamLevel("dev")] = Field(
        default=123, description="Random seed for observation noise."
    )

    picard_max_iter: Annotated[int, ParamLevel("dev")] = Field(
        default=40, description="Maximum Picard iterations."
    )
    picard_tol: Annotated[float, ParamLevel("dev")] = Field(
        default=1.0e-7, description="Picard convergence tolerance."
    )
    picard_relaxation: Annotated[float, ParamLevel("dev")] = Field(
        default=1.0, description="Picard relaxation factor."
    )
    head_floor_m: Annotated[float, ParamLevel("dev")] = Field(
        default=1.0e-6, description="Minimum allowable head in metres."
    )

    @field_validator("n_days", "nx", "obs_t_stride", "picard_max_iter", "start_year", "precip_seed")
    @classmethod
    def _validate_positive_ints(cls, value):
        out = int(value)
        if out <= 0:
            raise ValueError("value must be > 0")
        return out

    @field_validator(
        "dt_days",
        "L_m",
        "H_linearized_m",
        "Kam_true_m_per_day",
        "Kav_true_m_per_day",
        "Syam_true",
        "Syav_true",
        "h0_m",
        "target_annual_precip_mm",
        "picard_tol",
        "head_floor_m",
    )
    @classmethod
    def _validate_positive_floats(cls, value):
        out = float(value)
        if out <= 0.0:
            raise ValueError("value must be > 0")
        return out

    @field_validator(
        "obs_noise_std_m",
        "recharge_wet_m_per_day",
        "recharge_dry_m_per_day",
        "losses_mm_day",
    )
    @classmethod
    def _validate_non_negative_floats(cls, value):
        out = float(value)
        if out < 0.0:
            raise ValueError("value must be >= 0")
        return out

    @field_validator("obs_seed")
    @classmethod
    def _coerce_int(cls, value):
        return int(value)

    @field_validator("obs_x_m")
    @classmethod
    def _validate_obs_x_values(cls, values):
        out = [float(v) for v in values]
        return out

    @field_validator("recharge_wet_months", "losses_months")
    @classmethod
    def _validate_month_lists(cls, values):
        out = [int(v) for v in values]
        if len(out) == 0:
            raise ValueError("month list cannot be empty")
        if any(v < 1 or v > 12 for v in out):
            raise ValueError("month list values must be between 1 and 12")
        return out

    @field_validator("formulation_true")
    @classmethod
    def _validate_formulation(cls, value):
        key = str(value).strip().lower()
        if key not in SUPPORTED_FORMULATIONS:
            allowed = ", ".join(SUPPORTED_FORMULATIONS)
            raise ValueError(f"formulation_true must be one of: {allowed}")
        return key

    @field_validator("recharge_mode")
    @classmethod
    def _validate_recharge_mode(cls, value):
        key = str(value).strip().lower()
        if key not in SUPPORTED_RECHARGE_MODES:
            allowed = ", ".join(SUPPORTED_RECHARGE_MODES)
            raise ValueError(f"recharge_mode must be one of: {allowed}")
        return key

    @field_validator("picard_relaxation")
    @classmethod
    def _validate_relaxation(cls, value):
        out = float(value)
        if not (0.0 < out <= 1.0):
            raise ValueError("picard_relaxation must be in (0, 1]")
        return out

    @field_validator("Syam_true", "Syav_true")
    @classmethod
    def _validate_sy(cls, value):
        out = float(value)
        if out > 1.0:
            raise ValueError("specific yield must be <= 1")
        return out

    @field_validator("runoff_coeff")
    @classmethod
    def _validate_runoff_coeff(cls, value):
        out = float(value)
        if out < 0.0 or out > 1.0:
            raise ValueError("runoff_coeff must be in [0, 1]")
        return out

    @model_validator(mode="after")
    def _validate_domain_consistency(self):
        if not (0.0 < self.xi_true_m < self.L_m):
            raise ValueError("xi_true_m must satisfy 0 < xi_true_m < L_m")
        if any((x < 0.0 or x > self.L_m) for x in self.obs_x_m):
            raise ValueError("obs_x_m values must satisfy 0 <= x <= L_m")
        return self


def validate_groundwater_1d_chronicle_config(chronicle_cfg: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate and normalize groundwater chronicle configuration.
    """
    try:
        parsed = Groundwater1DChronicleSchema.model_validate(dict(chronicle_cfg))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")


__all__ = (
    "Groundwater1DChronicleSchema",
    "validate_groundwater_1d_chronicle_config",
)

