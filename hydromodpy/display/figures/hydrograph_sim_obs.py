"""Discharge hydrograph overlaying simulated and observed series."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display._map_axes import style_date_axis
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class HydrographSimObs(BaseFigure):
    """Time series of discharge sim and obs on the same axis."""

    spec = FigureSpec(
        name="hydrograph_sim_obs",
        title="Discharge hydrograph (sim vs obs)",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(8.5, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        station: str = "_catchment",
        variable: str = "discharge",
        log_y: bool = False,
        **_,
    ) -> Axes:
        sim_ts = sim.timeseries(variable, station=station)
        ax.plot(
            sim_ts.index,
            sim_ts.values,
            label="sim",
            color="steelblue",
            lw=1.2,
        )

        obs_df = sim.observed(variable, station=station)
        for station_id, group in obs_df.groupby("station_id"):
            ax.plot(
                group["datetime"].values,
                group["value"].values,
                label=f"obs ({station_id})",
                color="black",
                lw=0.9,
                ls="--",
                alpha=0.85,
            )

        ax.set_xlabel("Date")
        ax.set_ylabel(axis_label(variable))
        if log_y:
            ax.set_yscale("log")
        ax.set_title(f"Hydrograph sim vs obs - {sim.name or sim.sim_id} @ {station}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend()
        style_date_axis(ax)
        return ax
