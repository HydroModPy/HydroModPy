"""Share of the run each cell spent carrying flow.

A transient run holds one wet-network map per timestep, and reading them one
after another is how a network that shrinks every summer gets missed. This
collapses the whole record onto one map: dark where the channel ran all year,
pale where it only ran at the wettest steps, and out of the ramp entirely
where nothing ever reached the cell.

The legacy persistency index is the same number, computed on the same field,
over the whole record rather than over one cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._flow_persistence import (
    FLOW_FIELD,
    cycles,
    flowing_stack,
    resolve_cycle,
    span_label,
)
from hydromodpy.display.figures.accumulation_map import (
    GROUND_COLOR,
    GROUND_EDGE,
    truncated_palette,
)
from hydromodpy.display.legend_placement import place_legend
from hydromodpy.display.map_axes import style_relative_km_axes
from hydromodpy.display.overlays import apply_overlays
from hydromodpy.display.ugrid import render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class FlowPersistenceMap(BaseFigure):
    """Fraction of the simulated timesteps each cell carried accumulated flow.

    Options
    -------
    ``cycle``
        Label of one hydrological cycle, usually a calendar year, to read
        instead of the whole record. Set it to the cycle
        ``flow_intermittence_map`` classifies when the two maps are read side
        by side: a cell that ran through a wet year and stopped through a dry
        one otherwise reads as dry on one map and as flowing on the other,
        which is two windows disagreeing and not two answers.
    ``threshold``
        Accumulated flux above which a cell counts as flowing, in m3/s.
    ``cmap``
        Sequential palette. Its pale end is cut so no drawn cell is lighter
        than the cells the ramp says nothing about.
    """

    spec = FigureSpec(
        name="flow_persistence_map",
        title="Flow persistence",
        kind="spatial",
        required_fields=(FLOW_FIELD,),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        cycle: str | None = None,
        threshold: float = 0.0,
        cmap: str = "Blues",
        overlays: tuple[str, ...] | list[str] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.patches import Patch

        flowing = flowing_stack(sim, threshold=threshold)
        steps = np.arange(flowing.shape[0])
        if cycle is not None:
            blocks = cycles(sim, flowing.shape[0])
            steps = blocks[resolve_cycle(blocks, cycle, figure=self.spec.name)]
            flowing = flowing[steps]
        share = 100.0 * flowing.mean(axis=0)
        ever = share > 0.0

        render_face_field(
            ax,
            sim,
            np.where(ever, share, np.nan),
            cmap=truncated_palette(cmap, 0.45),
            vmin=0.0,
            vmax=100.0,
            cbar_label="Timesteps carrying flow (%)",
        )
        apply_overlays(
            ax,
            sim,
            ("watershed", "outlet") if overlays is None else overlays,
            timestep=0,
        )
        style_relative_km_axes(ax)
        window = span_label(sim, steps)
        ax.set_title(
            f"{self.spec.title} - {sim.name or sim.sim_id}\n"
            f"{window + ', ' if window else ''}{flowing.shape[0]} timesteps, "
            f"{int(ever.sum()):,} cells ever flowing"
        )

        handles = ax.get_legend_handles_labels()[0]
        never = int((~ever).sum())
        if never:
            handles.append(
                Patch(
                    facecolor=GROUND_COLOR,
                    edgecolor=GROUND_EDGE,
                    label=f"never flowing ({never:,} cells)",
                )
            )
        if handles:
            place_legend(ax, handles=handles, fontsize=9, framealpha=0.9)
        return ax

    def unavailable_reason(self, sim: Run) -> str | None:
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        if int(sim.n_timesteps or 0) < 2:
            return "a persistence share needs more than one timestep"
        return None


__all__ = ["FlowPersistenceMap"]
