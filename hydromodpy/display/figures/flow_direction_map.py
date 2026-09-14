"""Where every cell of the mesh sends its water, and where it sends none.

A quiver of sixty thousand arrows is a black rectangle, so the direction is
drawn as a flat colour per cell, one of eight octants on a cyclic palette. Read
that way a converging valley shows up as two facing bands meeting on an axis,
and a flat or an artefact shows up as speckle, both at a glance and neither
readable from arrows at that size. The arrows are still there, on a coarse
spatial subsample the caller controls, and they carry the sense of the flow on
a greyscale print, where a cyclic colour cannot: any lightness ramp assigns the
same grey to two of the eight bearings.

The octant is derived from geometry, not from a pointer table. This figure
reads the steepest-descent receiver graph of
:mod:`hydromodpy.core.field_routing` and takes the vector from a cell centre to
its receiver's centre, so it says the same thing on a Voronoi dual as on a
structured grid. In particular it is NOT a whitebox D8 pointer: this repository
uses whitebox's convention rather than ESRI's
(``hydromodpy/spatial/geographic/core/d8.py``), and a reader who assumes a
pointer code is being decoded here would look for the wrong bug.

A cell with no receiver is drawn as such rather than as an arrow of zero
length: it is a pit the descent dies in, or the outlet the catchment closes on,
and the two are told apart on the page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

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

    from hydromodpy.results.run import Run

OCTANT_NAMES: tuple[str, ...] = ("E", "NE", "N", "NW", "W", "SW", "S", "SE")
"""The eight bearings, counter-clockwise from east, as octant ``k`` at ``45k``."""

_CYCLIC_CMAP = "twilight"
"""The sanctioned cyclic palette: a bearing wraps around, and so does it.

Sampled at the eight octants it stays perceptually even in colour. It cannot
stay separable in greyscale, and no palette can: a bearing is cyclic and a
lightness ramp is not, so any of them prints two opposite-ish octants as the
same grey. That is what the arrow layer is for, and why it is on by default.
"""

_PIT_FACE = "#FFFFFF"
"""White under a hatch: a texture, because no flat hue is free here.

The eight octants run white to blue to black to red and back, so a dead end
drawn as one more flat colour can always be approached by one of them: the
sand of the high-contrast triplet lands within 0.04 relative luminance of
octant SE, and in the same warm hue family. The house answer to a state that
has to be told from a whole ramp at once is the one
``downslope_distance_map`` uses for its unreachable cells: white fill, hatch,
dark edge. That is a texture, and no colour on the circle carries one.
"""

_PIT_EDGE = "#111111"
_PIT_HATCH = "xxx"
_INACTIVE_FACE = "#EDEDED"

_CONTOUR_HALO = "#FFFFFF"
_CONTOUR_LINE = "#1A1A1A"
"""The two passes the catchment outline is drawn in, halo first.

A cyclic palette spans the whole lightness range, so no single grey clears a
3:1 contrast against all eight octants at once: over octant W the outline
would sit at 1.6:1. The white halo carries the line over the dark octants and
the dark line carries it over the light ones, so one of the two always reads.
"""

NO_RECEIVER_LABEL = "no receiver"
INACTIVE_LABEL = "no elevation"
OUTLET_LABEL = "outlet the catchment closes on"

_ARROW_COLOR = "#101010"
_ARROW_EDGE = "#FFFFFF"
_COMPASS_EDGE = "#606060"
_COMPASS_GROUND = "#F0F0F0"
"""What a hollow wedge shows through, so an empty bearing reads as empty.

Octant E is a near-white lavender. On a white rose it prints the same as an
unpainted wedge, which is the one distinction the rose now has to make.
"""

DEFAULT_ARROW_BINS = 24
"""Arrows across the widest side of the domain. Zero draws none."""


@register
class FlowDirectionMap(BaseFigure):
    """Steepest-descent receiver direction of every cell of the mesh.

    Built from the run alone: the persisted model top, the neighbour graph over
    the mesh faces, and the centre-to-centre vector to each cell's receiver.
    Any backend that persists a mesh top draws the same map, and no calibrated
    parameter enters it.
    """

    spec = FigureSpec(
        name="flow_direction_map",
        title="Flow direction",
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
        arrow_bins: int = DEFAULT_ARROW_BINS,
        **_,
    ) -> Axes:
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        bins = _checked_bins(arrow_bins)
        surface = routing_surface_from_run(sim, diagonal_neighbors=diagonal_neighbors)
        polygons = face_polygons(sim)
        if len(polygons) != surface.n_cells:
            raise ValueError(
                f"the mesh draws {len(polygons)} faces and the routing surface holds "
                f"{surface.n_cells} cells."
            )

        graph = surface.downhill_graph()
        receiver = np.asarray(graph.downstream, dtype=int)
        routed = receiver >= 0
        delta = _receiver_vectors(surface.centroids, receiver, routed)
        octant = _octant_of(delta, routed)
        colors = octant_colors()

        bearings = [octant == index for index in range(len(OCTANT_NAMES))]
        for index, name in enumerate(OCTANT_NAMES):
            _add_layer(ax, polygons, bearings[index], color=colors[index], label=name)
        counts = tuple(int(mask.sum()) for mask in bearings)

        dead_end = surface.active & (octant < 0)
        _add_layer(
            ax,
            polygons,
            dead_end,
            color=_PIT_FACE,
            label=NO_RECEIVER_LABEL,
            edgecolor=_PIT_EDGE,
            hatch=_PIT_HATCH,
        )
        _add_layer(ax, polygons, ~surface.active, color=_INACTIVE_FACE, label=INACTIVE_LABEL)

        drawn_arrows = _draw_arrows(ax, surface.centroids, delta, routed, bins)
        _draw_compass(ax, colors, counts)
        outlet_x, outlet_y = surface.centroids[surface.outlet]
        outlet_marker = {
            "marker": "*",
            "markerfacecolor": "#FFFFFF",
            "markeredgecolor": _PIT_EDGE,
            "linestyle": "none",
        }
        ax.plot([outlet_x], [outlet_y], markersize=13, zorder=8, **outlet_marker)

        style_map_axes(ax)
        _draw_watershed_contour(ax, sim)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")
        handles: list[Patch | Line2D] = [
            Patch(
                facecolor=_PIT_FACE,
                edgecolor=_PIT_EDGE,
                hatch=_PIT_HATCH,
                label=f"{NO_RECEIVER_LABEL}: pit or outlet ({cell_count(dead_end)})",
            ),
            Line2D([0], [0], markersize=11, label=OUTLET_LABEL, **outlet_marker),
        ]
        if not surface.active.all():
            handles.append(
                Patch(
                    facecolor=_INACTIVE_FACE,
                    edgecolor="none",
                    label=f"{INACTIVE_LABEL} ({cell_count(~surface.active)})",
                )
            )
        ax.legend(handles=handles, loc="upper left", fontsize=8.5, framealpha=0.9)
        annotate_note(ax, "\n".join(_notes(surface, dead_end, counts, drawn_arrows, bins)))
        return ax


def octant_colors() -> tuple[str, ...]:
    """Return one colour per octant, sampled around the cyclic palette."""
    import matplotlib as mpl
    from matplotlib.colors import to_hex

    ramp = mpl.colormaps[_CYCLIC_CMAP]
    return tuple(to_hex(ramp(index / len(OCTANT_NAMES))) for index in range(len(OCTANT_NAMES)))


def _receiver_vectors(
    centroids: np.ndarray,
    receiver: np.ndarray,
    routed: np.ndarray,
) -> np.ndarray:
    """Return the (n_cells, 2) vector from each cell centre to its receiver's."""
    return centroids[np.where(routed, receiver, 0)] - centroids


def _octant_of(delta: np.ndarray, routed: np.ndarray) -> np.ndarray:
    """Return the octant of the centre-to-centre vector, ``-1`` without one."""
    bearing = np.degrees(np.arctan2(delta[:, 1], delta[:, 0]))
    octant = np.mod(np.rint(bearing / (360.0 / len(OCTANT_NAMES))), len(OCTANT_NAMES))
    return np.where(routed & np.isfinite(bearing), octant, -1).astype("int64")


def _checked_bins(arrow_bins: int) -> int:
    """Return the arrow density, checked for a usable subsample."""
    bins = int(arrow_bins)
    if bins < 0:
        raise ValueError(f"arrow_bins counts arrows across the domain, got {bins}.")
    return bins


def _draw_arrows(
    ax: Axes,
    centroids: np.ndarray,
    delta: np.ndarray,
    routed: np.ndarray,
    bins: int,
) -> int:
    """Draw one arrow per occupied bin; return how many were drawn.

    The arrow is the MEAN unit direction of the cells of its bin, drawn
    unnormalised: a bin whose cells all agree gets a full-length arrow, and one
    where they disagree gets a stub. A flat or a badly conditioned patch is
    exactly where they disagree, so the length is a reading and not decoration.
    """
    if bins == 0 or not routed.any():
        return 0
    length = np.hypot(delta[:, 0], delta[:, 1])
    usable = routed & np.isfinite(length) & (length > 0.0)
    if not usable.any():
        return 0

    points = centroids[usable]
    unit = delta[usable] / length[usable, None]
    origin = points.min(axis=0)
    span = float(np.max(points.max(axis=0) - origin))
    if span <= 0.0:
        return 0
    step = span / bins
    index = np.minimum((points - origin) / step, bins - 1).astype("int64")
    key = index[:, 1] * bins + index[:, 0]

    counts = np.bincount(key, minlength=bins * bins).astype("float64")
    occupied = counts > 0
    if not occupied.any():
        return 0
    mean = [
        np.bincount(key, weights=column, minlength=bins * bins)[occupied] / counts[occupied]
        for column in (points[:, 0], points[:, 1], unit[:, 0], unit[:, 1])
    ]
    ax.quiver(
        mean[0],
        mean[1],
        mean[2],
        mean[3],
        angles="xy",
        scale_units="xy",
        scale=1.0 / (0.85 * step),
        width=0.004,
        pivot="mid",
        color=_ARROW_COLOR,
        edgecolor=_ARROW_EDGE,
        linewidth=0.35,
        zorder=7,
    )
    return int(occupied.sum())


def _draw_compass(ax: Axes, colors: tuple[str, ...], counts: tuple[int, ...]) -> None:
    """Draw the octant palette as a compass rose, each colour at its bearing.

    A column of eight swatches would make a reader count entries to tell
    north-east from south-west. Placing the colour where it points removes the
    counting: the legend has the shape of the answer.

    A bearing no cell takes is drawn hollow. On a shared-edge graph the four
    diagonals are empty by construction, and a rose that paints them anyway
    tells the reader the map uses eight bearings when it uses four.
    """
    from matplotlib.patches import Wedge

    span = 360.0 / len(OCTANT_NAMES)
    rose = ax.inset_axes((0.775, 0.735, 0.215, 0.215), zorder=9)
    rose.set_aspect("equal")
    rose.set_xlim(-1.75, 1.75)
    rose.set_ylim(-1.6, 1.9)
    rose.set_xticks([])
    rose.set_yticks([])
    for spine in rose.spines.values():
        spine.set_color(_COMPASS_EDGE)
        spine.set_linewidth(0.5)
    rose.patch.set_facecolor(_COMPASS_GROUND)
    rose.patch.set_alpha(0.95)
    for index, name in enumerate(OCTANT_NAMES):
        bearing = index * span
        empty = counts[index] == 0
        rose.add_patch(
            Wedge(
                (0.0, 0.0),
                1.0,
                bearing - span / 2.0,
                bearing + span / 2.0,
                facecolor="none" if empty else colors[index],
                edgecolor=_COMPASS_EDGE,
                linewidth=0.4,
                linestyle="--" if empty else "solid",
            )
        )
        rose.text(
            1.28 * np.cos(np.radians(bearing)),
            1.28 * np.sin(np.radians(bearing)),
            name,
            ha="center",
            va="center",
            fontsize=7.0,
        )
    rose.text(0.0, 1.78, "flow direction", ha="center", va="top", fontsize=7.5)


def _notes(
    surface: RoutingSurface,
    dead_end: np.ndarray,
    counts: tuple[int, ...],
    arrows: int,
    bins: int,
) -> list[str]:
    """Return the lines a reader needs to know which map is on the page."""
    inside = int(surface.within_catchment(dead_end).sum())
    lines = [
        surface.neighbourhood_note,
        _bearing_note(counts),
        f"no receiver: {cell_count(dead_end)}, {inside} of them in {surface.support_name}",
        surface.outlet_note,
    ]
    if arrows:
        lines.append(
            f"{arrows} arrows on a {bins} x {bins} subsample, shorter where the bin disagrees"
        )
    return lines


def _bearing_note(counts: tuple[int, ...]) -> str:
    """Return the line saying how many cells took each bearing.

    How many of the eight the surface actually uses is the first reading of
    the map, and it is not in the colours: four flat bands and four absences
    look the same as eight bands until the counts are written down.
    """
    taken = [f"{name} {count:,}" for name, count in zip(OCTANT_NAMES, counts, strict=True) if count]
    empty = [name for name, count in zip(OCTANT_NAMES, counts, strict=True) if not count]
    if not taken:
        return "no cell carries a bearing"
    line = "bearings: " + ", ".join(taken)
    return line if not empty else f"{line}; none on {', '.join(empty)}"


def _draw_watershed_contour(ax: Axes, sim: Run) -> None:
    """Draw the catchment outline as a white halo under a dark line.

    One line cannot do it here. The octants are sampled around a cyclic
    palette that runs from near white to near black, so a single grey clears
    3:1 against some of them and 1.6:1 against the others: over the darkest
    octant a dark outline disappears, over the lightest one a pale outline
    does. Two passes leave one of the two readable everywhere.
    """
    overlay_watershed_contour(ax, sim, color=_CONTOUR_HALO, linewidth=2.6, alpha=0.9)
    overlay_watershed_contour(ax, sim, color=_CONTOUR_LINE, linewidth=0.9, alpha=0.95)


def _add_layer(
    ax: Axes,
    polygons: list[np.ndarray],
    mask: np.ndarray,
    *,
    color: str,
    label: str,
    edgecolor: str = "none",
    hatch: str | None = None,
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
            edgecolors=edgecolor,
            linewidths=0.3 if hatch else 0.0,
            hatch=hatch,
            label=label,
            zorder=2,
        )
    )
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()


__all__ = [
    "DEFAULT_ARROW_BINS",
    "INACTIVE_LABEL",
    "NO_RECEIVER_LABEL",
    "OCTANT_NAMES",
    "OUTLET_LABEL",
    "FlowDirectionMap",
    "octant_colors",
]
