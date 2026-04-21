"""Geographic compatibility package.

The decomposed geographic workflow now lives in ``hydromodpy.spatial.geographic.core``.
This package exposes the historical runtime facade and its compatibility
helpers.
"""

from __future__ import annotations

import importlib

from hydromodpy.spatial.geographic.catchment_delineation import (
    CatchmentDelineation,
    DEM_correcflow_analysis,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig, RiverNetworkConfig
from hydromodpy.spatial.geographic.dem_metadata import (
    LegacyDemMetadata,
    read_legacy_dem_metadata,
)
from hydromodpy.spatial.geographic.domain_rasters import (
    LegacyDomainRasterProducts,
    build_legacy_domain_rasters,
)
from hydromodpy.spatial.geographic.pipeline import (
    LegacyGeographicContext,
    build_legacy_geographic_context,
)
from hydromodpy.spatial.geographic.subbasin import Subbasin

_LAZY_V2_EXPORTS: dict[str, tuple[str, str]] = {
    # Keep compatibility from ``hydromodpy.spatial.geographic``.
    "CatchmentFromPointProducts": (
        "hydromodpy.spatial.geographic.core.catchment_from_point",
        "CatchmentFromPointProducts",
    ),
    "extract_catchment_from_point": (
        "hydromodpy.spatial.geographic.core.catchment_from_point",
        "extract_catchment_from_point",
    ),
    "CatchmentDomainProducts": (
        "hydromodpy.spatial.geographic.core.catchment_domain",
        "CatchmentDomainProducts",
    ),
    "derive_catchment_domain": (
        "hydromodpy.spatial.geographic.core.catchment_domain",
        "derive_catchment_domain",
    ),
    "extract_catchment_from_polygon": (
        "hydromodpy.spatial.geographic.core.catchment_from_polygon",
        "extract_catchment_from_polygon",
    ),
    "compute_catchment_area_km2": (
        "hydromodpy.spatial.geographic.core.catchment_metrics",
        "compute_catchment_area_km2",
    ),
    "CatchmentZoneCode": (
        "hydromodpy.spatial.geographic.core.catchment_zones",
        "CatchmentZoneCode",
    ),
    "CatchmentZoneProducts": (
        "hydromodpy.spatial.geographic.core.catchment_zones",
        "CatchmentZoneProducts",
    ),
    "build_catchment_zone_codes": (
        "hydromodpy.spatial.geographic.core.catchment_zones",
        "build_catchment_zone_codes",
    ),
    "clip_dem_to_box_buffer": (
        "hydromodpy.spatial.geographic.core.domain_dem",
        "clip_dem_to_box_buffer",
    ),
    "FlowProducts": (
        "hydromodpy.spatial.geographic.core.flow_products",
        "FlowProducts",
    ),
    "build_regional_flow_products": (
        "hydromodpy.spatial.geographic.core.flow_products",
        "build_regional_flow_products",
    ),
    "build_surface_topo_from_dem": (
        "hydromodpy.spatial.geographic.core.surface_from_dem",
        "build_surface_topo_from_dem",
    ),
    "GeographicBoundaryFeatures": (
        "hydromodpy.spatial.geographic.core.derived_features",
        "GeographicBoundaryFeatures",
    ),
    "GeographicDerivedFeatures": (
        "hydromodpy.spatial.geographic.core.derived_features",
        "GeographicDerivedFeatures",
    ),
    "coerce_geographic_derived_features": (
        "hydromodpy.spatial.geographic.core.derived_features",
        "coerce_geographic_derived_features",
    ),
    "resolve_river_mesh_trace": (
        "hydromodpy.spatial.geographic.core.derived_features",
        "resolve_river_mesh_trace",
    ),
    "DomainGeographicContext": (
        "hydromodpy.spatial.geographic.core.domain_geographic_pipeline",
        "DomainGeographicContext",
    ),
    "build_geographic_derived_features": (
        "hydromodpy.spatial.geographic.core.domain_geographic_pipeline",
        "build_geographic_derived_features",
    ),
    "build_domain_geographic_context": (
        "hydromodpy.spatial.geographic.core.domain_geographic_pipeline",
        "build_domain_geographic_context",
    ),
    "RiverMeshTrace": (
        "hydromodpy.spatial.geographic.core.river_mesh_trace",
        "RiverMeshTrace",
    ),
    "build_river_mesh_trace_from_vector": (
        "hydromodpy.spatial.geographic.core.river_mesh_trace",
        "build_river_mesh_trace_from_vector",
    ),
    "RiverNetworkProducts": (
        "hydromodpy.spatial.geographic.core.river_network",
        "RiverNetworkProducts",
    ),
    "resolve_stream_threshold_cells": (
        "hydromodpy.spatial.geographic.core.river_network",
        "resolve_stream_threshold_cells",
    ),
    "build_river_network_products": (
        "hydromodpy.spatial.geographic.core.river_network",
        "build_river_network_products",
    ),
}


def __getattr__(name: str):
    """Resolve core compatibility symbols lazily."""
    if name in _LAZY_V2_EXPORTS:
        module_name, attr_name = _LAZY_V2_EXPORTS[name]
        module = importlib.import_module(module_name)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy.spatial.geographic' has no attribute {name!r}")


__all__ = [
    "CatchmentDelineation",
    "GeographicConfig",
    "RiverNetworkConfig",
    "DEM_correcflow_analysis",
    "Subbasin",
    "LegacyDemMetadata",
    "read_legacy_dem_metadata",
    "LegacyDomainRasterProducts",
    "build_legacy_domain_rasters",
    "LegacyGeographicContext",
    "build_legacy_geographic_context",
    *_LAZY_V2_EXPORTS,
]


