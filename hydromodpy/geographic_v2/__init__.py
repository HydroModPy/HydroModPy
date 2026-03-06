"""Geographic V2 package.

This package hosts the new decomposed geographic workflow:
- catchment extraction,
- domain polygon derivation,
- DEM/domain clipping,
- 3-zone coding on raster support.

Implementation note:
- imports are lazy to keep package import light and avoid circular imports
  with legacy ``hydromodpy.geographic`` modules.
"""

from __future__ import annotations

import importlib

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Catchment creation
    "CatchmentFromPointProducts": (
        "hydromodpy.geographic_v2.catchment_from_point",
        "CatchmentFromPointProducts",
    ),
    "extract_catchment_from_point": (
        "hydromodpy.geographic_v2.catchment_from_point",
        "extract_catchment_from_point",
    ),
    "extract_catchment_from_polygon": (
        "hydromodpy.geographic_v2.catchment_from_polygon",
        "extract_catchment_from_polygon",
    ),
    "compute_catchment_area_km2": (
        "hydromodpy.geographic_v2.catchment_metrics",
        "compute_catchment_area_km2",
    ),
    # Domain polygons
    "CatchmentDomainProducts": (
        "hydromodpy.geographic_v2.catchment_domain",
        "CatchmentDomainProducts",
    ),
    "derive_catchment_domain": (
        "hydromodpy.geographic_v2.catchment_domain",
        "derive_catchment_domain",
    ),
    # Zoning
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
    # Raster products
    "FlowProducts": (
        "hydromodpy.geographic_v2.flow_products",
        "FlowProducts",
    ),
    "build_regional_flow_products": (
        "hydromodpy.geographic_v2.flow_products",
        "build_regional_flow_products",
    ),
    "clip_dem_to_box_buffer": (
        "hydromodpy.geographic_v2.domain_dem",
        "clip_dem_to_box_buffer",
    ),
    "build_surface_topo_from_dem": (
        "hydromodpy.geographic_v2.surface_from_dem",
        "build_surface_topo_from_dem",
    ),
    # End-to-end context assembly
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
    """Resolve V2 exports lazily on first access."""
    if name in _LAZY_IMPORTS:
        module_name, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_name)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy.geographic_v2' has no attribute {name!r}")


__all__ = list(_LAZY_IMPORTS)
