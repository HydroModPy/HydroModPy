"""The three-class map of an agreement between two stream networks.

``J`` balances an excess of simulated stream against a missing one, so the
readable image of ``J`` is the map of where each of the two happens: valid
where the two networks share a cell, excess where only the model put one,
missing where only the map did. A single scalar cannot say whether a residual
near zero comes from a good fit or from a large excess cancelling a large gap,
and this map can.

The partition is rebuilt from what the run persisted, through the construction
the criterion scores, so the map cannot disagree with the numbers a trial
published. It moves with the seepage threshold, which the figure names on the
page rather than leaving to a reader to guess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._stream_comparison import (
    AGREEMENT_COLORS,
    annotate_note,
    cell_count,
    checked_cells,
    class_label,
    comparison_from_run,
    threshold_note,
)
from hydromodpy.display.map_axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display.mesh_geometry import face_polygons
from hydromodpy.results.derive.stream_network import (
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
    AGREEMENT_VALID,
    agreement_label,
    unavailable_reason_for_comparison,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.patches import Patch

    from hydromodpy.results.run import Run

_DRAW_ORDER: tuple[int, ...] = (
    AGREEMENT_NEITHER,
    AGREEMENT_VALID,
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
)
"""Background first, then the three classes, so the palette stacks predictably."""

_LEGEND_ORDER: tuple[int, ...] = (
    AGREEMENT_VALID,
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
)
"""The three classes first: they are what the figure is read for."""

_NEITHER_EDGE = "#c8c8c8"
"""A border on the legend swatch, which is otherwise white on white."""


@register
class SeepageNetworkConfusionMap(BaseFigure):
    """Valid, excess and missing cells of a simulated stream network.

    Every cell of the mesh carries exactly one of the four classes, read from
    the run: the release flux the solver wrote, the mapped network the project
    declares and the delineated watershed, put back through the construction
    the criterion scores. Any backend persisting those draws the same map.
    """

    spec = FigureSpec(
        name="seepage_network_confusion_map",
        title="Seepage network confusion",
        kind="comparison",
        required_fields=("release_flux",),
        default_figsize=(7.0, 5.5),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Return why this run holds no stream comparison, or None when it does."""
        return unavailable_reason_for_comparison(sim) or super().unavailable_reason(sim)

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        tau_specific_ratio: float | None = None,
        diagonal_neighbors: bool | None = None,
        timestep: int | None = None,
        **_,
    ) -> Axes:
        comparison = comparison_from_run(
            sim,
            tau_specific_ratio=tau_specific_ratio,
            diagonal_neighbors=diagonal_neighbors,
            timestep=timestep,
        )
        polygons = face_polygons(sim)
        agreement = checked_cells(comparison.agreement, len(polygons), "agreement map")

        for zorder, value in enumerate(_DRAW_ORDER, start=1):
            _add_class(
                ax,
                polygons,
                agreement == value,
                color=AGREEMENT_COLORS[value],
                label=agreement_label(value),
                zorder=zorder,
            )

        style_map_axes(ax)
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")
        ax.legend(handles=_legend_handles(agreement), loc="best", fontsize=9, framealpha=0.9)
        annotate_note(ax, threshold_note(comparison))
        return ax


def _legend_handles(agreement: np.ndarray) -> list[Patch]:
    """Return one legend patch per class, sized by the cells it holds.

    The three classes are always listed, an empty one included: a class the
    model produced nothing for is a result, and a legend that drops it reads
    as a figure that was never asked the question.
    """
    from matplotlib.patches import Patch

    handles: list[Patch] = []
    for value in _LEGEND_ORDER:
        selected = agreement == value
        if value == AGREEMENT_NEITHER and not selected.any():
            continue
        handles.append(
            Patch(
                facecolor=AGREEMENT_COLORS[value],
                edgecolor=_NEITHER_EDGE if value == AGREEMENT_NEITHER else "none",
                label=f"{class_label(value)} ({cell_count(selected)})",
            )
        )
    return handles


def _add_class(
    ax: Axes,
    polygons: list[np.ndarray],
    mask: np.ndarray,
    *,
    color: str,
    label: str,
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
            label=label,
            zorder=zorder,
        )
    )
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()


__all__ = ["SeepageNetworkConfusionMap"]
