"""Where the snap moved the mapped stream network, cell by cell.

The raw mapped cells are drawn as outlines, the cells they moved onto filled,
and one segment joins each raw centre to its new one, coloured by what the
snap did: unchanged, moved, merged onto a cell already taken, or rejected
(kept at its raw position). A reader sees at a glance whether the map was
nudged onto its own valley or dragged into the next one, which no single
index says.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.stream_snap import SNAP_STATUS_LABELS
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._observed_network_snap import (
    STATUS_COLORS,
    STATUS_ORDER,
    snap_from_run,
    snap_note,
    snap_unavailable_reason,
    status_cells,
)
from hydromodpy.display.figures._stream_comparison import (
    CASING_COLOR,
    GROUND_COLOR,
    MapExtentName,
    cell_count,
    draw_cells,
    map_extent,
    map_legend,
    select_cells,
)
from hydromodpy.display.maps.axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display.maps.mesh_geometry import face_polygons

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

_SNAPPED_COLOR = "#88CCEE"
"""The fill of the snapped map, light so the segments read over it."""


@register
class ObservedNetworkSnapMap(BaseFigure):
    """The mapped network before and after ``[geographic.snap_streams]``.

    Drawn from the snap the run's own setting produces, through the
    construction the criterion scores. Unavailable when the run's snap is off.
    """

    spec = FigureSpec(
        name="observed_network_snap_map",
        title="Mapped network snapped onto the talwegs",
        kind="comparison",
        required_fields=("release_flux",),
        default_figsize=(7.0, 6.6),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Return why this run holds no snap, or None when it does."""
        return snap_unavailable_reason(sim) or super().unavailable_reason(sim)

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        extent: MapExtentName = "catchment",
        **_,
    ) -> Axes:
        from matplotlib.collections import LineCollection
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        snap = snap_from_run(sim)
        polygons = face_polygons(sim)
        if len(polygons) != snap.raw.size:
            raise ValueError(
                f"the snap holds {snap.raw.size} cells, the mesh holds {len(polygons)}."
            )
        centres = np.asarray([polygon.mean(axis=0)[:2] for polygon in polygons], dtype=float)

        draw_cells(
            ax,
            select_cells(polygons, snap.snapped),
            color=_SNAPPED_COLOR,
            label="snapped map",
            zorder=2,
            edgecolor=_SNAPPED_COLOR,
        )
        draw_cells(
            ax,
            select_cells(polygons, snap.raw),
            color="none",
            label="raw map",
            zorder=3,
            edgecolor=CASING_COLOR,
        )
        handles = [
            Patch(facecolor=_SNAPPED_COLOR, label=f"snapped map ({cell_count(snap.snapped)})"),
            Patch(
                facecolor="none",
                edgecolor=CASING_COLOR,
                label=f"raw map ({cell_count(snap.raw)})",
            ),
        ]
        for zorder, code in enumerate(STATUS_ORDER, start=4):
            cells = status_cells(snap, code)
            label = SNAP_STATUS_LABELS[code]
            handles.append(
                Line2D(
                    [],
                    [],
                    color=STATUS_COLORS[code],
                    marker="o",
                    linestyle="-",
                    label=f"{label} ({cell_count(snap.status == code)})",
                )
            )
            if cells.size == 0:
                continue
            ends = np.where(snap.target[cells] >= 0, snap.target[cells], cells)
            segments = np.stack([centres[cells], centres[ends]], axis=1)
            ax.add_collection(
                LineCollection(
                    segments,
                    colors=STATUS_COLORS[code],
                    linewidths=1.2,
                    zorder=zorder,
                    label=f"_{label} displacement",
                )
            )
            ax.scatter(
                centres[cells, 0],
                centres[cells, 1],
                s=6,
                color=STATUS_COLORS[code],
                zorder=zorder,
                label="_" + label,
            )

        ax.set_facecolor(GROUND_COLOR)
        style_map_axes(ax)
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")
        window = map_extent(sim, polygons, extent=extent)
        map_legend(ax, handles, note=snap_note(snap), ncols=3)
        window.apply(ax)
        return ax


__all__ = ["ObservedNetworkSnapMap"]
