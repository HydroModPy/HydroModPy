"""Plan view of an aquifer property, layer by layer.

The companion of ``parameter_section``: that one cuts the aquifer, this one
looks down on it. A zonation written as two polygons in the configuration
becomes two patches here, which is the only place a reader can check that the
zones landed where the geology says they should before reading any head.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures.parameter_section import LOG_SCALE_DECADES, PARAMETER_FIELDS
from hydromodpy.display.map_axes import style_relative_km_axes
from hydromodpy.display.overlays import apply_overlays
from hydromodpy.display.ugrid import render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class ParameterMap(BaseFigure):
    """One aquifer property across the domain, for one layer.

    Options
    -------
    ``variable``
        Property to draw. Defaults to the hydraulic conductivity.
    ``layer``
        Layer index, top layer by default.
    ``log``
        Force a log colour scale on or off. Decided from the spread by default.
    """

    spec = FigureSpec(
        name="parameter_map",
        title="Parameter map",
        kind="spatial",
        required_fields=("hydraulic_conductivity",),
        optional_fields=("specific_yield", "specific_storage"),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: str = "hydraulic_conductivity",
        layer: int = 0,
        log: bool | None = None,
        cmap: str = "viridis",
        overlays: tuple[str, ...] | list[str] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.colors import LogNorm

        if variable not in PARAMETER_FIELDS:
            raise ValueError(
                f"parameter_map: {variable!r} is not an aquifer property; "
                f"pick one of {', '.join(PARAMETER_FIELDS)}"
            )
        if not sim.has_field(variable):
            raise ValueError(f"parameter_map: {variable!r} is not in this run")

        values = np.atleast_2d(np.asarray(sim.field(variable), dtype="float64"))
        if not 0 <= layer < values.shape[0]:
            raise ValueError(
                f"parameter_map: layer {layer} is outside the {values.shape[0]} "
                "layer(s) this run has"
            )
        plane = values[int(layer)]

        collection = render_face_field(
            ax,
            sim,
            plane,
            cmap=cmap,
            cbar_label=self.axis_label_for(variable),
        )
        positive = plane[np.isfinite(plane) & (plane > 0.0)]
        spread = positive.size and np.log10(positive.max() / positive.min()) > LOG_SCALE_DECADES
        if bool(spread) if log is None else bool(log):
            collection.set_norm(LogNorm(vmin=float(positive.min()), vmax=float(positive.max())))

        apply_overlays(
            ax,
            sim,
            ("watershed", "outlet") if overlays is None else overlays,
            timestep=0,
        )
        style_relative_km_axes(ax)
        ax.set_title(
            f"{self.field_descriptor_for(variable).long_name} - "
            f"{sim.name or sim.sim_id}\nlayer {int(layer)}"
        )
        return ax


__all__ = ["ParameterMap"]
