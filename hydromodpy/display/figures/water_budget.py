"""Bar chart of the simulated water budget components."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.simulation import SimulationView


@register
class WaterBudget(BaseFigure):
    """Per-component IN/OUT bar chart aggregated over the run."""

    spec = FigureSpec(
        name="water_budget",
        title="Water budget",
        kind="balance",
        required_tables=("budgets",),
        default_figsize=(7.0, 4.5),
    )

    def render(
        self,
        sim: "SimulationView",
        ax: "Axes",
        **_,
    ) -> "Axes":
        df = sim.budget()
        if df.empty:
            ax.text(0.5, 0.5, "no budget data",
                    ha="center", va="center", transform=ax.transAxes)
            return ax
        agg = df.groupby("component")[["flux_in", "flux_out"]].sum()
        agg.plot.bar(ax=ax, color=["#3b8686", "#cf3a3a"])
        ax.set_title(f"Water budget — {sim.name or sim.id}")
        ax.set_ylabel("Flux (m³/d)")
        ax.set_xlabel("")
        ax.tick_params(axis="x", rotation=30)
        return ax
