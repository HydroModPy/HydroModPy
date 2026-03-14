"""Field utilities (homogeneous/heterogeneous parameter handling)."""

from hydromodpy.field.core import (
    BaseFieldMesh,
    Field,
    FieldDiscretization,
    FieldMesh,
    FieldParam,
    MeshCell,
    MeshWithValues,
    WeightedAverageFieldDiscretization,
)
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
    "FieldParam",
    "Field",
    "FieldSquare",
    "GeologyField",
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


def __getattr__(name):
    """Lazily resolve optional case modules to avoid import cycles."""
    if name == "GeologyField":
        from hydromodpy.data_managers.geology import GeologyField

        return GeologyField
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
