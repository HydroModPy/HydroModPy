"""Which reaches of the simulated network run all year and which dry up.

A share of the record, as ``flow_persistence_map`` draws it, mixes two
different things: a reach that ran every step of a wet year and none of a dry
one, and a reach that ran half of every year. The question a field campaign
asks is the second one, cycle by cycle, so this map classifies each cell
within one hydrological cycle instead of averaging over all of them.

Three classes, the legacy ones: perennial when the cell carried flow at every
timestep of the cycle, intermittent when it carried flow at some of them, dry
when it never did.
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
from hydromodpy.display.legend_placement import place_legend
from hydromodpy.display.map_axes import style_relative_km_axes
from hydromodpy.display.overlays import apply_overlays
from hydromodpy.display.ugrid import render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


PERENNIAL_COLOR = "#1f6fb4"
"""Cells that carried flow at every timestep of the cycle."""

INTERMITTENT_COLOR = "#d2762a"
"""Cells that carried flow at some timesteps of the cycle, not all."""

DRY_COLOR = "#EDEDED"
"""Cells that carried no flow at any step of the cycle."""

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
    ``threshold``
        Accumulated flux above which a cell counts as flowing, in m3/s.
    """

    spec = FigureSpec(
        name="flow_intermittence_map",
        title="Flow intermittence",
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
        overlays: tuple[str, ...] | list[str] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.colors import BoundaryNorm, ListedColormap
        from matplotlib.patches import Patch

        flowing = flowing_stack(sim, threshold=threshold)
        blocks = cycles(sim, flowing.shape[0])
        label = resolve_cycle(blocks, cycle, figure=self.spec.name)
        steps = blocks[label]
        window = flowing[steps]

        flowing_steps = window.sum(axis=0)
        perennial = flowing_steps == window.shape[0]
        intermittent = (flowing_steps > 0) & ~perennial
        classes = np.where(perennial, 0.0, np.where(intermittent, 1.0, np.nan))

        palette = ListedColormap((PERENNIAL_COLOR, INTERMITTENT_COLOR), name="intermittence")
        palette = palette.with_extremes(bad=DRY_COLOR)
        collection = render_face_field(ax, sim, classes, cmap=palette, colorbar=False)
        collection.set_norm(BoundaryNorm([-0.5, 0.5, 1.5], palette.N))

        apply_overlays(
            ax,
            sim,
            ("watershed", "outlet") if overlays is None else overlays,
            timestep=int(steps[-1]),
        )
        style_relative_km_axes(ax)
        ax.set_title(
            f"{self.spec.title} - {sim.name or sim.sim_id}\n"
            f"{span_label(sim, steps) or label}, {window.shape[0]} timesteps"
        )

        handles = [
            Patch(
                facecolor=PERENNIAL_COLOR,
                label=f"perennial ({int(perennial.sum()):,} cells)",
            ),
            Patch(
                facecolor=INTERMITTENT_COLOR,
                label=f"intermittent ({int(intermittent.sum()):,} cells)",
            ),
            Patch(
                facecolor=DRY_COLOR,
                edgecolor=DRY_EDGE,
                label=f"dry ({int((flowing_steps == 0).sum()):,} cells)",
            ),
        ]
        place_legend(ax, handles=handles, fontsize=9, framealpha=0.9)
        return ax

    def unavailable_reason(self, sim: Run) -> str | None:
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        if int(sim.n_timesteps or 0) < 2:
            return "a cell cannot be called intermittent over a single timestep"
        return None


__all__ = ["FlowIntermittenceMap"]
