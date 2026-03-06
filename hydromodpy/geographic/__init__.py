"""Legacy geographic package with compatibility bridges.

The new decomposed geographic workflow is now hosted in
``hydromodpy.geographic_v2``.
"""

from __future__ import annotations

import importlib

from hydromodpy.geographic.geographic import DEM_correcflow_analysis, Geographic
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.geographic.subbasin import Subbasin

_LAZY_V2_EXPORTS: dict[str, tuple[str, str]] = {
    # Keep transitional compatibility from ``hydromodpy.geographic``.
    "CatchmentFromPointProducts": (
        "hydromodpy.geographic_v2.catchment_from_point",
        "CatchmentFromPointProducts",
    ),
    "extract_catchment_from_point": (
        "hydromodpy.geographic_v2.catchment_from_point",
        "extract_catchment_from_point",
    ),
    "CatchmentDomainProducts": (
        "hydromodpy.geographic_v2.catchment_domain",
        "CatchmentDomainProducts",
    ),
    "derive_catchment_domain": (
        "hydromodpy.geographic_v2.catchment_domain",
        "derive_catchment_domain",
    ),
    "extract_catchment_from_polygon": (
        "hydromodpy.geographic_v2.catchment_from_polygon",
        "extract_catchment_from_polygon",
    ),
    "compute_catchment_area_km2": (
        "hydromodpy.geographic_v2.catchment_metrics",
        "compute_catchment_area_km2",
    ),
    "CatchmentZoneCode": (
        "hydromodpy.geographic_v2.catchment_zones",
        "CatchmentZoneCode",
    ),
    "CatchmentZoneProducts": (
        "hydromodpy.geographic_v2.catchment_zones",
        "CatchmentZoneProducts",
    ),
    "build_catchment_zone_codes": (
        "hydromodpy.geographic_v2.catchment_zones",
        "build_catchment_zone_codes",
    ),
    "clip_dem_to_box_buffer": (
        "hydromodpy.geographic_v2.domain_dem",
        "clip_dem_to_box_buffer",
    ),
    "FlowProducts": (
        "hydromodpy.geographic_v2.flow_products",
        "FlowProducts",
    ),
    "build_regional_flow_products": (
        "hydromodpy.geographic_v2.flow_products",
        "build_regional_flow_products",
    ),
    "build_surface_topo_from_dem": (
        "hydromodpy.geographic_v2.surface_from_dem",
        "build_surface_topo_from_dem",
    ),
    "DomainGeographicContext": (
        "hydromodpy.geographic_v2.domain_geographic_pipeline",
        "DomainGeographicContext",
    ),
    "build_domain_geographic_context": (
        "hydromodpy.geographic_v2.domain_geographic_pipeline",
        "build_domain_geographic_context",
    ),
}


def __getattr__(name: str):
    """Resolve V2 compatibility symbols lazily."""
    if name in _LAZY_V2_EXPORTS:
        module_name, attr_name = _LAZY_V2_EXPORTS[name]
        module = importlib.import_module(module_name)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy.geographic' has no attribute {name!r}")


__all__ = [
    "Geographic",
    "GeographicConfig",
    "DEM_correcflow_analysis",
    "Subbasin",
    *_LAZY_V2_EXPORTS,
]
