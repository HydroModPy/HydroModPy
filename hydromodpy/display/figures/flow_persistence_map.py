"""Share of the run each cell spent flowing.

A transient run holds one wet-network map per timestep, and reading them one
after another is how a network that shrinks every summer gets missed. This
collapses the whole record onto one map: dark where the channel ran all year,
pale where it only ran at the wettest steps, and out of the ramp entirely
where nothing ever reached the cell.

"Flowing" is the definition the network criterion scores: the downstream
closure of the seepage cells on the criterion graph, above the visible flow.
The persistency index of Abherve et al. (2025) is the same share, over the
whole record rather than over one cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec, run_suffix
from hydromodpy.display.figure_options import (
    DiagonalNeighbors,
    Extent,
    FlowTauSpecificRatio,
    Opt,
    Overlays,
    VisibleFlow,
)
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
    catchment_cells,
    map_extent,
    map_legend,
    veil_outside_catchment,
)
from hydromodpy.display.figures.accumulation_map import (
    GROUND_COLOR,
    GROUND_EDGE,
    truncated_palette,
)
from hydromodpy.display.maps.axes import style_map_axes
from hydromodpy.display.maps.mesh_geometry import face_polygons
from hydromodpy.display.maps.overlays import apply_overlays
from hydromodpy.display.maps.ugrid import render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class FlowPersistenceMap(BaseFigure):
    """Fraction of the simulated timesteps each cell flowed."""

    spec = FigureSpec(
        name="flow_persistence_map",
        title="Flow persistence",
        kind="spatial",
        required_fields=(FLOW_FIELD,),
        default_figsize=(7.0, 6.4),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        cycle: Annotated[
            str | None,
            Opt(
                "Label of one hydrological cycle, usually a calendar year, to read "
                "instead of the whole record. Set it to the cycle "
                "flow_intermittence_map classifies when the two maps are read side by "
                "side. Left out, the whole record."
            ),
        ] = None,
        visible_flow: VisibleFlow = None,
        tau_specific_ratio: FlowTauSpecificRatio = None,
        diagonal_neighbors: DiagonalNeighbors = None,
        cmap: Annotated[
            str,
            Opt(
                "Sequential palette, by Matplotlib name. Its pale end is cut so no drawn "
                "cell is lighter than the cells that never flowed."
            ),
        ] = "Blues",
        overlays: Overlays = None,
        extent: Extent = "catchment",
        **_,
    ) -> Axes:
        from matplotlib.patches import Patch

        flow = cycle_flow(
            sim,
            visible_flow=visible_flow,
            tau_specific_ratio=tau_specific_ratio,
            diagonal_neighbors=diagonal_neighbors,
        )
        if cycle is None:
            steps = np.sort(np.concatenate(flow.steps))
            counts = flow.total()
        else:
            blocks = dict(zip(flow.labels, flow.steps, strict=True))
            steps, counts = flow.block(resolve_cycle(blocks, cycle, figure=self.spec.name))
        share = 100.0 * counts / max(int(steps.size), 1)
        ever = share > 0.0

        render_face_field(
            ax,
            sim,
            np.where(ever, share, np.nan),
            cmap=truncated_palette(cmap, 0.45),
            vmin=0.0,
            vmax=100.0,
            cbar_label="Timesteps flowing (%)",
        )
        polygons = face_polygons(sim)
        frame = map_extent(sim, polygons, extent=extent)
        counted = catchment_cells(sim, polygons) if extent == "catchment" else None
        if counted is not None:
            veil_outside_catchment(ax, sim, frame)
        scope = np.ones_like(ever) if counted is None else counted
        apply_overlays(
            ax,
            sim,
            ("watershed", "outlet") if overlays is None else overlays,
            timestep=0,
        )
        style_map_axes(ax)
        window = span_label(sim, steps)
        ax.set_title(
            f"{self.spec.title}{run_suffix(sim)}\n"
            f"{window + ', ' if window else ''}{steps.size} timesteps, "
            f"{int((ever & scope).sum()):,} cells ever flowing"
        )

        handles = ax.get_legend_handles_labels()[0]
        never = int((~ever & scope).sum())
        if never:
            handles.append(
                Patch(
                    facecolor=GROUND_COLOR,
                    edgecolor=GROUND_EDGE,
                    label=f"never flowing ({never:,} cells)",
                )
            )
        map_legend(ax, handles, note=frame_note(flow, counted), ncols=max(len(handles), 1))
        frame.apply(ax)
        return ax

    def unavailable_reason(self, sim: Run) -> str | None:
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        if int(sim.n_timesteps or 0) < 2:
            return "a persistence share needs more than one timestep"
        return flow_unavailable_reason(sim)


__all__ = ["FlowPersistenceMap"]
