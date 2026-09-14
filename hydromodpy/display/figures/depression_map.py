"""Where the routing surface is pitted, and what it cannot deliver to the outlet.

Two questions look alike on a mesh and are not the same one.

A cell sits IN A CLOSED DEPRESSION when it cannot get out of the domain at all:
no descent from it reaches the edge of the active mesh. That is what a priority
flood seeded on that edge raises, and it is what "is the surface I route on
still pitted" asks. The outlet is not one of the seeds, because sealing a cell
is a choice about the catchment and a depression is a property of the surface:
on the Nancon the outlet is interior and needs 4.07 m of fill before it spills
out of the mesh, so it is itself in one.

A cell CANNOT REACH THE CATCHMENT OUTLET when it does get out, somewhere else.
On a buffered box most of the mesh belongs to neighbouring basins; they drain
perfectly well, and the stream criterion floods them to their spill level
anyway, because it seeds one cell and a distance to that cell is undefined
until every path ends there. That set is the criterion's own support, and worth
seeing under its own name.

The default reading is the first. ``shows="unreachable"`` gives the second, and
either way the note carries both counts: on the Nancon mesh the first is three
thousand cells and the second eighteen thousand, and a reader shown the second
under the name of the first concludes that the conditioning failed.
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
from hydromodpy.display.figures._stream_comparison import cell_count, map_legend
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

_LEGEND_SWATCH = 0.62
"""Where the legend patch samples the ramp: dark enough to read, not the end."""

_RAISED_WIDTH_PT = 0.5
"""Half a point of outline, in each cell's own colour.

The subject of this map is a scatter of one-cell footprints over sixty
thousand cells of background. At page size a single cell is a few pixels, and
a lone pit disappears into the antialiasing of the grey behind it. Stroking
each raised cell in its own colour widens it by half a point and adds nothing
else: no depth is redrawn, no boundary is invented.
"""

INACTIVE_LABEL = "no elevation"

DEPRESSIONS = "depressions"
UNREACHABLE = "unreachable"

DEFAULT_CLIP_PERCENTILE = 99.0
"""Percentile the colour scale stops at, so one deep sink does not flatten it."""


@dataclass(frozen=True, slots=True)
class Reading:
    """What one of the two questions puts on the page."""

    name: str
    title: str
    raised_label: str
    drains_label: str
    outlet_label: str
    scale_label: str


READINGS: dict[str, Reading] = {
    DEPRESSIONS: Reading(
        name=DEPRESSIONS,
        title="Closed depressions of the routing surface",
        raised_label="in a closed depression",
        drains_label="gets out of the domain as it stands",
        outlet_label="catchment outlet, no escape of the surface",
        scale_label="Fill the depression needs before it spills (m)",
    ),
    UNREACHABLE: Reading(
        name=UNREACHABLE,
        title="What cannot reach the catchment outlet",
        raised_label="cannot reach the outlet",
        drains_label="reaches the outlet as it stands",
        outlet_label="outlet the flood was sealed on",
        scale_label="Fill needed before the cell reaches the outlet (m)",
    ),
}


def reading_for(shows: str) -> Reading:
    """Return the labels of one reading, or refuse a name that has none."""
    try:
        return READINGS[str(shows)]
    except KeyError:
        raise ValueError(
            f"shows must be one of {', '.join(sorted(READINGS))}, got {shows!r}."
        ) from None


@dataclass(frozen=True, slots=True)
class Flood:
    """One priority flood of a surface, and what it had to raise."""

    seeds: np.ndarray
    """(n_cells,) bool: the cells the flood was allowed to leave through."""

    filled: np.ndarray
    """(n_cells,) elevations after the flood, NaN off the active mesh."""

    fill_m: np.ndarray
    """(n_cells,) filled minus persisted, in metres, NaN off the active mesh."""

    raised: np.ndarray
    """(n_cells,) bool: cells the flood had to lift onto a spill level."""

    @property
    def deepest_m(self) -> float:
        """The largest fill applied, zero when the flood raised nothing."""
        return float(self.fill_m[self.raised].max()) if self.raised.any() else 0.0


@dataclass(frozen=True, slots=True)
class DepressionFill:
    """Both floods of one routing surface, and what separates them."""

    surface: RoutingSurface

    closed: Flood
    """Seeded on every escape: the cells that cannot get out of the domain."""

    to_outlet: Flood
    """Seeded on the outlet alone: what the stream criterion floods."""

    stranded_fraction: float
    """Share of the support whose descent still misses the sealed outlet.

    Zero is the only healthy answer: after a flood seeded on one cell, every
    path of the support ends there by construction. Anything else means the
    surface the flood conditioned is not the one the descent walks, which is
    what a mismatched neighbourhood produces.
    """

    @property
    def cut_off(self) -> np.ndarray:
        """(n_cells,) bool: raised by the outlet flood, in no depression.

        These cells drain, and not to this outlet. They are the whole reason
        the two readings must not share a name: on the Nancon they are fifteen
        thousand of the eighteen thousand the criterion's flood raises.
        """
        return self.to_outlet.raised & ~self.closed.raised

    @property
    def pitted_and_unreachable(self) -> np.ndarray:
        """(n_cells,) bool: raised by both floods, so genuinely in a pit."""
        return self.to_outlet.raised & self.closed.raised

    def flood_for(self, reading: Reading) -> Flood:
        """Return the flood one reading draws."""
        return self.closed if reading.name == DEPRESSIONS else self.to_outlet


def depression_fill(surface: RoutingSurface) -> DepressionFill:
    """Flood ``surface`` twice, and measure what the two answers do not share.

    Once from every escape, which raises the closed depressions and nothing
    else, and once from the outlet alone, which is what the stream criterion
    does before it measures a distance to that single cell.

    Both floods and the descent that checks the second walk the SAME neighbour
    graph. Fed the eight-neighbour graph while the descent reads the
    four-neighbour one, a flood leaves every filled cell spilling over a
    diagonal the descent cannot take, and almost the whole catchment stops
    reaching the outlet. The metric below re-derives its adjacency from
    ``diagonal_neighbors`` through the two builders the surface already used,
    so the pair cannot drift.
    """
    active = surface.active
    original = np.where(active, surface.topography, np.nan)
    closed = _flood(surface, original, surface.escape_mask())
    to_outlet = _flood(surface, original, surface.outlet_mask())

    metric = build_downslope_metric(
        to_outlet.filled,
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
        closed=closed,
        to_outlet=to_outlet,
        stranded_fraction=stranded,
    )


def _flood(surface: RoutingSurface, original: np.ndarray, seeds: np.ndarray) -> Flood:
    """Run one priority flood of the surface over the graph it routes on."""
    report = fill_depressions_on_graph(original, surface.adjacency, seeds)
    fill_m = report.surface - original
    return Flood(
        seeds=seeds,
        filled=report.surface,
        fill_m=fill_m,
        raised=surface.active & (fill_m > DEFAULT_EPSILON_M / 2.0),
    )


@register
class DepressionMap(BaseFigure):
    """Cells of the mesh top that cannot get out, and the fill each one needs.

    A depression here is a cell no descent leaves the domain from, over the
    same neighbour graph the stream criterion measures its distances on. Not to
    be confused with ``conditioning_impact_map``, which shows what the
    geographic step did to the DEM before the mesh existed: this one is what is
    LEFT once that DEM has been resampled onto the mesh, because a raster
    conditioned on its own grid grows new pits under a different neighbourhood.

    ``shows="unreachable"`` swaps the subject for the cells the criterion's own
    flood raises, which is a larger set and a different statement: those cells
    mostly drain, to a neighbouring basin rather than to this outlet.
    """

    spec = FigureSpec(
        name="depression_map",
        title="Closed depressions of the routing surface",
        kind="spatial",
        default_figsize=(7.5, 6.6),
    )
    """The page, taller than a plain map by what the key needs under it.

    The key and the five-line note take 1.2 in of the height. Left at the 6.0
    in this figure used to declare, the mesh printed 494 px across against the
    657 it had when the note sat inside the axes, which trades one unreadable
    map for another.
    """

    def unavailable_reason(self, sim: Run) -> str | None:
        """Return why this run carries no surface to route on, or None."""
        return unavailable_reason_for_routing(sim) or super().unavailable_reason(sim)

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        shows: str = DEPRESSIONS,
        diagonal_neighbors: bool = False,
        clip_percentile: float = DEFAULT_CLIP_PERCENTILE,
        cmap: str | None = None,
        **_,
    ) -> Axes:
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        reading = reading_for(shows)
        surface = routing_surface_from_run(sim, diagonal_neighbors=diagonal_neighbors)
        polygons = face_polygons(sim)
        if len(polygons) != surface.n_cells:
            raise ValueError(
                f"the mesh draws {len(polygons)} faces and the routing surface holds "
                f"{surface.n_cells} cells."
            )
        fill = depression_fill(surface)
        flood = fill.flood_for(reading)

        drains = surface.active & ~flood.raised
        _add_flat(ax, polygons, drains, color=_UNRAISED_FACE, label=reading.drains_label)
        _add_flat(ax, polygons, ~surface.active, color=_INACTIVE_FACE, label=INACTIVE_LABEL)
        ramp = get_cmap(cmap or _FILL_CMAP)
        vmax = _color_ceiling(_scaled_fills(surface, flood, reading), clip_percentile)
        _add_fill(ax, polygons, flood, reading, cmap=ramp, vmax=vmax)

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
        ax.set_title(f"{reading.title} - {sim.name or sim.sim_id}")

        handles: list[Patch | Line2D] = []
        if flood.raised.any():
            handles.append(
                Patch(
                    facecolor=ramp(_LEGEND_SWATCH),
                    edgecolor="none",
                    label=f"{reading.raised_label} ({cell_count(flood.raised)})",
                )
            )
        handles.append(
            Patch(
                facecolor=_UNRAISED_FACE,
                edgecolor="none",
                label=f"{reading.drains_label} ({cell_count(drains)})",
            )
        )
        handles.append(Line2D([0], [0], markersize=11, label=reading.outlet_label, **outlet_marker))
        if not surface.active.all():
            handles.append(
                Patch(
                    facecolor=_INACTIVE_FACE,
                    edgecolor="#909090",
                    label=f"{INACTIVE_LABEL} ({cell_count(~surface.active)})",
                )
            )
        map_legend(ax, handles, note="\n".join(_notes(fill, reading)))
        return ax


def _scaled_fills(surface: RoutingSurface, flood: Flood, reading: Reading) -> np.ndarray:
    """Return the fills the colour scale is stretched over.

    The whole mesh for the depressions. That flood raises no neighbouring
    basin, only pits, and a pit outside the catchment is the same object as one
    inside it: on the Nancon the deepest is 11.29 m against 4.87 m inside, and
    three per cent of the drawn cells sit above the ceiling the catchment alone
    would set.

    The catchment alone for the unreachable cells, where the mesh is a buffered
    box holding whole basins the flood has to lift over a ridge. There a
    percentile taken over the whole mesh is set by lobes that are not the
    subject: 31.21 m against 3.97 m inside, with two thirds of the drawn cells
    above the ceiling, and every metre-scale pit of the catchment collapses
    onto the first colour of the ramp.
    """
    if reading.name == DEPRESSIONS or surface.catchment is None:
        return flood.fill_m[flood.raised]
    inside = flood.fill_m[surface.within_catchment(flood.raised)]
    return inside if inside.size else flood.fill_m[flood.raised]


def _color_ceiling(values: np.ndarray, clip_percentile: float) -> float:
    """Return the top of the colour scale, floored so a scale always exists."""
    percentile = float(clip_percentile)
    if not 0.0 < percentile <= 100.0:
        raise ValueError(f"clip_percentile must lie in (0, 100], got {percentile}.")
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return DEFAULT_EPSILON_M
    return max(float(np.percentile(finite, percentile)), DEFAULT_EPSILON_M)


def _notes(fill: DepressionFill, reading: Reading) -> list[str]:
    """Return the lines a reader needs to know which flood is on the page.

    Both readings carry both counts. The figure exists because they were told
    apart nowhere, and a note that only reports the set it drew would let a
    reader carry the same confusion to the next page.
    """
    return _depression_notes(fill) if reading.name == DEPRESSIONS else _unreachable_notes(fill)


def _depression_notes(fill: DepressionFill) -> list[str]:
    """Return the note of the depressions reading, with the other count in it."""
    surface = fill.surface
    closed = fill.closed
    if not closed.raised.any():
        lines = ["no closed depression: every cell of the mesh top gets out as it stands"]
    else:
        share = int(closed.raised.sum()) / surface.n_cells if surface.n_cells else 0.0
        lines = [
            f"{cell_count(closed.raised)} in a closed depression ({share:.1%} of the "
            f"mesh), up to {closed.deepest_m:.2f} m"
        ]
        if surface.catchment is not None:
            inside = surface.within_catchment(closed.raised)
            deepest = float(closed.fill_m[inside].max()) if inside.any() else 0.0
            lines.append(f"inside the catchment: {cell_count(inside)}, up to {deepest:.2f} m")
    lines.append(
        f'out elsewhere but not to this outlet: {cell_count(fill.cut_off)} (shows="{UNREACHABLE}")'
    )
    lines.append(surface.escape_note)
    lines.append(surface.neighbourhood_note)
    return lines


def _unreachable_notes(fill: DepressionFill) -> list[str]:
    """Return the note of the unreachable reading, with the other count in it.

    The depression count of the two readings need not match, and saying which
    of the two is on the page is the point: a cell can sit in a closed
    depression and still descend to the sealed outlet, the outlet itself first
    of all. On the Nancon the criterion's flood covers 3 008 of the 3 023 the
    surface holds.
    """
    surface = fill.surface
    flood = fill.to_outlet
    if not flood.raised.any():
        lines = ["every cell of the mesh top already descends to the sealed outlet"]
    else:
        share = int(flood.raised.sum()) / surface.n_cells if surface.n_cells else 0.0
        lines = [
            f"{cell_count(flood.raised)} cannot reach the outlet ({share:.1%} of the "
            f"mesh), up to {flood.deepest_m:.2f} m"
        ]
    lines.append(
        f"of them, in a closed depression: {int(fill.pitted_and_unreachable.sum())} of the "
        f"{int(fill.closed.raised.sum())} the mesh holds; out elsewhere: "
        f"{cell_count(fill.cut_off)}"
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
    flood: Flood,
    reading: Reading,
    *,
    cmap: Colormap,
    vmax: float,
) -> None:
    """Draw the raised cells on a depth scale, with the colorbar that reads it."""
    from matplotlib.collections import PolyCollection

    selected = np.flatnonzero(flood.raised)
    if selected.size == 0:
        return
    values = flood.fill_m[selected]
    collection = PolyCollection(
        [polygons[index] for index in selected],
        array=values,
        cmap=cmap,
        edgecolors="face",
        linewidths=_RAISED_WIDTH_PT,
        label=reading.raised_label,
        zorder=3,
    )
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
    bar.set_label(reading.scale_label)


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
    "DEPRESSIONS",
    "INACTIVE_LABEL",
    "READINGS",
    "UNREACHABLE",
    "DepressionFill",
    "DepressionMap",
    "Flood",
    "Reading",
    "depression_fill",
    "reading_for",
]
