"""Generic core components for field parameterization and discretization."""

from hydromodpy.field.core.field_mesh import BaseFieldMesh, FieldMesh, MeshCell, MeshWithValues
from hydromodpy.field.core.field_param import FieldParam
from hydromodpy.field.core.field_spatial import Field, FieldDiscretization
from hydromodpy.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)

__all__ = (
    "FieldParam",
    "Field",
    "FieldDiscretization",
    "WeightedAverageFieldDiscretization",
    "FieldMesh",
    "MeshCell",
    "MeshWithValues",
    "BaseFieldMesh",
)

