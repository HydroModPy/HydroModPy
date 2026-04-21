"""Side-by-side spatial comparison of two simulations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display._ugrid import last_timestep, render_face_field
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.simulation import SimulationView


@register
class SideBySideMapFigure(BaseFigure):
    """Draw the same field from two simulations on two axes with a shared range."""

    spec = FigureSpec(
        name="side_by_side",
        title="Side-by-side map",
        kind="comparison",
        default_figsize=(11.0, 5.0),
    )

    def render(
        self,
        sim: "SimulationView",
        ax: "Axes",
        *,
        reference: "SimulationView | None" = None,
        field: str = "head",
        timestep: int | None = None,
        cmap: str = "viridis",
        **_,
    ) -> "Axes":
        if reference is None:
            raise ValueError("side_by_side: 'reference' simulation required")
        ts = last_timestep(sim) if timestep is None else timestep
        a = np.asarray(sim.field(field, timestep=ts)).ravel()
        b = np.asarray(reference.field(field, timestep=ts)).ravel()
        vmin = float(np.nanmin([a.min(), b.min()]))
        vmax = float(np.nanmax([a.max(), b.max()]))
        render_face_field(
            ax, sim, a, cmap=cmap, vmin=vmin, vmax=vmax,
            cbar_label=axis_label(field),
        )
        ax.set_title(sim.name or sim.sim_id)
        return ax

    def plot(
        self,
        sim: "SimulationView",
        *,
        reference: "SimulationView | None" = None,
        field: str = "head",
        timestep: int | None = None,
        cmap: str = "viridis",
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> "MplFigure":
        import matplotlib.pyplot as plt

        if reference is None:
            raise ValueError("side_by_side: 'reference' simulation required")

        fig, axes = plt.subplots(
            1, 2,
            figsize=figsize or (self.spec.default_figsize[0], self.spec.default_figsize[1]),
            dpi=dpi,
            constrained_layout=True,
        )
        ts = last_timestep(sim) if timestep is None else timestep
        a = np.asarray(sim.field(field, timestep=ts)).ravel()
        b = np.asarray(reference.field(field, timestep=ts)).ravel()
        vmin = float(np.nanmin([a.min(), b.min()]))
        vmax = float(np.nanmax([a.max(), b.max()]))
        render_face_field(
            axes[0], sim, a, cmap=cmap, vmin=vmin, vmax=vmax,
            cbar_label=axis_label(field),
        )
        axes[0].set_title(sim.name or sim.sim_id)
        render_face_field(
            axes[1], reference, b, cmap=cmap, vmin=vmin, vmax=vmax,
            cbar_label=axis_label(field),
        )
        axes[1].set_title(reference.name or reference.id)
        fig.suptitle(f"Side-by-side {field}")
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig
