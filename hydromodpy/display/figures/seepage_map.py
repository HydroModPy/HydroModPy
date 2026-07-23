"""Seepage area map (cells where the water table reaches the surface)."""

from __future__ import annotations

from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._scalar_face_map import ScalarFaceMap


@register
class SeepageMap(ScalarFaceMap):
    """Binary seepage indicator over the mesh.

    1 marks cells where the simulated head reaches or exceeds the surface
    elevation; 0 marks cells where the water table stays below ground.
    """

    spec = FigureSpec(
        name="seepage_map",
        title="Seepage areas",
        kind="spatial",
        required_fields=("seepage_mask",),
        default_figsize=(7.0, 5.5),
    )
    default_cmap = "Reds"
    default_overlays = ("watershed", "outlet")
    cbar_label = "Seepage (1 = water table at surface)"

    def render(self, sim, ax, *, vmin=None, vmax=None, **opts):
        """Pin the colour scale to the 0-1 indicator range."""
        return super().render(
            sim,
            ax,
            vmin=0.0 if vmin is None else vmin,
            vmax=1.0 if vmax is None else vmax,
            **opts,
        )
