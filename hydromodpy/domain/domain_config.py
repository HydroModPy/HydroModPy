from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.watershed.geology_config import GeologyConfig


class DomainConfig(BaseModel):
    """
    Domain configuration.

    Controls which zone providers are loaded in `Domain`.
    """

    zone_ids: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered list of zone identifiers loaded in the domain. "
            "Supported values currently include: 'geology'."
        ),
    )
    geology: Annotated[GeologyConfig, ParamLevel("user")] = Field(
        default_factory=GeologyConfig,
        description=(
            "Geology configuration used internally by Domain to build "
            "the 'geology' zone field."
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
