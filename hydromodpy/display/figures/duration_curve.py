"""Flow-duration curve at a station."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class DurationCurveFigure(BaseFigure):
    """Exceedance-probability (flow-duration) curve for one station."""

    spec = FigureSpec(
        name="duration_curve",
        title="Flow-duration curve",
        kind="timeseries",
        required_tables=("timeseries",),
        default_figsize=(7.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        station: str = "_catchment",
        variable: str = "discharge",
        log_y: bool = True,
        **_,
    ) -> Axes:
        ts = sim.timeseries(variable, station=station)
        values = np.asarray(ts.values, dtype=float)
        values = values[~np.isnan(values)]
        if values.size == 0:
            raise ValueError(f"duration_curve: no data for '{variable}' at '{station}'")
        sorted_vals = np.sort(values)[::-1]
        exceedance = np.arange(1, sorted_vals.size + 1) / (sorted_vals.size + 1) * 100.0
        ax.plot(exceedance, sorted_vals, color="steelblue", lw=1.2)
        ax.set_xlabel("Exceedance probability (%)")
        ax.set_ylabel(axis_label(variable))
        if log_y:
            ax.set_yscale("log")
        ax.set_xlim(0, 100)
        ax.grid(True, ls=":", lw=0.4)
        ax.set_title(f"Duration curve - {sim.name or sim.sim_id} @ {station}")
        return ax
