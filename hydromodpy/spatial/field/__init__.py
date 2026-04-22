"""Field utilities (homogeneous/heterogeneous parameter handling)."""

from hydromodpy.spatial.field.cases.square import (
    FieldMeshSquare,
    FieldSquare,
)
from hydromodpy.spatial.field.core import (
    BaseFieldMesh,
    Field,
    FieldDiscretization,
    FieldMesh,
    FieldParam,
    MeshCell,
    MeshWithValues,
    WeightedAverageFieldDiscretization,
)
from hydromodpy.spatial.field.geology import (
    GeologyField,
    GeologyStructuredMesh,
)
from hydromodpy.spatial.field.meshes import (
    StructuredFieldMesh,
    TriangularStructuredFieldMesh,
    TriangularUnstructuredFieldMesh,
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
