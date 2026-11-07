"""Spatial layer for HydroModPy.

The package exposes a compact public surface while keeping imports lazy so
submodule documentation does not pull the whole spatial runtime eagerly.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CatchmentZonesField",
    "RasterSupport",
    "Surface",
    "PreparedSurfaceSampler",
    "CatchmentDelineation",
    "GeographicConfig",
]

_LAZY_IMPORTS = {
    "CatchmentZonesField": "hydromodpy.spatial.geographic.core.catchment_zones_field:CatchmentZonesField",
    "RasterSupport": "hydromodpy.spatial.raster_support:RasterSupport",
    "Surface": "hydromodpy.spatial.surface:Surface",
    "PreparedSurfaceSampler": "hydromodpy.spatial.surface_sampling:PreparedSurfaceSampler",
    "CatchmentDelineation": "hydromodpy.spatial.geographic.catchment_delineation:CatchmentDelineation",
    "GeographicConfig": "hydromodpy.spatial.geographic.geographic_config:GeographicConfig",
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
