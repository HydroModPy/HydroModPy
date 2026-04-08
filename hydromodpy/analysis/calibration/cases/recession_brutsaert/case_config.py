"""
Brutsaert case-specific Pydantic schemas for chronicle inputs.

This module isolates case-level validation from simulation/calibration logic.
The workflow is:
1) parse raw `[chronicle]` dict with `model_validate(...)`,
2) apply field validators for physical constraints,
3) return a plain normalized dict with `model_dump(...)`.
"""

from __future__ import annotations

from typing import Annotated, Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hydromodpy.core.config.param_level import ParamLevel


class BrutsaertChronicleSchema(BaseModel):
    """
    Schema for `[chronicle]` in the Brutsaert calibration workflow.

    `extra="forbid"` is used to catch unknown keys early.
    """

    # Reject undeclared keys to avoid silent TOML typos.
    model_config = ConfigDict(extra="forbid")

    Q0: Annotated[float, ParamLevel("dev")] = Field(
        description="Initial discharge."
    )
    K: Annotated[float, ParamLevel("dev")] = Field(
        description="Hydraulic conductivity."
    )
    Sy: Annotated[float, ParamLevel("dev")] = Field(
        description="Specific yield."
    )
    solution: Annotated[str, ParamLevel("dev")] = Field(
        default="boussinesq", description="Analytical solution type."
    )
    A: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="Aquifer cross-sectional area."
    )
    L: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="Aquifer length."
    )
    b: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="Aquifer thickness."
    )
    ag: Annotated[float, ParamLevel("dev")] = Field(
        default=0.7, description="Gravity constant or slope parameter."
    )
    p: Annotated[float, ParamLevel("dev")] = Field(
        default=0.346, description="Brutsaert recession exponent."
    )
    n_points: Annotated[int, ParamLevel("dev")] = Field(
        default=50, description="Number of data points to generate."
    )
    log_spacing: Annotated[bool, ParamLevel("dev")] = Field(
        default=True, description="Use logarithmic spacing for time points."
    )
    t_min_days: Annotated[float, ParamLevel("dev")] = Field(
        default=0.1, description="Minimum time in days."
    )
    error_fraction: Annotated[float, ParamLevel("dev")] = Field(
        default=0.15, description="Fractional error for synthetic noise."
    )
    random_seed: Annotated[int | None, ParamLevel("dev")] = Field(
        default=12345, description="Random seed for reproducibility."
    )

    @field_validator("Q0", "K", "Sy", "t_min_days")
    @classmethod
    def _validate_positive(cls, value):
        out = float(value)
        if out <= 0.0:
            raise ValueError("value must be > 0")
        return out

    @field_validator("A", "L", "b")
    @classmethod
    def _validate_optional_positive(cls, value):
        if value is None:
            return None
        out = float(value)
        if out <= 0.0:
            raise ValueError("value must be > 0")
        return out

    @field_validator("ag")
    @classmethod
    def _validate_ag(cls, value):
        out = float(value)
        if out < 0.0 or out > 1.0:
            raise ValueError("ag must be in [0, 1]")
        return out

    @field_validator("n_points")
    @classmethod
    def _validate_n_points(cls, value):
        if int(value) <= 0:
            raise ValueError("n_points must be > 0")
        return int(value)

    @field_validator("error_fraction")
    @classmethod
    def _validate_non_negative(cls, value):
        out = float(value)
        if out < 0.0:
            raise ValueError("error_fraction must be >= 0")
        return out


def validate_brutsaert_chronicle_config(chronicle_cfg: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate and normalize Brutsaert chronicle config.

    Returns a plain dictionary so downstream code does not depend on Pydantic.
    """
    try:
        # Main pydantic entry point: parse + validate according to schema.
        parsed = BrutsaertChronicleSchema.model_validate(dict(chronicle_cfg))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    # Convert validated model back to standard Python values.
    return parsed.model_dump(mode="python")
