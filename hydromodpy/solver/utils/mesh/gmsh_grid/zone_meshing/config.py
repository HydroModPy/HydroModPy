"""Validate and normalize configuration for zone-conformal meshing workflows.

This module stays small on purpose: its role is to define what a valid
zone-meshing configuration looks like before geometry and Gmsh calls are
performed. It separates configuration concerns from the actual meshing logic.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)


class ZoneMeshingSettingsSchema(BaseModel):
    """Validated settings for one conformal 2D Gmsh meshing run."""

    model_config = ConfigDict(extra="forbid")

    algorithm: str = "delaunay"
    global_size: float = 250.0
    min_size: float | None = None
    max_size: float | None = None
    simplify_tolerance: float = 0.0
    heal_tolerance: float = 0.0
    min_polygon_area: float = 0.0
    refine_interfaces: bool = False
    interface_size: float | None = None
    interface_distance: float | None = None
    interface_sampling: int = 64

    @field_validator("algorithm")
    @classmethod
    def _validate_algorithm(cls, value):
        text = str(value).strip().lower()
        if not text:
            raise ValueError("algorithm cannot be empty")
        return text

    @field_validator(
        "global_size",
        "min_size",
        "max_size",
        "simplify_tolerance",
        "heal_tolerance",
        "min_polygon_area",
        "interface_size",
        "interface_distance",
    )
    @classmethod
    def _validate_optional_non_negative_float(cls, value):
        if value is None:
            return None
        out = float(value)
        if out < 0.0:
            raise ValueError("values must be >= 0")
        return out

    @field_validator("interface_sampling")
    @classmethod
    def _validate_interface_sampling(cls, value):
        out = int(value)
        if out < 2:
            raise ValueError("interface_sampling must be >= 2")
        return out

    @model_validator(mode="after")
    def _validate_cross_constraints(self):
        if self.global_size <= 0.0:
            raise ValueError("global_size must be > 0")
        if self.min_size is not None and self.min_size <= 0.0:
            raise ValueError("min_size must be > 0 when provided")
        if self.max_size is not None and self.max_size <= 0.0:
            raise ValueError("max_size must be > 0 when provided")
        if (
            self.min_size is not None
            and self.max_size is not None
            and self.min_size > self.max_size
        ):
            raise ValueError("min_size must be <= max_size")

        if self.refine_interfaces:
            if self.interface_size is None:
                self.interface_size = min(
                    (
                        self.min_size
                        if self.min_size is not None
                        else self.global_size * 0.5
                    ),
                    self.global_size,
                )
            if self.interface_distance is None:
                self.interface_distance = max(
                    self.global_size * 3.0, self.interface_size
                )
            if self.interface_size <= 0.0:
                raise ValueError(
                    "interface_size must be > 0 when refine_interfaces=true"
                )
            if self.interface_size > self.global_size:
                raise ValueError(
                    "interface_size must be <= global_size when refine_interfaces=true"
                )
            if self.interface_distance <= 0.0:
                raise ValueError(
                    "interface_distance must be > 0 when refine_interfaces=true"
                )
        return self


def validate_zone_meshing_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate raw meshing settings and return normalized Python values."""

    if not isinstance(config_data, Mapping):
        raise ValueError("zone meshing configuration must be a mapping")
    try:
        parsed = ZoneMeshingSettingsSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")
