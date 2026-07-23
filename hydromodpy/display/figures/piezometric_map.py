"""Water-table elevation map (piezometric surface)."""

from __future__ import annotations

from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._scalar_face_map import ScalarFaceMap


@register
class PiezometricMap(ScalarFaceMap):
    """Map of the water-table elevation at a given timestep."""

    spec = FigureSpec(
        name="piezometric_map",
        title="Water-table elevation",
        kind="spatial",
        required_fields=("watertable_elevation",),
        default_figsize=(7.0, 5.5),
    )
    default_cmap = "viridis"
    default_overlays = ("watershed", "outlet")
