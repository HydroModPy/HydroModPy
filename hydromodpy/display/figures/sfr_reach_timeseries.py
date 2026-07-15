"""Time series of one SFR reach quantity (stage, depth, flows)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import style_date_axis

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

STATE_UNITS = {"stage": "m", "depth": "m"}


def sfr_reach_stations(sim: Run, variable: str) -> list[tuple[str, int, str]]:
    """Return the ``(network_id, reach_ifno, station_id)`` triples for one variable.

    SFR series land under ``station_id = sfr:<network>:<reach>``; the triples are
    sorted by reach number so a longitudinal sweep follows the routing order.
    """
    triples: list[tuple[str, int, str]] = []
    for station in sim.stations(variable):
        parts = str(station).split(":")
        if len(parts) != 3 or parts[0] != "sfr":
            continue
        try:
            triples.append((parts[1], int(parts[2]), station))
        except ValueError:
            continue
    triples.sort(key=lambda item: (item[0], item[1]))
    return triples


@register
class SfrReachTimeseries(BaseFigure):
    """Time series of one quantity on one SFR reach.

    Defaults to the most downstream reach (highest ``ifno``, the network gauge)
    and the routed ``downstream_flow``.
    """

    spec = FigureSpec(
        name="sfr_reach_timeseries",
        title="SFR reach time series",
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
        reach: int | None = None,
        log_y: bool = False,
        **_,
    ) -> Axes:
        triples = sfr_reach_stations(sim, variable)
        if not triples:
            raise KeyError(f"sfr_reach_timeseries: no SFR '{variable}' series for sim {sim.sim_id}")
        if reach is None:
            network_id, ifno, station = triples[-1]
        else:
            matches = [t for t in triples if t[1] == int(reach)]
            if not matches:
                raise KeyError(
                    f"sfr_reach_timeseries: no reach {reach} with '{variable}' for sim {sim.sim_id}"
                )
            network_id, ifno, station = matches[0]

        ts = sim.timeseries(variable, station=station)
        ax.plot(ts.index, ts.values, color="steelblue", lw=1.2, label=f"reach {ifno}")
        ax.set_xlabel("Date")
        ax.set_ylabel(f"{variable} ({STATE_UNITS.get(variable, 'm³/s')})")
        if log_y:
            ax.set_yscale("log")
        ax.set_title(f"SFR {variable} - {sim.name or sim.sim_id} @ {network_id}:{ifno}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend(fontsize=13, framealpha=0.94)
        style_date_axis(ax)
        return ax
