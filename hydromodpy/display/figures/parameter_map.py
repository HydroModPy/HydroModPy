"""Plan view of an aquifer property, layer by layer.

The companion of ``parameter_section``: that one cuts the aquifer, this one
looks down on it. A zonation written as two polygons in the configuration
becomes two patches here, which is the only place a reader can check that the
zones landed where the geology says they should before reading any head. The
conductivity along the other axes of the K tensor and its three angles are
drawn the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec, run_suffix
from hydromodpy.display.figure_options import CmapOrOwn, Opt, Overlays
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._parameter_scale import (
    CYCLIC_FIELDS,
    PARAMETER_CHOICES,
    PARAMETER_FIELDS,
    cmap_for,
    colour_norm,
    mark_turn,
    parameter_label,
    parameter_name,
    require_property,
    wrapped,
)
from hydromodpy.display.figures.scalar_face_map import top_active_values
from hydromodpy.display.maps.axes import style_relative_km_axes
from hydromodpy.display.maps.overlays import apply_overlays
from hydromodpy.display.maps.ugrid import render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class ParameterMap(BaseFigure):
    """One aquifer property across the domain, for one layer."""

    spec = FigureSpec(
        name="parameter_map",
        title="Parameter map",
        kind="spatial",
        required_fields=("hydraulic_conductivity",),
        optional_fields=tuple(
            name for name in PARAMETER_FIELDS if name != "hydraulic_conductivity"
        ),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: Annotated[
            str,
            Opt(f"Property to draw: {PARAMETER_CHOICES}."),
        ] = "hydraulic_conductivity",
        layer: Annotated[
            int | None,
            Opt(
                "Model layer to draw, counted from 0 at the top. Left out, the top "
                "active cell of each column."
            ),
        ] = None,
        log: Annotated[
            bool | None,
            Opt(
                "Force a log colour scale on or off. Left out, a log scale when the "
                "positive values span more than one decade. The tensor angles are "
                "always linear."
            ),
        ] = None,
        cmap: CmapOrOwn = None,
        overlays: Overlays = None,
        **_,
    ) -> Axes:
        require_property(sim, variable, figure="parameter_map")

        values = np.atleast_2d(np.asarray(sim.field(variable), dtype="float64"))
        if layer is None:
            plane = top_active_values(sim, values)
        elif 0 <= layer < values.shape[0]:
            plane = values[int(layer)]
        else:
            raise ValueError(
                f"parameter_map: layer {layer} is outside the {values.shape[0]} "
                "layer(s) this run has"
            )

        plane = wrapped(variable, plane)
        collection = render_face_field(
            ax,
            sim,
            plane,
            cmap=cmap_for(variable, cmap),
            cbar_label=parameter_label(variable),
        )
        norm = colour_norm(variable, plane, log=log)
        if norm is not None:
            collection.set_norm(norm)
        if variable in CYCLIC_FIELDS:
            mark_turn(collection.colorbar)

        apply_overlays(
            ax,
            sim,
            ("watershed", "outlet") if overlays is None else overlays,
            timestep=0,
        )
        style_relative_km_axes(ax)
        where = "top active cell" if layer is None else f"layer {int(layer)}"
        ax.set_title(f"{parameter_name(variable)}{run_suffix(sim)}\n{where}")
        return ax


__all__ = ["ParameterMap"]
