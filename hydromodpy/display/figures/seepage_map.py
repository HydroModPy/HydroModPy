"""Seepage area map (cells where the water table reaches the surface)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display._ugrid import last_timestep, render_face_field
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class SeepageMap(BaseFigure):
    """Binary seepage indicator over the mesh.

    1 marks cells where the simulated head reaches or exceeds the surface
    elevation; 0 marks cells where the water table stays below ground.
    """

    spec = FigureSpec(
        name="seepage_map",
        title="Seepage areas",
        kind="spatial",
        required_fields=("seepage_areas",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        cmap: str = "Reds",
        **_,
    ) -> Axes:
        ts = last_timestep(sim) if timestep is None else timestep
        mask = np.asarray(sim.field("seepage_areas", timestep=ts), dtype=float)
        render_face_field(
            ax, sim, mask, cmap=cmap, vmin=0.0, vmax=1.0, cbar_label="Seepage (1 = at surface)"
        )
        ax.set_title(f"Seepage areas — {sim.name or sim.sim_id}")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
