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
from hydromodpy.field.geology import (
    GeologyField,
    GeologyStructuredMesh,
)

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
