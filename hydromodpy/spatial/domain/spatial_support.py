from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol

import numpy as np

from hydromodpy.core.exceptions import ConfigMissingError
from hydromodpy.spatial.domain.spatial_support_config import (
    CatchmentZonesSupportConfig,
    DomainSupportConfig,
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
    GeologySupportConfig,
)
from hydromodpy.spatial.domain.support_fields import (
    AliasedSpatialSupportField,
    GeneratedBandsSupportField,
    GeneratedRingsSupportField,
    RasterZonesSupportField,
)
from hydromodpy.spatial.raster_support import RasterSupport


@dataclass(slots=True)
class SupportBuildContext:
    """Runtime objects available when building domain spatial supports."""

    cfg: object
    raw_toml: dict[str, object]
    workspace: object | None
    geographic: object | None
    domain_geographic: object | None
    domain: object
    flow: object | None
    loaded_data: object | None
    time_grid: object | None
    geographic_features: object | None = None


class SpatialSupportProvider(Protocol):
    """Builder contract used by the launcher to materialize support fields."""

    provider_name: ClassVar[str]
    build_phase: ClassVar[Literal["setup", "data"]]

    def build(
        self,
        *,
        support_id: str,
        config: DomainSupportConfig,
        context: SupportBuildContext,
    ) -> object: ...


class GeneratedBandsSupportProvider:
    provider_name = "generated_bands"
    build_phase = "setup"

    def build(
        self,
        *,
        support_id: str,
        config: GeneratedBandsSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        surface_topo = getattr(context.domain, "surface_topo", None)
        support = getattr(surface_topo, "support", None)
        if not isinstance(support, RasterSupport):
            raise ValueError("Generated bands support requires domain.surface_topo.support")
        support.assert_complete_domain()

        if config.axis == "x":
            lower = float(support.xmin)
            upper = float(support.xmax)
        else:
            lower = float(support.ymin)
            upper = float(support.ymax)
        span = upper - lower
        if span <= 0.0:
            raise ValueError("Domain support extent must be strictly positive")

        if config.coordinate_mode == "relative":
            breaks_abs = [lower + float(value) * span for value in config.breaks]
        else:
            breaks_abs = [float(value) for value in config.breaks]

        if any(value <= lower or value >= upper for value in breaks_abs):
            axis_label = "x" if config.axis == "x" else "y"
            raise ValueError(
                f"Generated bands breaks must lie strictly inside the domain {axis_label} extent "
                f"({lower}, {upper})."
            )

        return GeneratedBandsSupportField(
            identifier=support_id,
            axis=config.axis,
            breaks_abs=breaks_abs,
            labels=list(config.labels),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class GeneratedRingsSupportProvider:
    provider_name = "generated_rings"
    build_phase = "setup"

    def build(
        self,
        *,
        support_id: str,
        config: GeneratedRingsSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        surface_topo = getattr(context.domain, "surface_topo", None)
        support = getattr(surface_topo, "support", None)
        if not isinstance(support, RasterSupport):
            raise ValueError("Generated rings support requires domain.surface_topo.support")
        support.assert_complete_domain()

        center_x = (
            float(config.center_x)
            if config.center_x is not None
            else 0.5 * (float(support.xmin) + float(support.xmax))
        )
        center_y = (
            float(config.center_y)
            if config.center_y is not None
            else 0.5 * (float(support.ymin) + float(support.ymax))
        )
        max_radius = min(
            center_x - float(support.xmin),
            float(support.xmax) - center_x,
            center_y - float(support.ymin),
            float(support.ymax) - center_y,
        )
        if max_radius <= 0.0:
            raise ValueError("Generated rings center must lie strictly inside the domain extent.")

        if config.coordinate_mode == "relative":
            radii_abs = [float(value) * max_radius for value in config.radii]
        else:
            radii_abs = [float(value) for value in config.radii]

        if any(value >= max_radius for value in radii_abs):
            raise ValueError(
                "Generated rings radii must lie strictly inside the largest "
                "inscribed circle around the chosen center."
            )

        return GeneratedRingsSupportField(
            identifier=support_id,
            center_x=center_x,
            center_y=center_y,
            radii_abs=radii_abs,
            labels=list(config.labels),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class CatchmentZonesSupportProvider:
    provider_name = "catchment_zones"
    build_phase = "setup"

    def build(
        self,
        *,
        support_id: str,
        config: CatchmentZonesSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        domain = context.domain
        source_zone = domain.get_zone(config.source_zone_id)
        if source_zone is None:
            raise ValueError(
                f"Catchment support '{support_id}' requires domain zone '{config.source_zone_id}'."
            )

        if not hasattr(source_zone, "encoded_codes") or not hasattr(source_zone, "encoded_to_zone"):
            raise TypeError("Catchment source zone must expose encoded_codes and encoded_to_zone.")
        surface_topo = getattr(domain, "surface_topo", None)
        raster_support = getattr(surface_topo, "support", None)
        if not isinstance(raster_support, RasterSupport):
            raise ValueError("Catchment support requires domain.surface_topo.support")

        return RasterZonesSupportField(
            identifier=support_id,
            encoded_codes=np.asarray(source_zone.encoded_codes, dtype=np.int32),
            encoded_to_zone=dict(source_zone.encoded_to_zone),
            raster_support=raster_support,
            nodata_code=int(getattr(source_zone, "nodata_code", 0)),
            source_meta=getattr(source_zone, "source_meta", None),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class GeologySupportProvider:
    provider_name = "geology"
    build_phase = "data"

    def build(
        self,
        *,
        support_id: str,
        config: GeologySupportConfig,
        context: SupportBuildContext,
    ) -> object:
        loaded_data = context.loaded_data
        geology = getattr(loaded_data, "geology", None) if loaded_data is not None else None
        if geology is None:
            # A geology the planner inferred for this support loads in warn mode,
            # so a failed load reaches here as a warning, not as an error.
            raise ConfigMissingError(
                f"[domain.supports.{support_id}] kind = 'geology' reads the geology data, and "
                "none was loaded. Declare [data.geology] with a source that covers the "
                "domain, and list 'geology' in data.types so a failed load stops the run."
            )
        if str(getattr(geology, "identifier", "")).strip() == str(support_id).strip():
            return geology
        return AliasedSpatialSupportField(identifier=support_id, delegate=geology)


class SpatialSupportProviderRegistry:
    """Registry of named support providers used by the launcher."""

    def __init__(self) -> None:
        self._providers: dict[str, SpatialSupportProvider] = {}

    def register(self, provider: SpatialSupportProvider) -> None:
        self._providers[str(provider.provider_name).strip().lower()] = provider

    def get(self, provider_name: str) -> SpatialSupportProvider:
        normalized = str(provider_name).strip().lower()
        provider = self._providers.get(normalized)
        if provider is None:
            raise ValueError(f"Unknown spatial support provider '{provider_name}'")
        return provider


def build_default_spatial_support_provider_registry() -> SpatialSupportProviderRegistry:
    """Return the launcher registry populated with the built-in support providers."""
    registry = SpatialSupportProviderRegistry()
    registry.register(GeneratedBandsSupportProvider())
    registry.register(GeneratedRingsSupportProvider())
    registry.register(CatchmentZonesSupportProvider())
    registry.register(GeologySupportProvider())
    return registry
