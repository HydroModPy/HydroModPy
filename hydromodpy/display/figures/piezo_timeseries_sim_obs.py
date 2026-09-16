"""Piezometric head timeseries overlaying simulated and observed series.

The two halves of the comparison are written by two different producers and do
not meet under the same name. A head sampled at a declared observation point
lands under station ``obs:<point id>`` and the field name it was sampled from,
while a measured chronicle lands under the station id of its data family and
the name that family gives the measurement, ``groundwater_level``. The figure
bridges the two rather than asking the run to rename anything: the observed
station defaults to the simulated one with its ``obs:`` marker removed, and the
observed variable can be named when it differs from the simulated field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import style_date_axis
from hydromodpy.results.derive.time_alignment import (
    normalize_datetime_series,
    observed_on_simulation_index,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

OBSERVATION_POINT_PREFIX = "obs:"
"""Marker a declared observation point carries on the station it samples."""


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
        observed_station: str | None = None,
        observed_variable: str | None = None,
        **_,
    ) -> Axes:
        obs_station = (
            observed_station
            if observed_station is not None
            else station.removeprefix(OBSERVATION_POINT_PREFIX)
        )
        obs_variable = observed_variable if observed_variable is not None else variable

        sim_ts = normalize_datetime_series(sim.timeseries(variable, station=station))
        ax.plot(
            sim_ts.index,
            sim_ts.values,
            label="sim",
            color="darkorange",
            lw=1.2,
        )

        obs_df = sim.observed(obs_variable, station=obs_station)
        obs_ts = normalize_datetime_series(obs_df.set_index("datetime")["value"].rename("obs"))
        obs_aligned = observed_on_simulation_index(obs_ts, sim_ts.index).dropna()
        if obs_aligned.empty:
            raise ValueError(
                f"No observed {obs_variable!r} values at station {obs_station!r} overlap "
                f"the simulated {variable!r} series at station {station!r}"
            )
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
