"""Which reaches of the simulated network run all year and which dry up.

A share of the record, as ``flow_persistence_map`` draws it, mixes two
different things: a reach that ran every step of a wet year and none of a dry
one, and a reach that ran half of every year. The question a field campaign
asks is the second one, cycle by cycle, so this map classifies each cell
within one hydrological cycle instead of averaging over all of them.

Three classes, the legacy ones: perennial when the cell flowed at every
timestep of the cycle, intermittent when it flowed at some of them, dry when it
never did. "Flowing" is the definition the network criterion scores: the
downstream closure of the seepage cells on the criterion graph, above the
visible flow. The perennial class is therefore the yearly minimal extent of
the criterion with ``minimal_dry_steps = 0``, and the union of the two coloured
classes its yearly maximal extent with ``maximal_flowing_steps = 1``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._flow_persistence import (
    FLOW_FIELD,
    cycle_flow,
    flow_unavailable_reason,
    frame_note,
    resolve_cycle,
    span_label,
)
from hydromodpy.display.figures._stream_comparison import (
    MapExtentName,
    catchment_cells,
    map_extent,
    map_legend,
    veil_outside_catchment,
)
from hydromodpy.display.maps.axes import style_map_axes
from hydromodpy.display.maps.mesh_geometry import face_polygons
from hydromodpy.display.maps.overlays import apply_overlays
from hydromodpy.display.maps.ugrid import render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


PERENNIAL_COLOR = "#1f6fb4"
"""Cells that flowed at every timestep of the cycle."""

INTERMITTENT_COLOR = "#d2762a"
"""Cells that flowed at some timesteps of the cycle, not all."""

DRY_COLOR = "#EDEDED"
"""Cells that flowed at no step of the cycle."""

DRY_EDGE = "#C8C8C8"
"""A border on the legend swatch, which is otherwise near-white on white."""


@register
class FlowIntermittenceMap(BaseFigure):
    """Perennial, intermittent and dry cells over one hydrological cycle.

    Options
    -------
    ``cycle``
        Label of the cycle to draw, usually a calendar year. Defaults to the
        last complete one.
    ``visible_flow``
        Routed discharge a cell of the seepage closure must carry to flow:
        ``"1 L/s"`` by default, any discharge with its unit, a share of the
        outlet discharge such as ``"1%"``, or ``"0 L/s"`` for the closure alone.
    ``tau_specific_ratio``
        Seepage threshold as a fraction of the recharge a cell receives; the
        criterion's default when left out.
    ``extent``
        ``"catchment"`` (default) crops to the delineated watershed and counts
        the cells inside it; ``"mesh"`` keeps the whole modelled domain.
    """

    spec = FigureSpec(
        name="flow_intermittence_map",
        title="Flow intermittence",
        kind="spatial",
        required_fields=(FLOW_FIELD,),
        default_figsize=(7.0, 6.4),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        cycle: str | None = None,
        visible_flow: str | None = None,
        tau_specific_ratio: float | None = None,
        diagonal_neighbors: bool | None = None,
        overlays: tuple[str, ...] | list[str] | None = None,
        extent: MapExtentName = "catchment",
        **_,
    ) -> Axes:
        from matplotlib.colors import BoundaryNorm, ListedColormap
        from matplotlib.patches import Patch

        flow = cycle_flow(
            sim,
            visible_flow=visible_flow,
            tau_specific_ratio=tau_specific_ratio,
            diagonal_neighbors=diagonal_neighbors,
        )
        blocks = dict(zip(flow.labels, flow.steps, strict=True))
        label = resolve_cycle(blocks, cycle, figure=self.spec.name)
        steps, flowing_steps = flow.block(label)

        perennial = (flowing_steps == steps.size) & (flowing_steps > 0)
        intermittent = (flowing_steps > 0) & ~perennial
        classes = np.where(perennial, 0.0, np.where(intermittent, 1.0, np.nan))

        palette = ListedColormap((PERENNIAL_COLOR, INTERMITTENT_COLOR), name="intermittence")
        palette = palette.with_extremes(bad=DRY_COLOR)
        collection = render_face_field(ax, sim, classes, cmap=palette, colorbar=False)
        collection.set_norm(BoundaryNorm([-0.5, 0.5, 1.5], palette.N))

        polygons = face_polygons(sim)
        frame = map_extent(sim, polygons, extent=extent)
        counted = catchment_cells(sim, polygons) if extent == "catchment" else None
        if counted is not None:
            veil_outside_catchment(ax, sim, frame)
        scope = np.ones_like(perennial) if counted is None else counted
        apply_overlays(
            ax,
            sim,
            ("watershed", "outlet") if overlays is None else overlays,
            timestep=int(steps[-1]),
        )
        style_map_axes(ax)
        ax.set_title(
            f"{self.spec.title} - {sim.name or sim.sim_id}\n"
            f"{span_label(sim, steps) or label}, {steps.size} timesteps"
        )

        handles = ax.get_legend_handles_labels()[0]
        handles += [
            Patch(
                facecolor=PERENNIAL_COLOR,
                label=f"perennial ({int((perennial & scope).sum()):,} cells)",
            ),
            Patch(
                facecolor=INTERMITTENT_COLOR,
                label=f"intermittent ({int((intermittent & scope).sum()):,} cells)",
            ),
            Patch(
                facecolor=DRY_COLOR,
                edgecolor=DRY_EDGE,
                label=f"dry ({int(((flowing_steps == 0) & scope).sum()):,} cells)",
            ),
        ]
        map_legend(ax, handles, note=frame_note(flow, counted), ncols=len(handles))
        frame.apply(ax)
        return ax

    def unavailable_reason(self, sim: Run) -> str | None:
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        if int(sim.n_timesteps or 0) < 2:
            return "a cell cannot be called intermittent over a single timestep"
        return flow_unavailable_reason(sim)


__all__ = ["FlowIntermittenceMap"]
