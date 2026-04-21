"""Spatial difference between two simulations on the same mesh."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display._ugrid import last_timestep, render_face_field
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.simulation import SimulationView


@register
class DifferenceMap(BaseFigure):
    """Map of ``sim - reference`` for one field at one timestep.

    Both simulations must share the same mesh — the figure does not perform
    any interpolation. Pass a second :class:`SimulationView` via ``reference``.
    """

    spec = FigureSpec(
        name="difference_map",
        title="Difference map",
        kind="comparison",
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: "SimulationView",
        ax: "Axes",
        *,
        reference: "SimulationView | None" = None,
        field: str = "head",
        timestep: int | None = None,
        cmap: str = "RdBu_r",
        **_,
    ) -> "Axes":
        if reference is None:
            raise ValueError("difference_map: 'reference' simulation required")
        ts = last_timestep(sim) if timestep is None else timestep
        a = np.asarray(sim.field(field, timestep=ts)).ravel()
        b = np.asarray(reference.field(field, timestep=ts)).ravel()
        if a.shape != b.shape:
            raise ValueError(
                f"difference_map: incompatible mesh — sim has {a.size} faces, "
                f"reference has {b.size}"
            )
        diff = a - b
        vmax = float(np.nanmax(np.abs(diff))) or 1.0
        render_face_field(
            ax, sim, diff, cmap=cmap, vmin=-vmax, vmax=vmax,
            cbar_label=f"Δ {field}",
        )
        ax.set_title(f"Δ {field} — {sim.id} − {reference.id}")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
