"""Brutsaert case-specific pydantic schemas for chronicle inputs."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class BrutsaertChronicleSchema(BaseModel):
    """Schema for `[chronicle]` in Brutsaert calibration workflow."""

    model_config = ConfigDict(extra="forbid")

    Q0: float
    K: float
    Sy: float
    solution: str = "boussinesq"
    A: float | None = None
    L: float | None = None
    b: float | None = None
    ag: float = 0.7
    p: float = 0.346
    n_points: int = 50
    log_spacing: bool = True
    t_min_days: float = 0.1
    error_fraction: float = 0.15
    random_seed: int | None = 12345

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
    """Validate and normalize Brutsaert chronicle config."""
    try:
        parsed = BrutsaertChronicleSchema.model_validate(dict(chronicle_cfg))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")
