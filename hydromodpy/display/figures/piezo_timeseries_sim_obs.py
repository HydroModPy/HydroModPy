"""Piezometric head timeseries overlaying simulated and observed series."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display._map_axes import style_date_axis
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.results.time_alignment import (
    normalize_datetime_series,
    observed_on_simulation_index,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class PiezoTimeseriesSimObs(BaseFigure):
    """Head timeseries at one piezometer with simulated and observed overlay."""

    spec = FigureSpec(
        name="piezo_timeseries_sim_obs",
        title="Piezometric head (sim vs obs)",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(8.5, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        station: str,
        variable: str = "head",
        **_,
    ) -> Axes:
        sim_ts = normalize_datetime_series(sim.timeseries(variable, station=station))
        ax.plot(
            sim_ts.index,
            sim_ts.values,
            label="sim",
            color="darkorange",
            lw=1.2,
        )

        obs_df = sim.observed(variable, station=station)
        obs_ts = normalize_datetime_series(obs_df.set_index("datetime")["value"].rename("obs"))
        obs_aligned = observed_on_simulation_index(obs_ts, sim_ts.index).dropna()
        if obs_aligned.empty:
            raise ValueError(f"No observed {variable!r} values overlap station {station!r}")
        ax.plot(
            obs_aligned.index,
            obs_aligned.values,
            label="obs",
            color="black",
            lw=0.9,
            ls="--",
            marker="o",
            ms=3.0,
            alpha=0.85,
        )

        ax.set_xlabel("Date")
        ax.set_ylabel(axis_label(variable))
        ax.set_title(f"Piezo sim vs obs - {sim.name or sim.sim_id} @ {station}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend()
        style_date_axis(ax)
        return ax
