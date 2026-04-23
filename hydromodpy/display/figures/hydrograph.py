"""Discharge hydrograph at a chosen station."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display._map_axes import style_date_axis
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class Hydrograph(BaseFigure):
    """Time series of discharge at a station, with optional observed series."""

    spec = FigureSpec(
        name="hydrograph",
        title="Discharge hydrograph",
        kind="timeseries",
        required_tables=("timeseries",),
        default_figsize=(8.0, 4.5),
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
        try:
            ts = sim.timeseries(variable, station=station)
        except KeyError as exc:
            raise KeyError(
                f"hydrograph: no '{variable}' series at station '{station}' for sim {sim.sim_id}"
            ) from exc
        ax.plot(ts.index, ts.values, label="sim", color="steelblue", lw=1.2)
        ax.set_xlabel("Date")
        ax.set_ylabel(f"{variable} (m³/s)")
        if log_y:
            ax.set_yscale("log")
        ax.set_title(f"Hydrograph - {sim.name or sim.sim_id} @ {station}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend()
        style_date_axis(ax)
        return ax
