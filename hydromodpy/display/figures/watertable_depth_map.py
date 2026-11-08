"""Water-table depth map (meters below the land surface)."""

from __future__ import annotations

from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figures.scalar_face_map import ScalarFaceMap


class WatertableDepthMap(ScalarFaceMap):
    """Depth of the water table below topography, at a given timestep.

    The complement of :class:`~hydromodpy.display.figures.piezometric_map.PiezometricMap`:
    elevation answers "where does groundwater flow", depth answers "how far
    down is it", which is what drives seepage and shallow-root uptake.
    A reversed colormap keeps shallow water dark, like the seepage map.
    """

    spec = FigureSpec(
        name="watertable_depth_map",
        title="Water-table depth",
        kind="spatial",
        required_fields=("watertable_depth",),
        default_figsize=(7.0, 5.5),
    )
    default_cmap = "YlGnBu_r"
    default_overlays = ("watershed", "outlet")
