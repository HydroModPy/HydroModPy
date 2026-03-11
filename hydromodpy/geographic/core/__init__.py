"""Core geographic implementations.

This package contains the de-composed geographic pipeline used by domain
orchestration. Public entrypoints should keep importing from
``hydromodpy.geographic`` (compatibility façade) or from this core package when
advanced integration is needed.
"""

__all__ = [
    "catchment_domain",
    "catchment_from_point",
    "catchment_from_polygon",
    "catchment_metrics",
    "catchment_zones",
    "direct_dem_domain",
    "domain_dem",
    "domain_geographic_pipeline",
    "flow_products",
    "pipeline_steps",
    "surface_from_dem",
]
