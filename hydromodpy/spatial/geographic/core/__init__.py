"""Core building blocks for HydroModPy geographic preprocessing.

Purpose
-------
Provide small, testable modules that each implement one geographic step
(flow products, catchment delineation, domain clipping, zoning, metrics).

How to use this package
-----------------------
- Normal runtime code should keep using ``hydromodpy.spatial.geographic`` as facade.
- Advanced integrations can import specific modules from ``geographic.core``
  when a finer orchestration is required.
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
    "river_mesh_trace",
    "surface_from_dem",
]
