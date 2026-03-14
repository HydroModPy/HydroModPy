"""Case-specific field implementations and launchers."""

from hydromodpy.field.meshes import (
    StructuredFieldMesh,
    TriangularStructuredFieldMesh,
    TriangularUnstructuredFieldMesh,
)
from hydromodpy.field.cases.square import (
    FieldMeshSquare,
    FieldSquare,
)

__all__ = (
    "FieldSquare",
    "FieldMeshSquare",
    "StructuredFieldMesh",
    "TriangularStructuredFieldMesh",
    "TriangularUnstructuredFieldMesh",
    "GeologyField",
)


def __getattr__(name):
    """Lazily resolve optional case modules to avoid import cycles."""
    if name == "GeologyField":
        from hydromodpy.data_managers.geology import GeologyField

        return GeologyField
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
