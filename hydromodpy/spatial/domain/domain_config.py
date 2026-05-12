from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.spatial.domain.depth_model_config import (
    ConstantThicknessDepthModel,
    DepthModelConfig,
)
from hydromodpy.spatial.domain.spatial_support_config import DomainSupportConfig


class DomainConfig(HydroModelBase):
    """
    Domain configuration.

    Controls which zone providers are loaded in `Domain`.
    """

    zone_ids: Annotated[list[IdentifierStr], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered list of zone identifiers loaded in the domain registry. "
            "Keep this list for actual runtime zones (for example 'catchment', "
            "'geology', or custom zonations). Spatial-support declarations live "
            "under domain.supports."
        ),
    )
    supports: Annotated[dict[IdentifierStr, DomainSupportConfig], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Named spatial supports available to heterogeneous parameters. "
            "Each key is a support identifier referenced by field_spatial_id."
        ),
    )
    depth_model: Annotated[DepthModelConfig, Profile.USER] = Field(
        default_factory=ConstantThicknessDepthModel,
        description=(
            "Vertical domain model configuration. Use 'constant_thickness' or 'flat_substratum'."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_domain_keys(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)

        raw_supports = payload.get("supports")
        if isinstance(raw_supports, Mapping):
            supports: dict[str, Any] = {}
            for support_id, raw_support in raw_supports.items():
                if isinstance(raw_support, Mapping):
                    support_payload = dict(raw_support)
                    if "kind" not in support_payload and "provider" in support_payload:
                        support_payload["kind"] = support_payload.pop("provider")
                    supports[str(support_id)] = support_payload
                else:
                    supports[str(support_id)] = raw_support
            payload["supports"] = supports

        raw_depth_model = payload.get("depth_model")
        if isinstance(raw_depth_model, Mapping):
            depth_model = dict(raw_depth_model)
            if "kind" not in depth_model and "type" in depth_model:
                depth_model["kind"] = depth_model.pop("type")
            payload["depth_model"] = depth_model

        return payload

    @classmethod
    def with_thickness(
        cls,
        thickness: float,
        *,
        zone_ids: list[str] | None = None,
        **overrides,
    ) -> DomainConfig:
        """DomainConfig with a constant aquifer thickness below topography."""
        return cls(
            depth_model=ConstantThicknessDepthModel(thickness=float(thickness)),
            zone_ids=zone_ids or [],
            **overrides,
        )

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

    @field_validator("supports")
    @classmethod
    def _normalize_support_keys(
        cls, value: dict[str, DomainSupportConfig]
    ) -> dict[str, DomainSupportConfig]:
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
