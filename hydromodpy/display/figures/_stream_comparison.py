"""What the stream-network maps share: one comparison, one palette, one frame.

Four maps read the same catchment from four angles: where the two networks
agree, how far apart they run, what the pair looks like on the relief, and
which cells the routed flux keeps active. They read the partition through one
function and colour it with one palette, because two derivations of one
partition is how a map comes to disagree with the map printed beside it, and
with the numbers a trial published.

They also share a frame. Everything these maps are read for is a one-cell-wide
line drawn over a mesh that is mostly not it: on the Nancon, 1 173 simulated
cells over 60 395. A map whose subject covers two percent of its area has to
earn that area back, so the frame, the weight a cell is drawn with and the
place the counts are written live here rather than four times over.

Nothing here decides anything: the partition comes from
:mod:`hydromodpy.results.derive.stream_network`, which rebuilds it through the
construction the calibration criterion scores.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.results.derive.stream_network import (
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
    AGREEMENT_VALID,
    NetworkComparison,
    agreement_label,
    network_comparison_from_run,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.collections import PolyCollection
    from matplotlib.legend import Legend

    from hydromodpy.results.run import Run

GROUND_COLOR = "#EDEDED"
"""The cells a map measures nothing on: the ground the subject is drawn over.

One tone across the whole set, so a reader moving from one map to the next
reads the same grey as the same statement: nothing was measured here.
"""

AGREEMENT_COLORS: dict[int, str] = {
    AGREEMENT_NEITHER: GROUND_COLOR,
    AGREEMENT_VALID: HIGH_CONTRAST_TRIPLET[0],
    AGREEMENT_EXCESS: HIGH_CONTRAST_TRIPLET[1],
    AGREEMENT_MISSING: HIGH_CONTRAST_TRIPLET[2],
}
"""One colour per agreement class, the darkest for the agreement itself.

The three lightnesses sit far enough apart for the classes to survive a
greyscale print and every common colour-vision deficiency. The cells no network
claims cover most of a catchment and take a light grey: drawn in anything
stronger they would carry the eye instead of the three classes the maps exist
for.
"""

CRITERION_NAMES: dict[int, str] = {
    AGREEMENT_VALID: "valid",
    AGREEMENT_EXCESS: "excess",
    AGREEMENT_MISSING: "missing",
}
"""The name a trial publishes each class under, as ``n_valid`` and its two peers."""

MapExtentName = Literal["catchment", "mesh"]
"""The two frames a stream map can be drawn in, under the name a TOML asks for."""

CELL_WEIGHT_PT = 0.7
"""Stroke laid around a drawn cell, in points.

A stream cell is one cell wide. On a 50 m mesh printed seven inches across
that is four pixels, and a fifth of a millimetre on paper: the line the map
exists to show breaks up under its own rasterisation. A map carrying one
subject strokes it in its own colour; a map carrying several that share the
line strokes a casing over their union once, or each of them widens over the
one beside it. It is a rendering width, not a measurement: every count on the
page comes from the mask, never from the ink.
"""

CASING_COLOR = "#4D4D4D"
"""The tone a network is cased in when it is drawn over the light ground.

A casing is how a one-cell line gains weight without any class stealing it
from the class beside it: the union of the drawn cells carries the stroke
once, and each class is then laid flat inside it. Read straight, the rim says
which cells the map measured on at all, before any colour of the scale does.
"""

MAP_MARGIN_RATIO = 0.04
"""Blank margin kept around a cropped frame, as a fraction of its longest side."""

_LEGEND_FONT_SIZE = 9.0
_LEGEND_MIN_FONT_SIZE = 6.0
_LEGEND_REFERENCE_WIDTH_IN = 7.0
"""The page width these maps declare, and what the key is sized against.

A key under the map cannot shrink on its own: drawn at full size on half a
page it takes the whole figure and leaves the map a stamp. Scaling it with the
page keeps the composition when a caller asks for a smaller one.
"""

_NOTE_BOX = {"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"}
"""The box every note of the gallery sits in."""

_MISSING_FEATURE = (KeyError, ValueError, FileNotFoundError, RuntimeError)
"""What a run raises when a feature it never wrote is asked for.

``AttributeError`` is deliberately not in it: a run answering neither ``mesh``
nor ``geographic`` is a coding error on the caller's side, and swallowing it
here would turn it into a silently degraded figure.
"""

_WATERSHED_FEATURE = "watershed"


def comparison_from_run(
    sim: Run,
    *,
    tau_specific_ratio: float | None = None,
    diagonal_neighbors: bool | None = None,
    timestep: int | None = None,
) -> NetworkComparison:
    """Rebuild the stream comparison of one run, at the knobs a caller named.

    A knob left as None keeps the default of the criterion rather than
    repeating it here: a threshold declared twice is a map that drifts from the
    numbers it illustrates.
    """
    named = {
        "tau_specific_ratio": tau_specific_ratio,
        "diagonal_neighbors": diagonal_neighbors,
        "timestep": timestep,
    }
    return network_comparison_from_run(
        sim, **{key: value for key, value in named.items() if value is not None}
    )


def class_label(value: int) -> str:
    """Return the legend label of one agreement class, under both its names."""
    name = CRITERION_NAMES.get(int(value))
    label = agreement_label(value)
    return label if name is None else f"{name}: {label}"


def threshold_note(comparison: NetworkComparison) -> str:
    """Return the line naming the threshold the partition was cut at.

    The three classes move with it, so a map that does not carry it leaves a
    reader guessing which of several partitions is on the page.
    """
    ratio = comparison.tau_specific_ratio
    if ratio == 0.0:
        return "seepage threshold: none (tau = 0), every releasing cell is a stream"
    return f"seepage threshold: tau = {ratio:g} of the mean recharge a cell receives"


def annotate_note(ax: Axes, text: str) -> None:
    """Put one note at the foot of a map, in the box the gallery uses."""
    ax.annotate(
        text,
        xy=(0.5, 0.03),
        xycoords="axes fraction",
        ha="center",
        va="bottom",
        fontsize=9,
        bbox=_NOTE_BOX,
        zorder=10,
    )


def map_legend(ax: Axes, handles: Sequence, *, note: str, ncols: int = 2) -> Legend:
    """Put the key and the note in one box under the map.

    Both used to sit inside the axes, the key wherever matplotlib found room
    and the note pinned to the foot; on a real catchment they landed on each
    other and the last class was read through the note. Under the map neither
    can cover the subject nor the other, and the counts a reader came for are
    on the same line as the colour they belong to.

    The box belongs to the figure rather than to the axes, because that is
    what the layout engine can reserve room for: anchored below the axes
    instead, it prints over the label of the x axis. Only a constrained layout
    reserves that room, and ``render`` is public: a caller handing it a plain
    axes would get the key printed over the map, so the figure gets the engine
    here rather than only in :meth:`BaseFigure.plot`.
    """
    figure = ax.figure
    if figure.get_layout_engine() is None:
        figure.set_layout_engine("constrained")
    size = _legend_font_size(ax)
    legend = figure.legend(
        handles=list(handles),
        title=note,
        loc="outside lower center",
        ncols=ncols,
        fontsize=size,
        title_fontsize=size,
        framealpha=0.95,
    )
    legend.set_alignment("left")
    return legend


def _legend_font_size(ax: Axes) -> float:
    """Return the type size of the key, sized against the page it is drawn on."""
    width = float(ax.figure.get_size_inches()[0])
    scaled = _LEGEND_FONT_SIZE * width / _LEGEND_REFERENCE_WIDTH_IN
    return float(min(max(scaled, _LEGEND_MIN_FONT_SIZE), _LEGEND_FONT_SIZE))


def cell_count(mask: np.ndarray) -> str:
    """Return the size of one group of cells, written for a legend entry."""
    count = int(np.asarray(mask, dtype=bool).sum())
    return f"{count} cell" if count == 1 else f"{count} cells"


def checked_cells(values: np.ndarray, n_faces: int, label: str) -> np.ndarray:
    """Return one per-cell array, checked against the mesh the figure draws.

    The comparison is built on the persisted topography and the figure draws
    the persisted connectivity; a run whose two disagree would otherwise paint
    one cell with the class of another.
    """
    array = np.asarray(values).reshape(-1)
    if array.size != n_faces:
        raise ValueError(f"the {label} holds {array.size} cells, the mesh holds {n_faces}.")
    return array


def select_cells(polygons: Sequence[np.ndarray], mask: np.ndarray) -> list[np.ndarray]:
    """Return the polygons of the cells one mask holds, in index order."""
    return [polygons[index] for index in np.flatnonzero(np.asarray(mask, dtype=bool))]


def draw_cells(
    ax: Axes,
    polygons: Sequence[np.ndarray],
    *,
    color: str,
    label: str,
    zorder: float,
    weight_pt: float = CELL_WEIGHT_PT,
    edgecolor: str | None = None,
    hatch: str | None = None,
) -> PolyCollection | None:
    """Draw one flat-coloured group of cells, or nothing when it is empty.

    ``edgecolor`` defaults to the fill, which turns ``weight_pt`` into the
    weight the group is drawn with rather than an outline around it.
    """
    from matplotlib.collections import PolyCollection

    if len(polygons) == 0:
        return None
    collection = PolyCollection(
        list(polygons),
        facecolors=color,
        edgecolors=color if edgecolor is None else edgecolor,
        linewidths=weight_pt,
        hatch=hatch,
        label=label,
        zorder=zorder,
    )
    ax.add_collection(collection)
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()
    return collection


@dataclass(frozen=True, slots=True)
class MapExtent:
    """The window a map is drawn in, and which cells it leaves off the page."""

    bounds: tuple[float, float, float, float]
    """``(xmin, xmax, ymin, ymax)`` of the window, in mesh coordinates."""

    inside: np.ndarray
    """(n_cells,) bool: cells whose centre falls inside the window."""

    name: str
    """What the window is, written for a note."""

    def apply(self, ax: Axes) -> None:
        """Frame ``ax`` on this window, and shrink the axes box onto it.

        Called last, after every ``draw_cells`` has autoscaled. The box, not
        the data, absorbs the equal aspect: a datalim-adjustable axes keeps
        the crop honest by widening it back to the shape of the page, which on
        a catchment taller than it is wide gives back most of the mesh the
        crop was asked to drop.
        """
        xmin, xmax, ymin, ymax = self.bounds
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)

    def outside_note(self, mask: np.ndarray, what: str) -> str | None:
        """Say how much of ``mask`` this window leaves off the page, or None.

        A crop that hides part of the subject has to say so: a reader counting
        stream cells on the page otherwise reads a number the legend
        contradicts.
        """
        hidden = np.asarray(mask, dtype=bool) & ~self.inside
        if not hidden.any():
            return None
        return f"outside this frame: {cell_count(hidden)} of {what}"


def map_extent(
    sim: Run,
    polygons: Sequence[np.ndarray],
    *,
    extent: MapExtentName = "catchment",
) -> MapExtent:
    """Return the window one map is framed on.

    ``catchment`` crops to the delineated watershed, which is where every
    class of the criterion lives; ``mesh`` keeps the whole modelled domain, for
    a reader checking what the model does outside the basin it was scored on.
    A run carrying no delineation falls back to the mesh and says so, rather
    than inventing a box.
    """
    if extent not in ("catchment", "mesh"):
        raise ValueError(f"extent must be 'catchment' or 'mesh', got {extent!r}.")
    centres = np.asarray([polygon.mean(axis=0)[:2] for polygon in polygons], dtype="float64")
    corners = np.concatenate([np.asarray(polygon)[:, :2] for polygon in polygons])
    mesh_bounds = (
        float(corners[:, 0].min()),
        float(corners[:, 0].max()),
        float(corners[:, 1].min()),
        float(corners[:, 1].max()),
    )
    if extent == "mesh":
        return _whole_mesh(mesh_bounds, centres.shape[0], "the whole mesh")

    bounds = _catchment_bounds(sim)
    if bounds is None:
        return _whole_mesh(
            mesh_bounds,
            centres.shape[0],
            "the whole mesh, this run declaring no catchment to crop to",
        )
    bounds = _padded(bounds, mesh_bounds)
    if bounds is None:
        return _whole_mesh(
            mesh_bounds,
            centres.shape[0],
            "the whole mesh, the declared catchment falling outside it",
        )
    xmin, xmax, ymin, ymax = bounds
    inside = (
        (centres[:, 0] >= xmin)
        & (centres[:, 0] <= xmax)
        & (centres[:, 1] >= ymin)
        & (centres[:, 1] <= ymax)
    )
    return MapExtent(bounds=bounds, inside=inside, name="the delineated catchment")


def _whole_mesh(bounds: tuple[float, float, float, float], n_cells: int, name: str) -> MapExtent:
    """Return the window that holds every cell of the mesh."""
    return MapExtent(bounds=bounds, inside=np.ones(n_cells, dtype=bool), name=name)


def _catchment_bounds(sim: Run) -> tuple[float, float, float, float] | None:
    """Return the bounding box of the delineated catchment, in mesh coordinates."""
    try:
        watershed = sim.geographic(_WATERSHED_FEATURE)
    except _MISSING_FEATURE:
        return None
    if watershed is None or watershed.empty:
        return None
    mesh_crs = getattr(sim.mesh, "crs", None)
    if mesh_crs and watershed.crs is not None and str(watershed.crs) != str(mesh_crs):
        watershed = watershed.to_crs(mesh_crs)
    xmin, ymin, xmax, ymax = (float(value) for value in watershed.total_bounds)
    if not np.isfinite([xmin, xmax, ymin, ymax]).all() or xmax <= xmin or ymax <= ymin:
        return None
    return (xmin, xmax, ymin, ymax)


def _padded(
    bounds: tuple[float, float, float, float],
    mesh_bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    """Return ``bounds`` widened by the map margin and clipped to the mesh."""
    xmin, xmax, ymin, ymax = bounds
    margin = MAP_MARGIN_RATIO * max(xmax - xmin, ymax - ymin)
    window = (
        max(xmin - margin, mesh_bounds[0]),
        min(xmax + margin, mesh_bounds[1]),
        max(ymin - margin, mesh_bounds[2]),
        min(ymax + margin, mesh_bounds[3]),
    )
    if window[1] <= window[0] or window[3] <= window[2]:
        return None
    return window


__all__ = (
    "AGREEMENT_COLORS",
    "CASING_COLOR",
    "CELL_WEIGHT_PT",
    "CRITERION_NAMES",
    "GROUND_COLOR",
    "MapExtent",
    "MapExtentName",
    "annotate_note",
    "cell_count",
    "checked_cells",
    "class_label",
    "comparison_from_run",
    "draw_cells",
    "map_extent",
    "map_legend",
    "select_cells",
    "threshold_note",
)
