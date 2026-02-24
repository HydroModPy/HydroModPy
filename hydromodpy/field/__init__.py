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
from hydromodpy.field.cases.square import (
    FieldMeshSquare,
    FieldSquare,
    StructuredFieldMesh,
    TriangularStructuredFieldMesh,
    TriangularUnstructuredFieldMesh,
)
from hydromodpy.field.cases.geology import GeologyField

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
