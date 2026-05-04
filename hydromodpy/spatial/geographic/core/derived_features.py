"""Structured geographic-derived features shared across runtime layers.

This module introduces a higher-level container for geographic artifacts that
are neither raw data-managers nor domain zones:

- topographic surface derived from the prepared DEM,
- boundary/support polygons used by the domain and meshing workflows,
- optional river-network products derived from the DEM workflow.

`DomainGeographicContext` remains available as a narrower compatibility view,
but the long-term orchestration contract should prefer `GeographicDerivedFeatures`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HydrographicNetwork,
    HydrographicNetworks,
)
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts
from hydromodpy.spatial.surface import Surface


@dataclass(frozen=True)
class GeographicBoundaryFeatures:
    """Boundary/support polygons derived during geographic preprocessing."""

    watershed_shp: str
    watershed_box_shp: str | None
    box_buff_shp: str


@dataclass(frozen=True)
class GeographicDerivedFeatures:
    """Canonical bundle of geographic artifacts derived from preprocessing."""

    surface_topo: Surface
    boundaries: GeographicBoundaryFeatures
    rivers: RiverNetworkProducts = field(
        default_factory=lambda: RiverNetworkProducts(enabled=False)
    )
    catchment_area_km2: float = 0.0
    catch_def: str = ""
    x_outlet: float | None = None
    y_outlet: float | None = None
    zone_kind: str = "catchment"
    watershed_box_buff_dem: str = ""
    regional_dem_path: str | None = None
    hydrographic_networks: HydrographicNetworks = field(default_factory=HydrographicNetworks)

    def to_domain_geographic_context(self):
        """Return the historical compatibility view used by domain consumers."""
        from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import (
            DomainGeographicContext,
        )

        return DomainGeographicContext(
            surface_topo=self.surface_topo,
            watershed_shp=str(self.boundaries.watershed_shp),
            catchment_area_km2=float(self.catchment_area_km2),
            catch_def=str(self.catch_def),
            x_outlet=None if self.x_outlet is None else float(self.x_outlet),
            y_outlet=None if self.y_outlet is None else float(self.y_outlet),
            watershed_box_buff_dem=str(self.watershed_box_buff_dem),
            watershed_box_shp=(
                None
                if self.boundaries.watershed_box_shp is None
                else str(self.boundaries.watershed_box_shp)
            ),
            box_buff_shp=str(self.boundaries.box_buff_shp),
            zone_kind=str(self.zone_kind),
            # Compatibility alias: the canonical owner is now `features.rivers`.
            river_mesh_trace=self.rivers.river_mesh_trace,
            regional_dem_path=(
                None if self.regional_dem_path is None else str(self.regional_dem_path)
            ),
        )

    @property
    def generated_hydrographic_network(self) -> HydrographicNetwork | None:
        """Return the canonical generated hydrographic network when available."""
        return self.hydrographic_networks.generated

    @property
    def reference_hydrographic_network(self) -> HydrographicNetwork | None:
        """Return the canonical reference hydrographic network when available."""
        return self.hydrographic_networks.reference

    @classmethod
    def from_domain_geographic_context(
        cls,
        context: object,
    ) -> GeographicDerivedFeatures:
        """Lift one historical domain-geographic payload into the new bundle."""
        river_mesh_trace = getattr(context, "river_mesh_trace", None)
        return cls(
            surface_topo=context.surface_topo,
            boundaries=GeographicBoundaryFeatures(
                watershed_shp=str(getattr(context, "watershed_shp", "")),
                watershed_box_shp=(
                    None
                    if getattr(context, "watershed_box_shp", None) in (None, "")
                    else str(context.watershed_box_shp)
                ),
                box_buff_shp=str(getattr(context, "box_buff_shp", "")),
            ),
            rivers=RiverNetworkProducts(
                enabled=bool(river_mesh_trace is not None),
                river_mesh_trace=river_mesh_trace,
            ),
            catchment_area_km2=float(getattr(context, "catchment_area_km2", 0.0) or 0.0),
            catch_def=str(getattr(context, "catch_def", "")),
            x_outlet=getattr(context, "x_outlet", None),
            y_outlet=getattr(context, "y_outlet", None),
            zone_kind=str(getattr(context, "zone_kind", "")),
            watershed_box_buff_dem=str(getattr(context, "watershed_box_buff_dem", "")),
            regional_dem_path=(
                None
                if getattr(context, "regional_dem_path", None) in (None, "")
                else str(context.regional_dem_path)
            ),
            hydrographic_networks=HydrographicNetworks(),
        )


def coerce_geographic_derived_features(
    *,
    geographic_features: object | None = None,
    geographic: object | None = None,
    domain_geographic: object | None = None,
) -> GeographicDerivedFeatures | None:
    """Resolve `GeographicDerivedFeatures` from runtime objects when possible."""
    if isinstance(geographic_features, GeographicDerivedFeatures):
        return geographic_features
    if geographic_features is not None:
        if getattr(geographic_features, "rivers", None) is not None and callable(
            getattr(geographic_features, "to_domain_geographic_context", None)
        ):
            return geographic_features
    if geographic is not None:
        getter = getattr(geographic, "get_geographic_derived_features", None)
        if callable(getter):
            features = getter()
            if features is not None:
                return features
        domain_getter = getattr(geographic, "get_domain_geographic_context", None)
        if callable(domain_getter):
            return GeographicDerivedFeatures.from_domain_geographic_context(domain_getter())
    if domain_geographic is not None:
        try:
            return GeographicDerivedFeatures.from_domain_geographic_context(domain_geographic)
        except AttributeError:
            return None
    return None


def attach_reference_hydrographic_network(
    geographic_features: GeographicDerivedFeatures,
    hydrography_load_result: object | None,
) -> GeographicDerivedFeatures:
    """Return one updated features bundle enriched with the reference network.

    The geographic preprocessing stack creates the generated network early,
    while the imported hydrography becomes available only after data loading.
    This helper keeps that late binding explicit and localized.
    """
    if hydrography_load_result is None:
        return geographic_features

    reference = HydrographicNetwork.from_hydrography_load_result(
        hydrography_load_result,
        watershed_shp=geographic_features.boundaries.watershed_shp,
    )
    networks = geographic_features.hydrographic_networks
    return replace(
        geographic_features,
        hydrographic_networks=replace(networks, reference=reference),
    )


def resolve_river_mesh_trace(
    *,
    geographic_features: GeographicDerivedFeatures | None = None,
    domain_geographic: object | None = None,
) -> object | None:
    """Return the canonical in-memory river mesh trace when available."""
    if geographic_features is not None and geographic_features.rivers is not None:
        river_trace = geographic_features.rivers.river_mesh_trace
        if river_trace is not None:
            return river_trace
    if domain_geographic is None:
        return None
    return getattr(domain_geographic, "river_mesh_trace", None)


__all__ = [
    "GeographicBoundaryFeatures",
    "GeographicDerivedFeatures",
    "attach_reference_hydrographic_network",
    "coerce_geographic_derived_features",
    "resolve_river_mesh_trace",
]
