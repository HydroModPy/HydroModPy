"""Closure error of the solver mass balance, timestep by timestep.

A groundwater solver reports what it put in and what it took out; the gap
between the two is the only statement it makes about its own convergence. A
run whose error stays inside a fraction of a percent has converged, one whose
error grows as the chronicle advances has not, and no map drawn from it means
anything. This is the figure to look at before any other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.legend_placement import place_legend

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class MassBalanceError(BaseFigure):
    """Percent closure error of one balanced quantity over the run."""

    spec = FigureSpec(
        name="mass_balance_error",
        title="Mass-balance closure error",
        kind="balance",
        required_tables=("mass_balance",),
        default_figsize=(7.5, 4.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        quantity: str = "water",
        tolerance: float = 1.0,
        **_,
    ) -> Axes:
        rows = sim.mass_balance
        if rows.empty:
            raise ValueError(f"mass_balance is empty for sim {sim.sim_id}")
        available = sorted(str(value) for value in rows["quantity"].unique())
        selected = rows.loc[rows["quantity"] == quantity]
        if selected.empty:
            raise ValueError(
                f"mass_balance_error: no '{quantity}' rows for sim {sim.sim_id} "
                f"(available: {', '.join(available)})"
            )

        steps = np.asarray(selected["timestep"], dtype="int64")
        error = np.asarray(selected["percent_error"], dtype="float64")
        order = np.argsort(steps)
        steps, error = steps[order], error[order]

        if tolerance > 0.0:
            ax.axhspan(-tolerance, tolerance, color="#1f6fb4", alpha=0.10, lw=0)
            ax.axhline(tolerance, color="#1f6fb4", lw=0.8, ls="--")
            ax.axhline(-tolerance, color="#1f6fb4", lw=0.8, ls="--", label=f"±{tolerance:g}%")
        ax.axhline(0.0, color="k", lw=1.0)
        ax.plot(steps, error, lw=1.4, color="#2e7d32", marker="o", ms=3, label=quantity)

        worst = float(np.max(np.abs(error))) if error.size else float("nan")
        ax.set_xlabel("Timestep")
        ax.set_ylabel("Closure error (%)")
        ax.grid(True, ls=":", lw=0.4)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}\nworst |error| {worst:.3g}%")
        place_legend(ax, fontsize=8, framealpha=0.9)
        return ax
