"""Solute concentration map."""

from __future__ import annotations

from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._scalar_face_map import ScalarFaceMap


@register
class ConcentrationMap(ScalarFaceMap):
    """Per-cell solute concentration at one timestep."""

    spec = FigureSpec(
        name="concentration_map",
        title="Concentration",
        kind="spatial",
        required_fields=("concentration",),
        default_figsize=(7.0, 5.5),
    )
    default_cmap = "plasma"
    default_overlays = ("watershed",)
