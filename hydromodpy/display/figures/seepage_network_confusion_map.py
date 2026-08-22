"""The three-class map of an agreement between two stream networks.

``J`` balances an excess of simulated stream against a missing one, so the
readable image of ``J`` is the map of where each of the two happens: valid
where the two networks share a cell, excess where only the model put one,
missing where only the map did. A single scalar cannot say whether a residual
near zero comes from a good fit or from a large excess cancelling a large
gap, and this map can.

The three classes are drawn in a palette whose lightnesses are far apart, so
the map keeps its three classes on a greyscale print and under every common
colour-vision deficiency. The masks are passed in: a run persists the fields a
solver produced, never the supports a criterion built out of them.
"""

from __future__ import annotations

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

CONFUSION_COLORS: dict[str, str] = {
    "valid": HIGH_CONTRAST_TRIPLET[0],
    "excess": HIGH_CONTRAST_TRIPLET[1],
    "missing": HIGH_CONTRAST_TRIPLET[2],
}
"""One colour per class of the confusion map, darkest for the agreement."""

CONFUSION_LABELS: dict[str, str] = {
    "valid": "valid: simulated and mapped",
    "excess": "excess: simulated only",
    "missing": "missing: mapped only",
}

_BACKGROUND_COLOR = "#EDEDED"


@register
class SeepageNetworkConfusionMap(BaseFigure):
    """Valid, excess and missing cells of a simulated stream network.

    The three masks are ``(n_cells,)`` booleans over the mesh faces, and they
    partition the union of the two networks: ``valid`` is the intersection,
    ``excess`` what only the model produced, ``missing`` what only the map
    holds. ``background`` outlines the rest of the catchment and is optional.
    """

    spec = FigureSpec(
        name="seepage_network_confusion_map",
        title="Seepage network confusion",
        kind="comparison",
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        valid: np.ndarray,
        excess: np.ndarray,
        missing: np.ndarray,
        background: np.ndarray | None = None,
        **_,
    ) -> Axes:
        from matplotlib.patches import Patch

        polygons = face_polygons(sim)
        n_faces = len(polygons)
        classes = {
            "valid": _as_mask(valid, n_faces, "valid"),
            "excess": _as_mask(excess, n_faces, "excess"),
            "missing": _as_mask(missing, n_faces, "missing"),
        }
        _refuse_overlap(classes)

        if background is not None:
            outside = _as_mask(background, n_faces, "background")
            for mask in classes.values():
                outside = outside & ~mask
            _add_class(ax, polygons, outside, color=_BACKGROUND_COLOR, zorder=1)

        for index, (name, mask) in enumerate(classes.items()):
            _add_class(ax, polygons, mask, color=CONFUSION_COLORS[name], zorder=2 + index)

        style_map_axes(ax)
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        ax.set_title(f"Seepage network confusion - {sim.name or sim.sim_id}")
        ax.legend(
            handles=[
                Patch(
                    facecolor=CONFUSION_COLORS[name],
                    edgecolor="none",
                    label=f"{CONFUSION_LABELS[name]} ({_cell_count(mask)})",
                )
                for name, mask in classes.items()
            ],
            loc="best",
            fontsize=9,
            framealpha=0.9,
        )
        return ax


def _add_class(
    ax: Axes,
    polygons: list[np.ndarray],
    mask: np.ndarray,
    *,
    color: str,
    zorder: int,
) -> None:
    """Draw one class of cells as a flat colour, or nothing when it is empty."""
    from matplotlib.collections import PolyCollection

    selected = np.flatnonzero(mask)
    if selected.size == 0:
        return
    ax.add_collection(
        PolyCollection(
            [polygons[index] for index in selected],
            facecolors=color,
            edgecolors="none",
            zorder=zorder,
        )
    )
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()


def _cell_count(mask: np.ndarray) -> str:
    """Return the size of one class, written for a legend entry."""
    count = int(mask.sum())
    return f"{count} cell" if count == 1 else f"{count} cells"


def _as_mask(values: np.ndarray, n_faces: int, label: str) -> np.ndarray:
    """Return one boolean mask, checked against the number of mesh faces."""
    mask = np.asarray(values).reshape(-1)
    if mask.size != n_faces:
        raise ValueError(f"the {label} mask holds {mask.size} cells, the mesh holds {n_faces}.")
    return mask.astype(bool)


def _refuse_overlap(classes: dict[str, np.ndarray]) -> None:
    """Refuse two classes sharing a cell: a cell belongs to exactly one."""
    names = list(classes)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            shared = int(np.sum(classes[first] & classes[second]))
            if shared:
                raise ValueError(
                    f"{shared} cells are both {first!r} and {second!r}; the three classes "
                    "partition the two networks and cannot overlap."
                )
