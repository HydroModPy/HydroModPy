"""Field utilities (homogeneous/heterogeneous parameter handling)."""

from __future__ import annotations

from importlib import import_module

__all__ = (
    "FieldParam",
    "Field",
    "FieldSquare",
    "GeologyField",
    "GeologyStructuredMesh",
    "FieldDiscretization",
    "WeightedAverageFieldDiscretization",
    "FieldMesh",
    "FieldMeshSquare",
    "MeshCell",
    "MeshWithValues",
    "BaseFieldMesh",
    "StructuredFieldMesh",
    "TriangularStructuredFieldMesh",
    "TriangularUnstructuredFieldMesh",
)

_LAZY_IMPORTS = {
    "FieldParam": "hydromodpy.spatial.field.core:FieldParam",
    "Field": "hydromodpy.spatial.field.core:Field",
    "FieldSquare": "hydromodpy.spatial.field.cases.square:FieldSquare",
    "GeologyField": "hydromodpy.spatial.field.geology:GeologyField",
    "GeologyStructuredMesh": "hydromodpy.spatial.field.geology:GeologyStructuredMesh",
    "FieldDiscretization": "hydromodpy.spatial.field.core:FieldDiscretization",
    "WeightedAverageFieldDiscretization": "hydromodpy.spatial.field.core:WeightedAverageFieldDiscretization",
    "FieldMesh": "hydromodpy.spatial.field.core:FieldMesh",
    "FieldMeshSquare": "hydromodpy.spatial.field.cases.square:FieldMeshSquare",
    "MeshCell": "hydromodpy.spatial.field.core:MeshCell",
    "MeshWithValues": "hydromodpy.spatial.field.core:MeshWithValues",
    "BaseFieldMesh": "hydromodpy.spatial.field.core:BaseFieldMesh",
    "StructuredFieldMesh": "hydromodpy.spatial.field.meshes:StructuredFieldMesh",
    "TriangularStructuredFieldMesh": "hydromodpy.spatial.field.meshes:TriangularStructuredFieldMesh",
    "TriangularUnstructuredFieldMesh": "hydromodpy.spatial.field.meshes:TriangularUnstructuredFieldMesh",
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
