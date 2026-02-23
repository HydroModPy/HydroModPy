"""
Pydantic chronicle schema for the transient 1D groundwater case.

The goal is to keep all user-facing case parameters in one validated place:
- domain and true hydraulic properties,
- boundary/recharge forcing controls,
- synthetic observation setup,
- nonlinear solver controls.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.calibration.cases.groundwater_1d.model import SUPPORTED_FORMULATIONS


SUPPORTED_RECHARGE_MODES = ("hydro_step", "reservoir_chronicle")


class Groundwater1DChronicleSchema(BaseModel):
    """
    Schema for `[chronicle]` in the groundwater_1d case.
    """

    model_config = ConfigDict(extra="forbid")

    n_days: int = 120
    dt_days: float = 1.0
    L_m: float = 500.0
    xi_true_m: float = 220.0
    nx: int = 101

    formulation_true: str = "boussinesq"
    H_linearized_m: float = 12.0

    Kam_true_m_per_day: float = 5.0
    Kav_true_m_per_day: float = 1.2
    Syam_true: float = 0.18
    Syav_true: float = 0.10

    h0_m: float = 6.0

    recharge_mode: str = "hydro_step"
    recharge_wet_m_per_day: float = 0.003
    recharge_dry_m_per_day: float = 0.0004
    recharge_wet_months: list[int] = Field(default_factory=lambda: [10, 11, 12, 1, 2, 3])

    start_year: int = 2000
    target_annual_precip_mm: float = 800.0
    precip_seed: int = 42
    runoff_coeff: float = 0.15
    losses_mm_day: float = 1.5
    losses_months: list[int] = Field(default_factory=lambda: [4, 5, 6, 7, 8, 9])

    obs_x_m: list[float] = Field(default_factory=list)
    obs_t_stride: int = 2
    obs_noise_std_m: float = 0.03
    obs_seed: int = 123

    picard_max_iter: int = 40
    picard_tol: float = 1.0e-7
    picard_relaxation: float = 1.0
    head_floor_m: float = 1.0e-6

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

