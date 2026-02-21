"""Reservoir case-specific pydantic schemas for chronicle inputs."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ReservoirChronicleSchema(BaseModel):
    """Schema for `[chronicle]` in reservoir calibration workflow."""

    model_config = ConfigDict(extra="forbid")

    n_days: int = 365
    start_year: int = 2000
    target_annual_precip_mm: float = 800.0
    precip_seed: int = 42
    runoff_coeff: float = 0.15
    losses_mm_day: float = 1.5
    losses_months: list[int] = Field(default_factory=lambda: [4, 5, 6, 7, 8, 9])
    error_fraction: float = 0.05
    error_seed: int = 12345
    capacity_mm_true: float | None = None
    k_per_day_true: float | None = None
    s0_mm: float = 0.0
    a_true: float | None = None
    kq_days_true: float | None = None
    ks_days_true: float | None = None
    sq0_mm: float = 0.0
    ss0_mm: float = 0.0

    @field_validator("n_days")
    @classmethod
    def _validate_n_days(cls, value):
        if int(value) <= 0:
            raise ValueError("n_days must be > 0")
        return int(value)

    @field_validator("target_annual_precip_mm")
    @classmethod
    def _validate_target_annual_precip_mm(cls, value):
        if float(value) <= 0.0:
            raise ValueError("target_annual_precip_mm must be > 0")
        return float(value)

    @field_validator("runoff_coeff")
    @classmethod
    def _validate_runoff_coeff(cls, value):
        out = float(value)
        if out < 0.0 or out > 1.0:
            raise ValueError("runoff_coeff must be in [0, 1]")
        return out

    @field_validator("losses_mm_day", "error_fraction")
    @classmethod
    def _validate_non_negative(cls, value):
        out = float(value)
        if out < 0.0:
            raise ValueError("value must be >= 0")
        return out

    @field_validator("capacity_mm_true", "k_per_day_true", "kq_days_true", "ks_days_true")
    @classmethod
    def _validate_optional_positive(cls, value):
        if value is None:
            return None
        out = float(value)
        if out <= 0.0:
            raise ValueError("value must be > 0")
        return out

    @field_validator("s0_mm", "sq0_mm", "ss0_mm")
    @classmethod
    def _validate_optional_non_negative_state(cls, value):
        out = float(value)
        if out < 0.0:
            raise ValueError("state values must be >= 0")
        return out

    @field_validator("a_true")
    @classmethod
    def _validate_optional_a_true(cls, value):
        if value is None:
            return None
        out = float(value)
        if out < 0.0 or out > 1.0:
            raise ValueError("a_true must be in [0, 1]")
        return out

    @field_validator("losses_months")
    @classmethod
    def _validate_losses_months(cls, values):
        out = [int(v) for v in values]
        if len(out) == 0:
            raise ValueError("losses_months cannot be empty")
        if any(v < 1 or v > 12 for v in out):
            raise ValueError("losses_months values must be between 1 and 12")
        return out


def validate_reservoir_chronicle_config(chronicle_cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize reservoir chronicle config."""
    try:
        parsed = ReservoirChronicleSchema.model_validate(dict(chronicle_cfg))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")
