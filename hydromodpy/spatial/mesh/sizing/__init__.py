"""Target cell size of a graded mesh, built from distance transforms on the DEM grid.

``size_field.py`` builds the field from its terms; ``gap.py`` adds the terms
that follow the gap between face lines.
"""

from __future__ import annotations

from hydromodpy.spatial.mesh.sizing.size_field import (
    MAX_SIZE_FIELD_PIXELS,
    OutsideCoarsening,
    PixelRegion,
    SizeTerm,
    build_size_field,
    sample_size_field,
)

__all__ = [
    "MAX_SIZE_FIELD_PIXELS",
    "OutsideCoarsening",
    "PixelRegion",
    "SizeTerm",
    "build_size_field",
    "sample_size_field",
]
