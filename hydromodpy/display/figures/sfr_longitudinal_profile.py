"""Longitudinal profile of one SFR quantity along the reach numbering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figures.sfr_reach_timeseries import STATE_UNITS, sfr_reach_stations

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class SfrLongitudinalProfile(BaseFigure):
    """One SFR quantity per reach at a chosen time step (default: the last).

    The x axis is the reach number ``ifno`` (strictly downstream-increasing by
    construction), so the profile reads head -> outlet left to right; the routed
    ``downstream_flow`` accumulates along it.
    """

    spec = FigureSpec(
        name="sfr_longitudinal_profile",
        title="SFR longitudinal profile",
        kind="timeseries",
        required_tables=("timeseries",),
        default_figsize=(8.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: str = "downstream_flow",
        timestep: int = -1,
        **_,
    ) -> Axes:
        triples = sfr_reach_stations(sim, variable)
        if not triples:
            raise KeyError(
                f"sfr_longitudinal_profile: no SFR '{variable}' series for sim {sim.sim_id}"
            )
        network_id = triples[0][0]
        reaches: list[int] = []
        values: list[float] = []
        stamp = None
        for _, ifno, station in triples:
            series = sim.timeseries(variable, station=station)
            reaches.append(ifno)
            values.append(float(series.iloc[timestep]))
            stamp = series.index[timestep]

        ax.plot(reaches, values, color="steelblue", lw=1.2, marker="o", ms=4)
        ax.set_xlabel("reach number (downstream-increasing)")
        ax.set_ylabel(f"{variable} ({STATE_UNITS.get(variable, 'm³/s')})")
        ax.set_title(
            f"SFR {variable} profile - {sim.name or sim.sim_id} @ {network_id}"
            + (f" ({stamp:%Y-%m-%d})" if stamp is not None else "")
        )
        ax.grid(True, ls=":", lw=0.4)
        return ax
