"""The downslope distance field, in the four classes of the paper.

``D_so`` and ``D_os`` are means, and a mean hides the shape of what it
averages: on a real catchment the median descent is zero and a handful of long
branches carry almost the whole value. This map is the field behind the
number. It says *where* the two networks disagree, which no scalar can, and it
says it in the classes the paper reads, 0-75, 75-500, 500-1000 and more than
1000 m, so two runs are compared on the same four steps instead of on two
colour scales stretched to their own extremes.

Three states, not one. A cell of the support carries a distance and takes its
class. A cell outside the support carries no measurement and is drawn out of
the scale: painting it in the nearest class would invent a perfect agreement
where nothing was measured. A cell whose descent ends without meeting its
target has no distance at all, and drawing it as "more than 1000 m" would
state a length the algorithm never found; it gets a hatched state of its own,
named in the legend.

The field is not persisted: the criterion builds it per trial and keeps it in
memory, so it arrives as an argument of :meth:`DownslopeDistanceMap.render`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display.mesh_geometry import face_polygons

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

DISTANCE_CLASS_EDGES_M: tuple[float, ...] = (0.0, 75.0, 500.0, 1000.0)
"""Lower edge of each distance class, in metres. The classes of the paper."""

_CLASS_RAMP: tuple[str, ...] = (
    "#E5CE8C",
    HIGH_CONTRAST_TRIPLET[1],
    HIGH_CONTRAST_TRIPLET[2],
    HIGH_CONTRAST_TRIPLET[0],
)
"""Light to dark, so a longer descent reads as a darker cell.

The three darkest steps are the high-contrast triplet, ordered by lightness
rather than by hue, and the lightest is a tint of the sand that opens it. The
gaps in perceived brightness are wide enough for the four classes to stay
ordered and separable on a greyscale print.

The lightest class stops at a relative luminance of 0.63, well below the near
white of an off-support cell at 0.85. A lighter tint printed almost the same
grey as a cell that was never measured, which is exactly the confusion the
third state exists to prevent.
"""

_OFF_SUPPORT_COLOR = "#EDEDED"
_UNREACHABLE_COLOR = "#FFFFFF"
_UNREACHABLE_EDGE = "#333333"
_UNREACHABLE_HATCH = "///"

_OFF_SUPPORT_LABEL = "off support"
_UNREACHABLE_LABEL = "unreachable"


def class_labels(edges: Sequence[float]) -> tuple[str, ...]:
    """Return one legend label per class, the last one open-ended."""
    labels = [f"{low:g}-{high:g} m" for low, high in zip(edges[:-1], edges[1:], strict=False)]
    labels.append(f"> {edges[-1]:g} m")
    return tuple(labels)


def class_colors(n_classes: int) -> tuple[str, ...]:
    """Return ``n_classes`` colours sampled along the light-to-dark ramp.

    Four classes give back the ramp itself, so the default map is drawn in
    exactly the four colours declared above; a caller passing its own edges
    still gets a scale ordered by lightness.
    """
    from matplotlib.colors import LinearSegmentedColormap, to_hex

    if n_classes == len(_CLASS_RAMP):
        return _CLASS_RAMP
    ramp = LinearSegmentedColormap.from_list("downslope_distance", _CLASS_RAMP)
    return tuple(to_hex(ramp(position)) for position in np.linspace(0.0, 1.0, n_classes))


# The values do not come from the run, and the scale is four discrete classes
# rather than a continuous colorbar, so ScalarFaceMap gives nothing here: its
# render() reads sim.field() and calls render_face_field(). BaseFigure it is.
@register
class DownslopeDistanceMap(BaseFigure):
    """Plan map of the downslope distance from one support to its target.

    ``distance`` is the ``(n_cells,)`` field the criterion computes: a length
    in metres where the descent arrives, ``inf`` where it ends without meeting
    the target, ``nan`` where nothing was measured. ``support`` is the mask of
    the cells the mean is taken over; it defaults to every measured cell.
    """

    spec = FigureSpec(
        name="downslope_distance_map",
        title="Downslope distance classes",
        kind="spatial",
        default_figsize=(7.0, 5.5),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Refuse a run-driven render: the distance field is never persisted.

        The criterion computes the descent of every cell at each trial and
        keeps it in memory, so a gallery has nothing to hand this figure.
        Saying it here turns the crash of a figure driven by name into a skip
        carrying the reason.
        """
        del sim
        return (
            "needs the per-cell downslope distance field the stream-network "
            "criterion computes during a calibration; a run does not persist it, "
            "so this figure is drawn by passing distance= to render()"
        )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        distance: np.ndarray,
        support: np.ndarray | None = None,
        class_edges: Sequence[float] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.patches import Patch

        polygons = face_polygons(sim)
        n_faces = len(polygons)
        edges = _checked_edges(DISTANCE_CLASS_EDGES_M if class_edges is None else class_edges)
        values = _checked_distance(distance, n_faces)

        measured = ~np.isnan(values)
        on_support = measured if support is None else _checked_mask(support, n_faces) & measured
        unreachable = on_support & np.isinf(values)
        reached = on_support & ~np.isinf(values)

        labels = class_labels(edges)
        colors = class_colors(len(edges))
        classes = _classify(values, reached, edges)

        _add_layer(
            ax,
            polygons,
            ~on_support,
            color=_OFF_SUPPORT_COLOR,
            label=_OFF_SUPPORT_LABEL,
            zorder=1,
        )
        for index, label in enumerate(labels):
            _add_layer(
                ax,
                polygons,
                classes == index,
                color=colors[index],
                label=label,
                zorder=2 + index,
            )
        _add_layer(
            ax,
            polygons,
            unreachable,
            color=_UNREACHABLE_COLOR,
            label=_UNREACHABLE_LABEL,
            zorder=2 + len(labels),
            hatch=_UNREACHABLE_HATCH,
            edgecolor=_UNREACHABLE_EDGE,
        )

        style_map_axes(ax)
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")

        handles = [
            Patch(
                facecolor=colors[index],
                edgecolor="none",
                label=f"{label} ({_cell_count(classes == index)})",
            )
            for index, label in enumerate(labels)
        ]
        if unreachable.any():
            handles.append(
                Patch(
                    facecolor=_UNREACHABLE_COLOR,
                    edgecolor=_UNREACHABLE_EDGE,
                    hatch=_UNREACHABLE_HATCH,
                    label=(
                        "unreachable: the descent never reaches the target "
                        f"({_cell_count(unreachable)})"
                    ),
                )
            )
        if not on_support.all():
            handles.append(
                Patch(
                    facecolor=_OFF_SUPPORT_COLOR,
                    edgecolor="none",
                    label=f"not on the measured support ({_cell_count(~on_support)})",
                )
            )
        ax.legend(handles=handles, loc="best", fontsize=9, framealpha=0.9)

        note = _absence_note(on_support, reached)
        if note is not None:
            ax.annotate(
                note,
                xy=(0.5, 0.03),
                xycoords="axes fraction",
                ha="center",
                va="bottom",
                fontsize=9,
                bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
                zorder=10,
            )
        return ax


def _classify(values: np.ndarray, reached: np.ndarray, edges: tuple[float, ...]) -> np.ndarray:
    """Return the class index of every cell, ``-1`` where there is none."""
    classes = np.full(values.size, -1, dtype="int64")
    if not reached.any():
        return classes
    inner = np.asarray(edges[1:], dtype="float64")
    classes[reached] = np.searchsorted(inner, values[reached], side="right")
    return classes


def _absence_note(on_support: np.ndarray, reached: np.ndarray) -> str | None:
    """Say what is missing when the map has no distance to show."""
    if not on_support.any():
        return "no cell is on the measured support: there is no distance to map"
    if not reached.any():
        return "no cell of the support reaches its target: every descent ends short"
    return None


def _add_layer(
    ax: Axes,
    polygons: list[np.ndarray],
    mask: np.ndarray,
    *,
    color: str,
    label: str,
    zorder: int,
    hatch: str | None = None,
    edgecolor: str = "none",
) -> None:
    """Draw one flat-coloured group of cells, or nothing when it is empty."""
    from matplotlib.collections import PolyCollection

    selected = np.flatnonzero(mask)
    if selected.size == 0:
        return
    collection = PolyCollection(
        [polygons[index] for index in selected],
        facecolors=color,
        edgecolors=edgecolor,
        linewidths=0.3 if hatch else 0.0,
        hatch=hatch,
        label=label,
        zorder=zorder,
    )
    ax.add_collection(collection)
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()


def _cell_count(mask: np.ndarray) -> str:
    """Return the size of one group, written for a legend entry."""
    count = int(mask.sum())
    return f"{count} cell" if count == 1 else f"{count} cells"


def _checked_edges(edges: Sequence[float]) -> tuple[float, ...]:
    """Return the class edges, checked for a usable scale."""
    values = tuple(float(edge) for edge in edges)
    if len(values) < 2:
        raise ValueError(
            f"the class edges hold {len(values)} entry; a scale needs at least two, "
            "since the last one opens the unbounded class."
        )
    # A NaN edge passes every ``<=`` comparison below, so it would reach
    # searchsorted on an unsorted array and scatter the classes silently.
    if not np.isfinite(values).all():
        raise ValueError(f"the class edges must all be finite, got {values}.")
    if any(high <= low for low, high in zip(values[:-1], values[1:], strict=False)):
        raise ValueError(f"the class edges must be strictly increasing, got {values}.")
    return values


def _checked_distance(distance: np.ndarray, n_faces: int) -> np.ndarray:
    """Return the distance field as floats, checked against the mesh."""
    values = np.asarray(distance, dtype="float64").reshape(-1)
    if values.size != n_faces:
        raise ValueError(f"the distance field holds {values.size} cells, the mesh holds {n_faces}.")
    if np.any(values[~np.isnan(values)] < 0.0):
        raise ValueError("the distance field holds a negative length; a descent cannot be one.")
    return values


def _checked_mask(support: np.ndarray, n_faces: int) -> np.ndarray:
    """Return the support as a boolean mask, checked against the mesh."""
    mask = np.asarray(support).reshape(-1)
    if mask.size != n_faces:
        raise ValueError(f"the support mask holds {mask.size} cells, the mesh holds {n_faces}.")
    return mask.astype(bool)


__all__ = [
    "DISTANCE_CLASS_EDGES_M",
    "DownslopeDistanceMap",
    "class_colors",
    "class_labels",
]
