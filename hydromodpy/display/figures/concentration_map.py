"""Solute concentration map."""

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
class ConcentrationMap(BaseFigure):
    """Per-cell solute concentration at one timestep."""

    spec = FigureSpec(
        name="concentration_map",
        title="Concentration",
        kind="spatial",
        required_fields=("concentration",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        layer: int | None = None,
        cmap: str = "plasma",
        **_,
    ) -> Axes:
        ts = last_timestep(sim) if timestep is None else timestep
        c = np.asarray(sim.field("concentration", timestep=ts, layer=layer))
        if c.ndim == 2:
            c = c[0]
        render_face_field(ax, sim, c, cmap=cmap, cbar_label=self.axis_label_for("concentration"))
        ax.set_title(f"Concentration - {sim.name or sim.sim_id}")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
