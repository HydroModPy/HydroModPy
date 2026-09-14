"""The three-class map of an agreement between two stream networks.

``J`` balances an excess of simulated stream against a missing one, so the
readable image of ``J`` is the map of where each of the two happens: valid
where the two networks share a cell, excess where only the model put one,
missing where only the map did. A single scalar cannot say whether a residual
near zero comes from a good fit or from a large excess cancelling a large gap,
and this map can.

Only if it can be read. The three classes are one cell wide and the mesh is
not: on the Nancon they hold 1 681 cells out of 60 395, so the map opens on
the delineated catchment, where every class of the criterion lives, and draws
its cells with the weight a one-cell line needs to survive the page. The three
counts sit in the key under the map, beside the colour each belongs to.

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
    CASING_COLOR,
    CELL_WEIGHT_PT,
    MapExtent,
    MapExtentName,
    cell_count,
    checked_cells,
    class_label,
    comparison_from_run,
    draw_cells,
    map_extent,
    map_legend,
    select_cells,
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

_CLASS_ORDER: tuple[int, ...] = (AGREEMENT_VALID, AGREEMENT_EXCESS, AGREEMENT_MISSING)
"""The three classes, drawn over the casing in a stable order."""

_LEGEND_ORDER: tuple[int, ...] = (
    AGREEMENT_VALID,
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
)
"""The three classes first: they are what the figure is read for."""

_NEITHER_EDGE = "#c8c8c8"
"""A border on the legend swatch, which is otherwise white on white."""

_FLAT_WEIGHT_PT = 0.0
"""What everything but the casing is drawn at, so no class widens over another.

The three classes interleave cell by cell along the same one-cell line. Given
a stroke each, every class grew half that stroke into its neighbours and the
one drawn first came out smaller than the count printed beside it: on the
Nancon the valid class held the most cells of the three and the least ink of
the three. The weight is carried once, by the casing under all of them.
"""


@register
class SeepageNetworkConfusionMap(BaseFigure):
    """Valid, excess and missing cells of a simulated stream network.

    Every cell of the mesh carries exactly one of the four classes, read from
    the run: the release flux the solver wrote, the mapped network the project
    declares and the delineated watershed, put back through the construction
    the criterion scores. Any backend persisting those draws the same map.

    ``extent`` picks the frame: ``catchment`` crops to the delineated
    watershed, ``mesh`` keeps the whole modelled domain.
    """

    spec = FigureSpec(
        name="seepage_network_confusion_map",
        title="Seepage network confusion",
        kind="comparison",
        required_fields=("release_flux",),
        default_figsize=(7.0, 6.2),
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
        extent: MapExtentName = "catchment",
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

        draw_cells(
            ax,
            select_cells(polygons, agreement == AGREEMENT_NEITHER),
            color=AGREEMENT_COLORS[AGREEMENT_NEITHER],
            label=agreement_label(AGREEMENT_NEITHER),
            zorder=1,
            weight_pt=_FLAT_WEIGHT_PT,
        )
        draw_cells(
            ax,
            select_cells(polygons, agreement != AGREEMENT_NEITHER),
            color=CASING_COLOR,
            label="_network casing",
            zorder=2,
            weight_pt=CELL_WEIGHT_PT,
        )
        for zorder, value in enumerate(_CLASS_ORDER, start=3):
            draw_cells(
                ax,
                select_cells(polygons, agreement == value),
                color=AGREEMENT_COLORS[value],
                label=agreement_label(value),
                zorder=zorder,
                weight_pt=_FLAT_WEIGHT_PT,
            )

        style_map_axes(ax)
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")

        window = map_extent(sim, polygons, extent=extent)
        notes = [threshold_note(comparison), f"frame: {window.name}"]
        map_legend(ax, _legend_handles(agreement, window), note="\n".join(notes))
        window.apply(ax)
        return ax


def _legend_handles(agreement: np.ndarray, window: MapExtent) -> list[Patch]:
    """Return one legend patch per class, sized by the cells it holds.

    The three classes are always listed, an empty one included: a class the
    model produced nothing for is a result, and a legend that drops it reads
    as a figure that was never asked the question. They are counted over the
    whole mesh, which is what the criterion averages; the ground is counted
    over the frame instead, since it is not a published number and a reader
    checking it counts the grey they can see.
    """
    from matplotlib.patches import Patch

    handles: list[Patch] = []
    for value in _LEGEND_ORDER:
        selected = agreement == value
        if value == AGREEMENT_NEITHER:
            selected = selected & window.inside
            if not selected.any():
                continue
        handles.append(
            Patch(
                facecolor=AGREEMENT_COLORS[value],
                edgecolor=_NEITHER_EDGE if value == AGREEMENT_NEITHER else CASING_COLOR,
                label=f"{class_label(value)} ({cell_count(selected)})",
            )
        )
    return handles


__all__ = ["SeepageNetworkConfusionMap"]
