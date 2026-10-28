from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.spatial.domain.depth_model_config import (
    ConstantThicknessDepthModel,
    DepthModelConfig,
)
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.domain.spatial_support_config import DomainSupportConfig


class DomainConfig(HydroModelBase):
    """Domain configuration: the zones, the depth of the aquifer and its layering.

    Controls which zone providers are loaded in `Domain`. ``layers`` is the
    vertical split of the aquifer, read by every solver.
    """

    zone_ids: Annotated[list[IdentifierStr], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Zone identifiers Domain.set_zone is allowed to register. It is an "
            "allowlist, not a request: nothing here causes a zone to be built. "
            "'catchment' and 'geology' are appended by HydroModPy because the "
            "binders write under those fixed names, and every support id is "
            "appended too, so what belongs here is a project's own zonations. "
            "Order is never read. Spatial-support declarations live under "
            "domain.supports."
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
            "Vertical domain model configuration. Use 'constant_thickness', "
            "'flat_substratum', or 'raster' with a [data.substratum] raster."
        ),
    )
    layers: Annotated[VerticalGridConfig, Profile.USER] = Field(
        default_factory=VerticalGridConfig,
        description=(
            "How the aquifer between the top and the base set by depth_model is split "
            "into layers. Every solver reads this one table."
        ),
    )

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
        """Keep the first of a zone id written twice, in the order written."""
        return list(dict.fromkeys(value))
