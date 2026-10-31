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
    "Domain",
    "DomainConfig",
    "FieldParam",
    "CatchmentDelineation",
    "GeographicConfig",
    "CellBlock",
    "CellType",
    "HydroMesh",
]

_LAZY_IMPORTS = {
    "CatchmentZonesField": "hydromodpy.spatial.catchment_zones_field:CatchmentZonesField",
    "RasterSupport": "hydromodpy.spatial.raster_support:RasterSupport",
    "Surface": "hydromodpy.spatial.surface:Surface",
    "PreparedSurfaceSampler": "hydromodpy.spatial.surface_sampling:PreparedSurfaceSampler",
    "Domain": "hydromodpy.spatial.domain.domain:Domain",
    "DomainConfig": "hydromodpy.spatial.domain.domain_config:DomainConfig",
    "FieldParam": "hydromodpy.spatial.field.field_param:FieldParam",
    "CatchmentDelineation": "hydromodpy.spatial.geographic.catchment_delineation:CatchmentDelineation",
    "GeographicConfig": "hydromodpy.spatial.geographic.geographic_config:GeographicConfig",
    "CellBlock": "hydromodpy.spatial.mesh.model.hydro_mesh:CellBlock",
    "CellType": "hydromodpy.spatial.mesh.model.cell_types:CellType",
    "HydroMesh": "hydromodpy.spatial.mesh.model.hydro_mesh:HydroMesh",
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
