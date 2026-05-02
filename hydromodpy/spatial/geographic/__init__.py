"""Geographic package.

The decomposed geographic workflow lives in ``hydromodpy.spatial.geographic.core``.
This package exposes the ``CatchmentDelineation`` runtime facade and its
public data contracts.
"""

from __future__ import annotations

from hydromodpy.spatial.geographic.catchment_delineation import (
    CatchmentDelineation,
    DEM_correcflow_analysis,
)
from hydromodpy.spatial.geographic.core.catchment_domain import (
    CatchmentDomainProducts,
    derive_catchment_domain,
)
from hydromodpy.spatial.geographic.core.catchment_from_point import (
    CatchmentFromPointProducts,
    extract_catchment_from_point,
)
from hydromodpy.spatial.geographic.core.catchment_from_polygon import (
    extract_catchment_from_polygon,
)
from hydromodpy.spatial.geographic.core.catchment_metrics import compute_catchment_area_km2
from hydromodpy.spatial.geographic.core.catchment_zones import (
    CatchmentZoneCode,
    CatchmentZoneProducts,
    build_catchment_zone_codes,
)
from hydromodpy.spatial.geographic.core.derived_features import (
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
    coerce_geographic_derived_features,
    resolve_river_mesh_trace,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HydrographicNetwork,
    HydrographicNetworks,
)
from hydromodpy.spatial.geographic.core.domain_dem import clip_dem_to_box_buffer
from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import (
    DomainGeographicContext,
    build_domain_geographic_context,
    build_geographic_derived_features,
)
from hydromodpy.spatial.geographic.core.flow_products import (
    FlowProducts,
    build_regional_flow_products,
)
from hydromodpy.spatial.geographic.core.river_mesh_trace import (
    RiverMeshTrace,
    build_river_mesh_trace_from_vector,
)
from hydromodpy.spatial.geographic.core.river_network import (
    RiverNetworkProducts,
    build_river_network_products,
    resolve_stream_threshold_cells,
)
from hydromodpy.spatial.geographic.core.surface_from_dem import build_surface_topo_from_dem
from hydromodpy.spatial.geographic.dem_metadata import (
    DemMetadata,
    read_dem_metadata,
)
from hydromodpy.spatial.geographic.domain_rasters import (
    DomainRasterProducts,
    build_domain_rasters,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig, RiverNetworkConfig
from hydromodpy.spatial.geographic.pipeline import (
    GeographicRuntimeContext,
    build_geographic_runtime_context,
)
from hydromodpy.spatial.geographic.subbasin import Subbasin

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
    "HydrographicNetwork",
    "HydrographicNetworks",
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
