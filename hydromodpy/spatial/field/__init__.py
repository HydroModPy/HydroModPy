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
    "FieldParam": "hydromodpy.spatial.field.core:FieldParam",
    "Field": "hydromodpy.spatial.field.core:Field",
    "FieldSquare": "hydromodpy.spatial.field.cases.square:FieldSquare",
    "GeologyField": "hydromodpy.spatial.field.geology:GeologyField",
    "FieldDiscretization": "hydromodpy.spatial.field.core:FieldDiscretization",
    "WeightedAverageFieldDiscretization": "hydromodpy.spatial.field.core:WeightedAverageFieldDiscretization",
    "FieldMeshSquare": "hydromodpy.spatial.field.cases.square:FieldMeshSquare",
    "MeshCell": "hydromodpy.spatial.field.core:MeshCell",
    "MeshWithValues": "hydromodpy.spatial.field.core:MeshWithValues",
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
