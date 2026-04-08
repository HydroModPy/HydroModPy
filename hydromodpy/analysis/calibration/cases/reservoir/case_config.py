"""
Reservoir case-specific Pydantic schemas for chronicle inputs.

This module keeps case-level input validation close to the reservoir case.
It uses Pydantic to validate types/ranges and returns normalized plain
dictionaries for the rest of the workflow.
"""

from __future__ import annotations

from typing import Annotated, Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hydromodpy.core.config.param_level import ParamLevel


class ReservoirChronicleSchema(BaseModel):
    """
    Schema for `[chronicle]` in reservoir calibration workflow.

    The schema includes fields for both model variants (one- and two-reservoir);
    each workflow then reads only the subset it needs.
    """

    # Strict mode: any unknown chronicle key is reported as a validation error.
    model_config = ConfigDict(extra="forbid")

    n_days: Annotated[int, ParamLevel("dev")] = Field(
        default=365, description="Number of simulation days."
    )
    start_year: Annotated[int, ParamLevel("dev")] = Field(
        default=2000, description="Start year for forcing generation."
    )
    target_annual_precip_mm: Annotated[float, ParamLevel("dev")] = Field(
        default=800.0, description="Target annual precipitation in mm."
    )
    precip_seed: Annotated[int, ParamLevel("dev")] = Field(
        default=42, description="Random seed for precipitation."
    )
    runoff_coeff: Annotated[float, ParamLevel("dev")] = Field(
        default=0.15, description="Runoff coefficient."
    )
    losses_mm_day: Annotated[float, ParamLevel("dev")] = Field(
        default=1.5, description="Daily evapotranspiration losses in mm/day."
    )
    losses_months: Annotated[list[int], ParamLevel("dev")] = Field(
        default_factory=lambda: [4, 5, 6, 7, 8, 9],
        description="Months where losses are applied.",
    )
    error_fraction: Annotated[float, ParamLevel("dev")] = Field(
        default=0.05, description="Fractional noise added to observations."
    )
    error_seed: Annotated[int, ParamLevel("dev")] = Field(
        default=12345, description="Random seed for observation noise."
    )
    solver_backend: Annotated[str, ParamLevel("dev")] = Field(
        default="analytic", description="Numerical solver backend."
    )
    capacity_mm_true: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="True reservoir capacity in mm."
    )
    k_per_day_true: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="True reservoir drainage coefficient in 1/day."
    )
    s0_mm: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0, description="Initial reservoir storage in mm."
    )
    a_true: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="True parameter a for dual-reservoir."
    )
    kq_days_true: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="True quick-flow time constant in days."
    )
    ks_days_true: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="True slow-flow time constant in days."
    )
    sq0_mm: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0, description="Initial quick storage in mm."
    )
    ss0_mm: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0, description="Initial slow storage in mm."
    )

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

    @field_validator("solver_backend")
    @classmethod
    def _validate_solver_backend(cls, value):
        backend = str(value).strip().lower()
        if backend not in {"analytic", "ode"}:
            raise ValueError("solver_backend must be 'analytic' or 'ode'")
        return backend

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
    """
    Validate and normalize reservoir chronicle config.

    Returns a plain dictionary so simulation code can stay independent from
    Pydantic internals.
    """
    try:
        # Parse/coerce inputs and run schema validators.
        parsed = ReservoirChronicleSchema.model_validate(dict(chronicle_cfg))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    # Export validated values as regular Python objects.
    return parsed.model_dump(mode="python")
