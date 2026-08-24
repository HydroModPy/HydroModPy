"""What the model still has to climb out of, on the mesh it routes on.

A downslope distance is a length along a flow path, and a flow path is only
defined once the depressions are resolved: on a raw surface a descent stops in
a pit that does not exist hydrologically, and the cells behind it have no
distance at all. The criterion therefore floods the mesh top before measuring
anything. This map is that flood: how much every cell has to be raised before
water can leave it, in metres, zero almost everywhere.

The value of the map is in the cells that are NOT zero. A patch of raised cells
inside the catchment is a place where the surface the model routes on does not
drain the way the terrain does, and the depth says how badly. Outside the
catchment the same patch is expected: the mesh is a buffered box, only one cell
is sealed as an outlet, and everything that cannot reach it is flooded to its
rim by construction. Reading the two together is why the note carries both
counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M, fill_depressions_on_graph
from hydromodpy.core.topographic_distance import (
    build_downslope_metric,
    downslope_distance_to_mask,
)
from hydromodpy.display.colormaps import get_cmap
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._routing_surface import (
    RoutingSurface,
    routing_surface_from_run,
    unavailable_reason_for_routing,
)
from hydromodpy.display.figures._stream_comparison import annotate_note, cell_count
from hydromodpy.display.map_axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display.mesh_geometry import face_polygons

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.colors import Colormap

    from hydromodpy.results.run import Run

_FILL_CMAP = "magma_r"
"""Light to black as the fill deepens.

Perceptually uniform, so the depth ordering survives a greyscale print, and
reversed so that a deep fill is the dark thing on the page. Its light end sits
well above the grey of a cell that was not raised, and its dark end well below:
a raised cell is separable from the background whatever its depth.
"""

_UNRAISED_FACE = "#D9D9D9"
_INACTIVE_FACE = "#FFFFFF"
_OUTLET_EDGE = "#111111"

DRAINS_LABEL = "drains as it stands"
RAISED_LABEL = "raised to drain"
INACTIVE_LABEL = "no elevation"
OUTLET_LABEL = "outlet the flood was sealed on"

DEFAULT_CLIP_PERCENTILE = 99.0
"""Percentile the colour scale stops at, so one deep sink does not flatten it."""


@dataclass(frozen=True, slots=True)
class DepressionFill:
    """The flood of one routing surface, and what it left behind."""

    surface: RoutingSurface
    filled: np.ndarray
    """(n_cells,) elevations after the flood, NaN off the active mesh."""

    fill_m: np.ndarray
    """(n_cells,) filled minus persisted, in metres, NaN off the active mesh."""

    raised: np.ndarray
    """(n_cells,) bool: cells the flood had to lift onto a spill level."""

    stranded_fraction: float
    """Share of the support whose descent still misses the sealed outlet.

    Zero is the only healthy answer: after a flood seeded on one cell, every
    path of the support ends there by construction. Anything else means the
    surface the flood conditioned is not the one the descent walks, which is
    what a mismatched neighbourhood produces.
    """


def depression_fill(surface: RoutingSurface) -> DepressionFill:
    """Flood ``surface`` from its outlet and measure what the flood changed.

    The flood and the descent that checks it walk the SAME neighbour graph. Fed
    the eight-neighbour graph while the descent reads the four-neighbour one,
    the flood leaves every filled cell spilling over a diagonal the descent
    cannot take, and almost the whole catchment stops reaching the outlet. The
    metric below re-derives its adjacency from ``diagonal_neighbors`` through
    the two builders the surface already used, so the pair cannot drift.
    """
    active = surface.active
    original = np.where(active, surface.topography, np.nan)
    report = fill_depressions_on_graph(original, surface.adjacency, surface.outlet_mask())
    fill_m = report.surface - original
    raised = active & (fill_m > DEFAULT_EPSILON_M / 2.0)

    metric = build_downslope_metric(
        report.surface,
        surface.face_node_connectivity,
        vertices=surface.vertices,
        centroids=surface.centroids,
        inactive_mask=~active,
        diagonal_neighbors=surface.diagonal_neighbors,
    )
    distance = downslope_distance_to_mask(metric, surface.outlet_mask())
    support = surface.within_catchment(active)
    stranded = float(np.mean(~np.isfinite(distance[support]))) if support.any() else float("nan")
    return DepressionFill(
        surface=surface,
        filled=report.surface,
        fill_m=fill_m,
        raised=raised,
        stranded_fraction=stranded,
    )


@register
class DepressionMap(BaseFigure):
    """Closed depressions of the mesh top, and the fill each one needs.

    Not to be confused with ``conditioning_impact_map``, which shows what the
    geographic step did to the DEM before the mesh existed. This one is what is
    LEFT once that DEM has been resampled onto the mesh: a raster conditioned
    on its own grid grows new pits under a different neighbourhood, and those
    are the pits the model actually routes around. For a criterion measured on
    the mesh, this is the map that matters.
    """

    spec = FigureSpec(
        name="depression_map",
        title="Depressions of the routing surface",
        kind="spatial",
        default_figsize=(7.5, 6.0),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Return why this run carries no surface to route on, or None."""
        return unavailable_reason_for_routing(sim) or super().unavailable_reason(sim)

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        diagonal_neighbors: bool = False,
        clip_percentile: float = DEFAULT_CLIP_PERCENTILE,
        cmap: str | None = None,
        **_,
    ) -> Axes:
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        surface = routing_surface_from_run(sim, diagonal_neighbors=diagonal_neighbors)
        polygons = face_polygons(sim)
        if len(polygons) != surface.n_cells:
            raise ValueError(
                f"the mesh draws {len(polygons)} faces and the routing surface holds "
                f"{surface.n_cells} cells."
            )
        fill = depression_fill(surface)

        drains = surface.active & ~fill.raised
        _add_flat(ax, polygons, drains, color=_UNRAISED_FACE, label=DRAINS_LABEL)
        _add_flat(ax, polygons, ~surface.active, color=_INACTIVE_FACE, label=INACTIVE_LABEL)
        vmax = _color_ceiling(_scaled_fills(fill), clip_percentile)
        _add_fill(ax, polygons, fill, cmap=get_cmap(cmap or _FILL_CMAP), vmax=vmax)

        outlet_x, outlet_y = surface.centroids[surface.outlet]
        outlet_marker = {
            "marker": "*",
            "markerfacecolor": "#FFFFFF",
            "markeredgecolor": _OUTLET_EDGE,
            "linestyle": "none",
        }
        ax.plot([outlet_x], [outlet_y], markersize=13, zorder=8, **outlet_marker)
        style_map_axes(ax)
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")

        handles: list[Patch | Line2D] = [
            Patch(
                facecolor=_UNRAISED_FACE,
                edgecolor="none",
                label=f"{DRAINS_LABEL} ({cell_count(drains)})",
            ),
            Line2D([0], [0], markersize=11, label=OUTLET_LABEL, **outlet_marker),
        ]
        if not surface.active.all():
            handles.append(
                Patch(
                    facecolor=_INACTIVE_FACE,
                    edgecolor="#909090",
                    label=f"{INACTIVE_LABEL} ({cell_count(~surface.active)})",
                )
            )
        ax.legend(handles=handles, loc="upper left", fontsize=8.5, framealpha=0.9)
        annotate_note(ax, "\n".join(_notes(fill)))
        return ax


def _scaled_fills(fill: DepressionFill) -> np.ndarray:
    """Return the fills the colour scale is stretched over.

    The catchment when the run has one. Outside it the mesh is a buffered box
    with a single sealed outlet, so everything that cannot reach that outlet
    is flooded to its rim by construction and reaches tens of metres. A
    percentile taken over the whole mesh is therefore set by the lobes the
    figure itself calls expected, and the metre-scale pits inside the
    catchment, the ones the note calls the real signal, all collapse onto the
    first colour of the ramp.
    """
    surface = fill.surface
    if surface.catchment is None:
        return fill.fill_m[fill.raised]
    inside = fill.fill_m[surface.within_catchment(fill.raised)]
    return inside if inside.size else fill.fill_m[fill.raised]


def _color_ceiling(values: np.ndarray, clip_percentile: float) -> float:
    """Return the top of the colour scale, floored so a scale always exists."""
    percentile = float(clip_percentile)
    if not 0.0 < percentile <= 100.0:
        raise ValueError(f"clip_percentile must lie in (0, 100], got {percentile}.")
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return DEFAULT_EPSILON_M
    return max(float(np.percentile(finite, percentile)), DEFAULT_EPSILON_M)


def _notes(fill: DepressionFill) -> list[str]:
    """Return the lines a reader needs to know which flood is on the page."""
    surface = fill.surface
    raised = fill.raised
    count = int(raised.sum())
    if count == 0:
        lines = ["no closed depression: the mesh top drains to the outlet as it stands"]
    else:
        share = count / surface.n_cells if surface.n_cells else 0.0
        deepest = float(fill.fill_m[raised].max())
        lines = [f"{cell_count(raised)} raised ({share:.1%} of the mesh), up to {deepest:.2f} m"]
        if surface.catchment is not None:
            inside = surface.within_catchment(raised)
            deepest_inside = float(fill.fill_m[inside].max()) if inside.any() else 0.0
            lines.append(
                f"inside the catchment: {cell_count(inside)}, up to {deepest_inside:.2f} m"
            )
    lines.append(f"sealed on {surface.outlet_note}")
    lines.append(surface.neighbourhood_note)
    lines.append(
        f"after the fill, {fill.stranded_fraction:.2%} of {surface.support_name} "
        "still misses the outlet"
    )
    return lines


def _add_fill(
    ax: Axes,
    polygons: list[np.ndarray],
    fill: DepressionFill,
    *,
    cmap: Colormap,
    vmax: float,
) -> None:
    """Draw the raised cells on a depth scale, with the colorbar that reads it."""
    from matplotlib.collections import PolyCollection

    selected = np.flatnonzero(fill.raised)
    if selected.size == 0:
        return
    collection = PolyCollection(
        [polygons[index] for index in selected],
        array=fill.fill_m[selected],
        cmap=cmap,
        edgecolors="none",
        label=RAISED_LABEL,
        zorder=3,
    )
    values = fill.fill_m[selected]
    collection.set_clim(vmin=0.0, vmax=vmax)
    ax.add_collection(collection)
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()
    clipped = bool(np.nanmax(values) > vmax)
    bar = ax.figure.colorbar(
        collection,
        ax=ax,
        fraction=0.046,
        pad=0.04,
        extend="max" if clipped else "neither",
    )
    bar.set_label("Fill needed before the cell drains (m)")


def _add_flat(
    ax: Axes,
    polygons: list[np.ndarray],
    mask: np.ndarray,
    *,
    color: str,
    label: str,
) -> None:
    """Draw one flat-coloured group of cells, or nothing when it is empty."""
    from matplotlib.collections import PolyCollection

    selected = np.flatnonzero(mask)
    if selected.size == 0:
        return
    ax.add_collection(
        PolyCollection(
            [polygons[index] for index in selected],
            facecolors=color,
            edgecolors="none",
            label=label,
            zorder=2,
        )
    )
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()


__all__ = [
    "DEFAULT_CLIP_PERCENTILE",
    "DRAINS_LABEL",
    "INACTIVE_LABEL",
    "OUTLET_LABEL",
    "RAISED_LABEL",
    "DepressionFill",
    "DepressionMap",
    "depression_fill",
]
