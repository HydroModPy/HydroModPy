"""Field utilities (homogeneous/heterogeneous parameter handling)."""

from __future__ import annotations

from importlib import import_module

__all__ = (
    "FieldParam",
    "Field",
    "FieldSquare",
    "GeologyField",
    "FieldDiscretization",
    "WeightedAverageFieldDiscretization",
    "FieldMeshSquare",
    "MeshCell",
    "MeshWithValues",
)

_LAZY_IMPORTS = {
    "FieldParam": "hydromodpy.spatial.field.field_param:FieldParam",
    "Field": "hydromodpy.spatial.field.field_spatial:Field",
    "FieldSquare": "hydromodpy.spatial.field.two_zone_field:FieldSquare",
    "GeologyField": "hydromodpy.spatial.field.geology_field:GeologyField",
    "FieldDiscretization": "hydromodpy.spatial.field.field_spatial:FieldDiscretization",
    "WeightedAverageFieldDiscretization": "hydromodpy.spatial.field.field_spatial:WeightedAverageFieldDiscretization",
    "FieldMeshSquare": "hydromodpy.spatial.field.unit_square_mesh:FieldMeshSquare",
    "MeshCell": "hydromodpy.spatial.field.mesh_cells:MeshCell",
    "MeshWithValues": "hydromodpy.spatial.field.mesh_cells:MeshWithValues",
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
