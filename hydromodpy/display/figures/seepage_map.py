"""Seepage area map: the cells where the water table reaches the land surface.

The field is a yes or no per cell, so the map draws two classes and counts
them in its key, as ``flow_intermittence_map`` does. A continuous colour ramp
would invite reading a fraction of seepage that the field does not hold.

It is the raw state of each cell at one instant. The flow maps apply the
network criterion on top of it, a routing downstream of the seepage cells
and a visible flow, so they draw connected streams where this map draws the
cells the water table reaches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._scalar_face_map import ScalarFaceMap
from hydromodpy.display.figures._stream_comparison import (
    GROUND_COLOR,
    MapExtentName,
    catchment_cells,
    checked_cells,
    draw_cells,
    map_extent,
    map_legend,
    select_cells,
    veil_outside_catchment,
)
from hydromodpy.display.maps.axes import style_map_axes
from hydromodpy.display.maps.mesh_geometry import face_polygons
from hydromodpy.display.maps.overlays import apply_overlays
from hydromodpy.display.maps.ugrid import last_timestep

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.patches import Patch

    from hydromodpy.results.run import Run

SEEPAGE_COLOR = "#08519c"
"""Cells where the water table reaches the land surface."""

GROUND_EDGE = "#c8c8c8"
"""A border on the legend swatch of the ground, otherwise near-white on white."""


@register
class SeepageMap(ScalarFaceMap):
    """Seepage and no-seepage cells of one stress period.

    A cell seeps where the simulated head reaches or exceeds the land
    surface. ``extent`` picks the frame: ``catchment`` (the default) crops to
    the delineated watershed and counts the cells inside it, ``mesh`` keeps
    the whole modelled domain and counts every cell.
    """

    spec = FigureSpec(
        name="seepage_map",
        title="Seepage areas",
        kind="spatial",
        required_fields=("seepage_mask",),
        default_figsize=(7.0, 6.2),
    )
    default_overlays = ("watershed", "outlet")

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        layer: int | None = None,
        overlays: tuple[str, ...] | list[str] | None = None,
        extent: MapExtentName = "catchment",
        **_,
    ) -> Axes:
        step = last_timestep(sim) if timestep is None else timestep
        polygons = face_polygons(sim)
        seeping = checked_cells(
            self.values(sim, timestep=step, layer=layer), len(polygons), "seepage mask"
        )
        seeping = np.nan_to_num(np.asarray(seeping, dtype="float64"), nan=0.0) > 0.0

        draw_cells(
            ax,
            select_cells(polygons, ~seeping),
            color=GROUND_COLOR,
            label="_no seepage",
            zorder=1,
            weight_pt=0.0,
        )
        draw_cells(
            ax, select_cells(polygons, seeping), color=SEEPAGE_COLOR, label="_seepage", zorder=2
        )

        window = map_extent(sim, polygons, extent=extent)
        counted = catchment_cells(sim, polygons) if extent == "catchment" else None
        if counted is not None:
            veil_outside_catchment(ax, sim, window)
        apply_overlays(
            ax,
            sim,
            self.default_overlays if overlays is None else overlays,
            timestep=step,
        )
        style_map_axes(ax)
        ax.set_title(self.title(sim, timestep=step))

        handles = ax.get_legend_handles_labels()[0]
        handles.extend(seepage_handles(seeping, counted))
        where = "in the catchment" if counted is not None else "over the whole mesh"
        note = (
            "water table at or above the land surface, cell by cell, before any routing\n"
            f"cells counted {where}"
        )
        map_legend(ax, handles, note=note, ncols=min(len(handles), 3))
        window.apply(ax)
        return ax


def seepage_handles(seeping: np.ndarray, counted: np.ndarray | None) -> list[Patch]:
    """Return the two legend patches, each with the number of cells it holds.

    ``counted`` restricts the counts to the cells of the catchment; ``None``
    counts every cell of the mesh.
    """
    from matplotlib.patches import Patch

    scope = np.ones_like(seeping, dtype=bool) if counted is None else counted
    wet = int((seeping & scope).sum())
    dry = int((~seeping & scope).sum())
    return [
        Patch(facecolor=SEEPAGE_COLOR, label=f"seepage ({wet:,} cells)"),
        Patch(facecolor=GROUND_COLOR, edgecolor=GROUND_EDGE, label=f"no seepage ({dry:,} cells)"),
    ]


__all__ = ["SeepageMap", "seepage_handles"]
