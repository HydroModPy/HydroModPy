"""Geographic package facade.

The decomposed geographic workflow lives in ``hydromodpy.spatial.geographic.core``.
This package exposes the ``CatchmentDelineation`` runtime facade and its
public data contracts via lazy attribute access to keep import time low.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CatchmentDelineation",
    "CatchmentDomainProducts",
    "CatchmentFromPointProducts",
    "CatchmentZoneCode",
    "CatchmentZoneProducts",
    "DEM_correcflow_analysis",
    "DemMetadata",
    "DomainGeographicContext",
    "DomainRasterProducts",
    "FlowProducts",
    "GeographicBoundaryFeatures",
    "GeographicConfig",
    "GeographicDerivedFeatures",
    "GeographicRuntimeContext",
    "RiverMeshTrace",
    "RiverNetworkConfig",
    "RiverNetworkProducts",
    "Subbasin",
    "build_catchment_zone_codes",
    "build_domain_geographic_context",
    "build_domain_rasters",
    "build_geographic_derived_features",
    "build_geographic_runtime_context",
    "build_regional_flow_products",
    "build_river_mesh_trace_from_vector",
    "build_river_network_products",
    "build_surface_topo_from_dem",
    "clip_dem_to_box_buffer",
    "coerce_geographic_derived_features",
    "compute_catchment_area_km2",
    "derive_catchment_domain",
    "extract_catchment_from_point",
    "extract_catchment_from_polygon",
    "read_dem_metadata",
    "resolve_river_mesh_trace",
    "resolve_stream_threshold_cells",
]

_LAZY_IMPORTS: dict[str, str] = {
    "CatchmentDelineation": "hydromodpy.spatial.geographic.catchment_delineation:CatchmentDelineation",
    "DEM_correcflow_analysis": "hydromodpy.spatial.geographic.catchment_delineation:DEM_correcflow_analysis",
    "CatchmentDomainProducts": "hydromodpy.spatial.geographic.core.catchment_domain:CatchmentDomainProducts",
    "derive_catchment_domain": "hydromodpy.spatial.geographic.core.catchment_domain:derive_catchment_domain",
    "CatchmentFromPointProducts": "hydromodpy.spatial.geographic.core.catchment_from_point:CatchmentFromPointProducts",
    "extract_catchment_from_point": "hydromodpy.spatial.geographic.core.catchment_from_point:extract_catchment_from_point",
    "extract_catchment_from_polygon": "hydromodpy.spatial.geographic.core.catchment_from_polygon:extract_catchment_from_polygon",
    "compute_catchment_area_km2": "hydromodpy.spatial.geographic.core.catchment_metrics:compute_catchment_area_km2",
    "CatchmentZoneCode": "hydromodpy.spatial.geographic.core.catchment_zones:CatchmentZoneCode",
    "CatchmentZoneProducts": "hydromodpy.spatial.geographic.core.catchment_zones:CatchmentZoneProducts",
    "build_catchment_zone_codes": "hydromodpy.spatial.geographic.core.catchment_zones:build_catchment_zone_codes",
    "GeographicBoundaryFeatures": "hydromodpy.spatial.geographic.core.derived_features:GeographicBoundaryFeatures",
    "GeographicDerivedFeatures": "hydromodpy.spatial.geographic.core.derived_features:GeographicDerivedFeatures",
    "coerce_geographic_derived_features": "hydromodpy.spatial.geographic.core.derived_features:coerce_geographic_derived_features",
    "resolve_river_mesh_trace": "hydromodpy.spatial.geographic.core.derived_features:resolve_river_mesh_trace",
    "clip_dem_to_box_buffer": "hydromodpy.spatial.geographic.core.domain_dem:clip_dem_to_box_buffer",
    "DomainGeographicContext": "hydromodpy.spatial.geographic.core.domain_geographic_pipeline:DomainGeographicContext",
    "build_domain_geographic_context": "hydromodpy.spatial.geographic.core.domain_geographic_pipeline:build_domain_geographic_context",
    "build_geographic_derived_features": "hydromodpy.spatial.geographic.core.domain_geographic_pipeline:build_geographic_derived_features",
    "FlowProducts": "hydromodpy.spatial.geographic.core.flow_products:FlowProducts",
    "build_regional_flow_products": "hydromodpy.spatial.geographic.core.flow_products:build_regional_flow_products",
    "RiverMeshTrace": "hydromodpy.spatial.geographic.core.river_mesh_trace:RiverMeshTrace",
    "build_river_mesh_trace_from_vector": "hydromodpy.spatial.geographic.core.river_mesh_trace:build_river_mesh_trace_from_vector",
    "RiverNetworkProducts": "hydromodpy.spatial.geographic.core.river_network:RiverNetworkProducts",
    "build_river_network_products": "hydromodpy.spatial.geographic.core.river_network:build_river_network_products",
    "resolve_stream_threshold_cells": "hydromodpy.spatial.geographic.core.river_network:resolve_stream_threshold_cells",
    "build_surface_topo_from_dem": "hydromodpy.spatial.geographic.core.surface_from_dem:build_surface_topo_from_dem",
    "DemMetadata": "hydromodpy.spatial.geographic.dem_metadata:DemMetadata",
    "read_dem_metadata": "hydromodpy.spatial.geographic.dem_metadata:read_dem_metadata",
    "DomainRasterProducts": "hydromodpy.spatial.geographic.domain_rasters:DomainRasterProducts",
    "build_domain_rasters": "hydromodpy.spatial.geographic.domain_rasters:build_domain_rasters",
    "GeographicConfig": "hydromodpy.spatial.geographic.geographic_config:GeographicConfig",
    "RiverNetworkConfig": "hydromodpy.spatial.geographic.geographic_config:RiverNetworkConfig",
    "GeographicRuntimeContext": "hydromodpy.spatial.geographic.pipeline:GeographicRuntimeContext",
    "build_geographic_runtime_context": "hydromodpy.spatial.geographic.pipeline:build_geographic_runtime_context",
    "Subbasin": "hydromodpy.spatial.geographic.subbasin:Subbasin",
}


def __getattr__(name: str):
    try:
        target = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module_path, attr_name = target.split(":", 1)
    module = import_module(module_path)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
