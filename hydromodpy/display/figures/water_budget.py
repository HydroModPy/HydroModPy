"""Bar chart of the simulated solver budget components."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class WaterBudget(BaseFigure):
    """Per-component IN/OUT bar chart aggregated over the full model domain."""

    spec = FigureSpec(
        name="water_budget",
        title="Water budget",
        kind="balance",
        required_tables=("budgets",),
        default_figsize=(7.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        **_,
    ) -> Axes:
        df = sim.budget()
        if df.empty:
            ax.text(0.5, 0.5, "no budget data", ha="center", va="center", transform=ax.transAxes)
            return ax
        agg = df.groupby("component")[["flux_in", "flux_out"]].sum()
        agg.plot.bar(ax=ax, color=["#3b8686", "#cf3a3a"])
        unit = _budget_unit_label(df)
        ax.set_title(f"Solver budget by component - {sim.name or sim.sim_id}")
        ax.set_ylabel(
            f"Sum of stored timestep rates ({unit})"
            if unit
            else "Sum of stored timestep rates"
        )
        ax.set_xlabel("")
        ax.tick_params(axis="x", rotation=30)
        return ax


def _budget_unit_label(df) -> str:
    if "unit" not in df:
        return ""
    try:
        units = [str(value) for value in df["unit"].dropna().unique() if str(value).strip()]
    except Exception:
        return ""
    return units[0] if len(units) == 1 else "mixed units"
