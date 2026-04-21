from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hydromodpy.core.config.profile import Profile
from hydromodpy.spatial.domain.depth_model_config import ConstantThicknessDepthModel, DepthModelConfig
from hydromodpy.spatial.domain.spatial_support_config import DomainSupportConfig
from hydromodpy.core.config.base import HydroModelBase


class DomainConfig(HydroModelBase):
    """
    Domain configuration.

    Controls which zone providers are loaded in `Domain`.
    """

    model_config = ConfigDict(extra="forbid")

    zone_ids: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered list of zone identifiers loaded in the domain registry. "
            "Keep this list for actual runtime zones (for example 'catchment', "
            "'geology', or custom zonations). Spatial-support declarations live "
            "under domain.supports."
        ),
    )
    supports: Annotated[dict[str, DomainSupportConfig], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Named spatial supports available to heterogeneous parameters. "
            "Each key is a support identifier referenced by field_spatial_id."
        ),
    )
    depth_model: Annotated[DepthModelConfig, Profile.USER] = Field(
        default_factory=ConstantThicknessDepthModel,
        description=(
            "Vertical domain model configuration. "
            "Use 'constant_thickness' or 'flat_substratum'."
        ),
    )

    @field_validator("zone_ids", mode="before")
    @classmethod
    def _validate_zone_ids(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("domain.zone_ids must be a list of strings")
        return value

    @field_validator("zone_ids")
    @classmethod
    def _normalize_zone_ids(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw_item in value:
            zone_id = str(raw_item).strip().lower()
            if zone_id == "":
                raise ValueError("domain.zone_ids cannot contain empty values")
            if zone_id in seen:
                continue
            seen.add(zone_id)
            out.append(zone_id)
        return out

    @field_validator("supports", mode="before")
    @classmethod
    def _validate_supports_input(cls, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("domain.supports must be a mapping")
        return value

    @field_validator("supports")
    @classmethod
    def _normalize_support_keys(cls, value: dict[str, DomainSupportConfig]) -> dict[str, DomainSupportConfig]:
        out: dict[str, DomainSupportConfig] = {}
        seen: set[str] = set()
        for raw_key, support_cfg in value.items():
            support_id = str(raw_key).strip()
            if support_id == "":
                raise ValueError("domain.supports cannot contain empty ids")
            normalized_key = support_id.lower()
            if normalized_key in seen:
                raise ValueError(f"Duplicate domain support id '{support_id}'")
            seen.add(normalized_key)
            out[support_id] = support_cfg
        return out
