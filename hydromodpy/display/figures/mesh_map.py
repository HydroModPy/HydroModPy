"""Solver mesh drawn cell by cell, coloured by land-surface elevation.

The "what did the model actually discretize" figure. It works unchanged on
a structured MODFLOW DIS grid (rectangles), on a MODFLOW 6 DISV Voronoi or
triangular mesh, and on the Boussinesq triangulation, because all of them
serialize to the same UGRID face/vertex arrays.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import (
    RELATIVE_MAP_COLORBAR_LABEL_SIZE,
    RELATIVE_MAP_COLORBAR_TICK_SIZE,
    style_relative_km_axes,
)
from hydromodpy.display.overlays import apply_overlays

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class MeshMap(BaseFigure):
    """Plan view of the solver mesh with visible cell edges."""

    spec = FigureSpec(
        name="mesh_map",
        title="Solver mesh",
        kind="spatial",
        required_fields=("topography",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        cmap: str = "terrain",
        edge_color: str = "0.25",
        edge_width: float | None = None,
        overlays: tuple[str, ...] | list[str] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.collections import PolyCollection

        from hydromodpy.display.mesh_geometry import face_polygons

        polygons = face_polygons(sim)
        topography = np.asarray(sim.field("topography"), dtype="float64").ravel()
        n_faces = len(polygons)
        # Thin the edges on a dense mesh, otherwise the strokes swallow the fill.
        width = edge_width if edge_width is not None else (0.35 if n_faces < 5000 else 0.1)
        collection = PolyCollection(
            polygons,
            array=topography,
            cmap=cmap,
            edgecolors=edge_color,
            linewidths=width,
        )
        ax.add_collection(collection)
        ax.set_aspect("equal", adjustable="datalim")
        ax.autoscale_view()
        cbar = ax.figure.colorbar(collection, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label(self.axis_label_for("topography"), fontsize=RELATIVE_MAP_COLORBAR_LABEL_SIZE)
        cbar.ax.tick_params(labelsize=RELATIVE_MAP_COLORBAR_TICK_SIZE)

        apply_overlays(ax, sim, ("watershed", "outlet") if overlays is None else overlays)
        style_relative_km_axes(ax)
        ax.set_title(
            f"{self.spec.title} - {sim.name or sim.sim_id}\n{n_faces} cells, {_layer_label(sim)}"
        )
        handles, _labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc="best", fontsize=8, framealpha=0.9)
        return ax


def _layer_label(sim: Run) -> str:
    """Return a short description of the vertical discretization."""
    n_layers = getattr(sim, "n_layers", None)
    if n_layers is None:
        return "vertical layering unknown"
    return f"{n_layers} layer" + ("s" if int(n_layers) > 1 else "")
