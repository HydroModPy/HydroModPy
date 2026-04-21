"""Seasonal box-plot of a timeseries grouped by month."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.simulation import SimulationView


_MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


@register
class SeasonalBoxplotFigure(BaseFigure):
    """Monthly distribution of a variable as a box-plot."""

    spec = FigureSpec(
        name="seasonal_boxplot",
        title="Seasonal box-plot",
        kind="timeseries",
        required_tables=("timeseries",),
        default_figsize=(8.0, 4.5),
    )

    def render(
        self,
        sim: "SimulationView",
        ax: "Axes",
        *,
        station: str = "_catchment",
        variable: str = "discharge",
        **_,
    ) -> "Axes":
        ts = sim.timeseries(variable, station=station)
        index = ts.index
        try:
            months = index.month
        except AttributeError:
            months = np.asarray([getattr(ts_idx, "month", 1) for ts_idx in index])

        data = [np.asarray(ts.values, dtype=float)[months == m] for m in range(1, 13)]
        data = [x[~np.isnan(x)] for x in data]
        positions = np.arange(1, 13)
        ax.boxplot(
            data,
            positions=positions,
            widths=0.6,
            showfliers=False,
            patch_artist=True,
            boxprops={"facecolor": "#cde"},
            medianprops={"color": "black"},
        )
        ax.set_xticks(positions)
        ax.set_xticklabels(_MONTH_NAMES)
        ax.set_ylabel(axis_label(variable))
        ax.set_title(f"Seasonal distribution — {sim.name or sim.sim_id} @ {station}")
        ax.grid(True, axis="y", ls=":", lw=0.4)
        return ax
