"""The mapped network drawn from its heads, and how each head landed.

The heads rule keeps only where the map says a stream starts and lets the
criterion graph draw the rest (:mod:`hydromodpy.core.stream_heads`), so the
map carried on the page is not the mapped linework but the trace: the cells
a head's descent actually walked. This figure exists to show that trace,
never the rule the run happened to be scored under, so it always redraws
under ``"heads"`` (:mod:`hydromodpy.results.derive.network_heads_view`).

A run that carries the permanent reaches of its map shows them too: their
trace on top of the full network's, and their heads as triangles. The union of
the two traces is the maximal map a calibration with a minimal map scores.

Nothing is scored here: the counts on the page are cells and heads, and the
distances belong to a calibration trial.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._stream_comparison import (
    CELL_WEIGHT_PT,
    MapExtentName,
    cell_count,
    checked_cells,
    draw_cells,
    map_extent,
    map_legend,
    select_cells,
)
from hydromodpy.display.maps.axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display.maps.mesh_geometry import face_polygons
from hydromodpy.results.derive.network_heads_view import (
    MapHeads,
    NetworkHeadsView,
    network_heads_view_from_run,
)
from hydromodpy.results.derive.stream_network import unavailable_reason_for_comparison

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

TRACE_COLOR = "#1A1A1A"
"""Fill of the cells the heads traced down the criterion graph."""

MAPPED_COLOR = "#1565C0"
"""Stroke of the raw mapped lines, drawn thin underneath the trace."""

PERMANENT_TRACE_COLOR = "#0B3C8C"
"""Fill of the cells the permanent network's heads traced."""

HEAD_COLOR = "#E66100"
"""Marker of a free end kept as a head."""

PERMANENT_HEAD_COLOR = "#0B3C8C"
"""Marker of a permanent free end kept as a head."""

LANDING_COLOR = "#000000"
"""Marker of the cell centre a kept head lands on."""

LOST_COLOR = "#CC0000"
"""Marker of a free end no landing cell was found for."""

SEGMENT_COLOR = "#808080"
"""The thin segment joining a kept head to its landing cell centre."""

_MAPPED_WIDTH_PT = 0.8
_SEGMENT_WIDTH_PT = 0.8
_HEAD_SIZE_PT = 24.0
_LANDING_SIZE_PT = 7.0
_LOST_SIZE_PT = 42.0


@register
class ObservedNetworkHeadsMap(BaseFigure):
    """Draw the mapped lines, the heads kept and lost, and the trace they draw.

    Always redrawn under ``observed_rasterization = "heads"``: with the run's
    own sealed ``heads_snap_radius`` and ``heads_min_drained_area_km2`` when it
    was scored that way, the criterion's defaults otherwise, because this
    figure exists to show the heads rule and not whichever one scored the run.

    ``output`` names the calibration output to read the other settings of
    (the seepage threshold, the neighbour graph, the positional accuracy) when
    the run sealed several network outputs; the first one otherwise.
    ``extent`` picks the frame: ``catchment`` crops to the delineated
    watershed, ``mesh`` keeps the whole modelled domain.
    """

    spec = FigureSpec(
        name="observed_network_heads_map",
        title="Observed network drawn from its heads",
        kind="comparison",
        required_fields=("release_flux",),
        default_figsize=(7.0, 6.8),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        return unavailable_reason_for_comparison(sim)

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        output: str | None = None,
        extent: MapExtentName = "catchment",
        **_,
    ) -> Axes:
        view = network_heads_view_from_run(sim, output=output)
        polygons = face_polygons(sim)
        traced = checked_cells(view.full.traced, len(polygons), "traced map")
        draw_cells(
            ax,
            select_cells(polygons, traced),
            color=TRACE_COLOR,
            label="_traced",
            zorder=3,
            weight_pt=CELL_WEIGHT_PT,
        )
        if view.permanent is not None:
            draw_cells(
                ax,
                select_cells(
                    polygons,
                    checked_cells(view.permanent.traced, len(polygons), "permanent trace"),
                ),
                color=PERMANENT_TRACE_COLOR,
                label="_permanent",
                zorder=3.5,
                weight_pt=CELL_WEIGHT_PT,
            )
        for line in view.mapped_lines_xy:
            ax.plot(
                line[:, 0],
                line[:, 1],
                color=MAPPED_COLOR,
                linewidth=_MAPPED_WIDTH_PT,
                zorder=2,
                solid_capstyle="round",
            )
        _draw_heads(ax, view.full, marker="o", color=HEAD_COLOR)
        if view.permanent is not None:
            _draw_heads(ax, view.permanent, marker="^", color=PERMANENT_HEAD_COLOR)

        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        style_map_axes(ax)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}\n{_title_counts(view)}")

        window = map_extent(sim, polygons, extent=extent)
        notes = [*_redraw_note(view), view.settings_note, f"frame: {window.name}"]
        map_legend(ax, _handles(view, traced), note="\n".join(notes))
        window.apply(ax)
        return ax


def _title_counts(view: NetworkHeadsView) -> str:
    """Return the title line: heads traced, heads lost, near-map share."""
    text = _counts(view.full)
    near_share = view.full.indices["heads_trace_near_map_share"]
    share_words = "n/a" if not np.isfinite(near_share) else f"{near_share:.0%}"
    text += f", {share_words} of the trace near the map"
    if view.permanent is not None:
        text += f"; permanent: {_counts(view.permanent)}"
    return text


def _counts(heads: MapHeads) -> str:
    """Return how many heads of one map were traced and lost."""
    n_lost = int(heads.indices["n_heads_lost"])
    n_kept = int(heads.indices["n_heads"]) - n_lost
    return f"{n_kept} head(s) traced, {n_lost} lost"


def _draw_heads(ax: Axes, heads: MapHeads, *, marker: str, color: str) -> None:
    """Draw the heads of one map, the segment to each landing cell, and the lost ones."""
    for head, landing in zip(heads.head_xy, heads.landing_xy, strict=True):
        ax.plot(
            [head[0], landing[0]],
            [head[1], landing[1]],
            color=SEGMENT_COLOR,
            linewidth=_SEGMENT_WIDTH_PT,
            zorder=4,
        )
    if heads.landing_xy.shape[0]:
        ax.scatter(
            heads.landing_xy[:, 0],
            heads.landing_xy[:, 1],
            s=_LANDING_SIZE_PT,
            color=LANDING_COLOR,
            zorder=6,
        )
    if heads.head_xy.shape[0]:
        ax.scatter(
            heads.head_xy[:, 0],
            heads.head_xy[:, 1],
            s=_HEAD_SIZE_PT,
            color=color,
            marker=marker,
            zorder=7,
        )
    if heads.lost_xy.shape[0]:
        ax.scatter(
            heads.lost_xy[:, 0],
            heads.lost_xy[:, 1],
            s=_LOST_SIZE_PT,
            color=LOST_COLOR,
            marker="x",
            linewidth=1.6,
            zorder=8,
        )


def _redraw_note(view: NetworkHeadsView) -> list[str]:
    """Return the note saying the run was redrawn under another rule, or nothing."""
    if not view.redrawn_as_heads:
        return []
    return ["redrawn under observed_rasterization = 'heads' with its default radius and area"]


def _handles(view: NetworkHeadsView, traced: np.ndarray) -> list:
    """Return the legend handles, one per class actually drawn."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    handles = [
        Patch(facecolor=TRACE_COLOR, edgecolor=TRACE_COLOR, label=f"traced ({cell_count(traced)})"),
    ]
    if view.permanent is not None:
        handles.append(
            Patch(
                facecolor=PERMANENT_TRACE_COLOR,
                edgecolor=PERMANENT_TRACE_COLOR,
                label=f"permanent trace ({cell_count(view.permanent.traced)})",
            )
        )
    handles.append(Line2D([], [], color=MAPPED_COLOR, linewidth=1.5, label="mapped network"))
    landed = view.full.head_xy.shape[0]
    if landed:
        handles.append(_marker("o", HEAD_COLOR, f"head kept ({landed})"))
    if view.permanent is not None and view.permanent.head_xy.shape[0]:
        handles.append(
            _marker(
                "^",
                PERMANENT_HEAD_COLOR,
                f"permanent head kept ({view.permanent.head_xy.shape[0]})",
            )
        )
        landed += view.permanent.head_xy.shape[0]
    if landed:
        handles.append(_marker("o", LANDING_COLOR, "landing cell centre", size=4))
    lost = view.full.lost_xy.shape[0] + (
        0 if view.permanent is None else view.permanent.lost_xy.shape[0]
    )
    if lost:
        handles.append(_marker("x", LOST_COLOR, f"head lost ({lost})"))
    return handles


def _marker(marker: str, color: str, label: str, *, size: float | None = None):
    """Return one legend marker handle."""
    from matplotlib.lines import Line2D

    extra = {} if size is None else {"markersize": size}
    return Line2D([], [], marker=marker, linestyle="none", color=color, label=label, **extra)


__all__ = ["ObservedNetworkHeadsMap"]
