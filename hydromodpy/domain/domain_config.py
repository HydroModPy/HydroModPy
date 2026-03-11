from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.domain.depth_model import ConstantThicknessDepthModel, DepthModelConfig
from hydromodpy.domain.spatial_support_config import DomainSupportConfig


class DomainConfig(BaseModel):
    """
    Domain configuration.

    Controls which zone providers are loaded in `Domain`.
    """

    model_config = ConfigDict(extra="forbid")

    support_mode: Annotated[
        Literal["none", "geology", "zones"] | None,
        ParamLevel("user"),
    ] = Field(
        default=None,
        description=(
            "Spatial-support strategy used by heterogeneous parameter mapping. "
            "'none' means no external support is needed, "
            "'geology' uses [data.geology], "
            "'zones' uses non-geology fields already attached to Domain.zones "
            "(for example catchment or custom zonations). "
            "When omitted, the mode is derived from domain.zone_ids for backward compatibility."
        ),
    )
    zone_ids: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered list of zone identifiers loaded in the domain registry. "
            "Keep this list for actual runtime zones (for example 'catchment', "
            "'geology', or custom zonations). Spatial-support selection is "
            "controlled by domain.support_mode."
        ),
    )
    supports: Annotated[dict[str, DomainSupportConfig], ParamLevel("user")] = Field(
        default_factory=dict,
        description=(
            "Named spatial supports available to heterogeneous parameters. "
            "Each key is a support identifier referenced by field_spatial_id."
        ),
    )
    depth_model: Annotated[DepthModelConfig, ParamLevel("user")] = Field(
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

    @model_validator(mode="after")
    def _resolve_support_mode(self) -> "DomainConfig":
        """Derive one stable spatial-support mode from the declared domain payload."""
        if self.support_mode == "none" and self.supports:
            raise ValueError("domain.support_mode='none' is incompatible with domain.supports")

        if self.support_mode == "geology":
            non_geology_supports = [
                support_id
                for support_id, support_cfg in self.supports.items()
                if getattr(support_cfg, "provider", None) != "geology"
            ]
            if non_geology_supports:
                raise ValueError(
                    "domain.support_mode='geology' cannot declare non-geology supports: "
                    + ", ".join(non_geology_supports)
                )
        elif self.support_mode == "zones":
            geology_supports = [
                support_id
                for support_id, support_cfg in self.supports.items()
                if getattr(support_cfg, "provider", None) == "geology"
            ]
            if geology_supports:
                raise ValueError(
                    "domain.support_mode='zones' cannot declare geology supports: "
                    + ", ".join(geology_supports)
                )

        if self.support_mode is not None:
            return self

        if self.supports:
            provider_names = {
                str(getattr(support_cfg, "provider", "")).strip().lower()
                for support_cfg in self.supports.values()
            }
            if provider_names == {"geology"}:
                self.support_mode = "geology"
            else:
                self.support_mode = "zones"
            return self

        zone_ids = set(self.zone_ids)
        if "geology" in zone_ids:
            self.support_mode = "geology"
        elif any(zone_id != "catchment" for zone_id in zone_ids):
            self.support_mode = "zones"
        else:
            self.support_mode = "none"
        return self
