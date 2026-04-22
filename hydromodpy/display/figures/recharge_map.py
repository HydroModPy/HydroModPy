"""Mean recharge map per cell."""

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
class RechargeMap(BaseFigure):
    """Per-cell recharge at a single timestep.

    Reads the ``recharge`` field from the Zarr store. If ``timestep`` is None
    the latest available step is used.
    """

    spec = FigureSpec(
        name="recharge_map",
        title="Recharge map",
        kind="spatial",
        required_fields=("recharge",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: "Run",
        ax: "Axes",
        *,
        timestep: int | None = None,
        cmap: str = "YlGnBu",
        **_,
    ) -> "Axes":
        ts = last_timestep(sim) if timestep is None else timestep
        rch = np.asarray(sim.field("recharge", timestep=ts))
        if rch.ndim == 2:
            rch = rch[0]
        render_face_field(ax, sim, rch, cmap=cmap, cbar_label="Recharge (m/d)")
        ax.set_title(f"Recharge — {sim.name or sim.sim_id}")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
