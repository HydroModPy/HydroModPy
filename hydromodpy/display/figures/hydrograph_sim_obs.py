"""Discharge hydrograph overlaying simulated and observed series."""

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
        sim_ts = normalize_datetime_series(sim.timeseries(variable, station=station))
        # A line is invisible when a series carries one or two samples (e.g. a
        # steady run with a single stress period); add a marker so the point
        # shows. Dense transient series stay marker-free for a clean look.
        sim_marker = "o" if len(sim_ts) <= 2 else None
        ax.plot(
            sim_ts.index,
            sim_ts.values,
            label="sim",
            color="steelblue",
            lw=1.2,
            marker=sim_marker,
            ms=6,
        )

        # Simulated discharge lives at the catchment-outlet pseudo-station
        # (``station``, default ``_catchment``), while observations come from
        # real gauges keyed by their own id. Fetch every observed gauge and
        # let the per-station loop align each onto the simulation index.
        obs_df = sim.observed(variable)
        has_aligned = False
        for station_id, group in obs_df.groupby("station_id"):
            obs_ts = normalize_datetime_series(
                group.set_index("datetime")["value"].rename(f"obs ({station_id})")
            )
            obs_aligned = observed_on_simulation_index(obs_ts, sim_ts.index).dropna()
            if obs_aligned.empty:
                continue
            has_aligned = True
            obs_marker = "o" if len(obs_aligned) <= 2 else None
            ax.plot(
                obs_aligned.index,
                obs_aligned.values,
                label=f"obs ({station_id})",
                color="black",
                lw=0.9,
                ls="--",
                alpha=0.85,
                marker=obs_marker,
                ms=5,
            )
        if not has_aligned:
            raise ValueError(f"No observed {variable!r} values overlap station {station!r}")

        ax.set_xlabel("Date")
        ax.set_ylabel(axis_label(variable))
        if log_y:
            ax.set_yscale("log")
        ax.set_title(f"Hydrograph sim vs obs - {sim.name or sim.sim_id} @ {station}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend(fontsize=13, framealpha=0.94)
        style_date_axis(ax)
        return ax
