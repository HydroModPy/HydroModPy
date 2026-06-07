"""Water-table elevation map (piezometric surface)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.map_axes import overlay_watershed_contour, style_relative_km_axes
from hydromodpy.display.ugrid import last_timestep, render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class PiezometricMap(BaseFigure):
    """Map of the water-table elevation at a given timestep."""

    spec = FigureSpec(
        name="piezometric_map",
        title="Water-table elevation",
        kind="spatial",
        required_fields=("watertable_elevation",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        cmap: str = "viridis",
        vmin: float | None = None,
        vmax: float | None = None,
        **_,
    ) -> Axes:
        ts = last_timestep(sim) if timestep is None else timestep
        head = sim.field("watertable_elevation", timestep=ts)
        render_face_field(
            ax,
            sim,
            head,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            cbar_label=self.axis_label_for("watertable_elevation"),
        )
        overlay_watershed_contour(ax, sim)
        style_relative_km_axes(ax)
        ax.set_title(f"Water table - {sim.name or sim.sim_id}")
        return ax
