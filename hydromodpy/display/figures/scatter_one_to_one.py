"""Scatter 1:1 plot of simulated vs observed values.

The scores printed are the ones the run recorded on ``[metrics] window``
(:mod:`hydromodpy.display.figures._run_score`), never computed again on the
drawn pairs. The pairs that score read are drawn in color, the others in gray.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.units.labels import axis_label, station_label
from hydromodpy.display.figure import BaseFigure, FigureNotApplicable, FigureSpec, run_suffix
from hydromodpy.display.figure_options import ObservedStation, Station, Variable
from hydromodpy.display.figures._observed import observed_series
from hydromodpy.display.figures._run_score import run_score
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    normalize_datetime_series,
    run_period_start,
    time_method_for,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run.view import Run


class ScatterOneToOne(BaseFigure):
    """Sim vs obs scatter with 1:1 line and the scores the run recorded."""

    spec = FigureSpec(
        name="scatter_one_to_one",
        title="Sim vs obs scatter (1:1)",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(5.5, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        station: Station = CATCHMENT,
        variable: Variable = "discharge",
        observed_station: ObservedStation = None,
        **_,
    ) -> Axes:
        import pandas as pd

        sim_ts = normalize_datetime_series(sim.timeseries(variable, station=station))
        try:
            obs_ts, obs_station = observed_series(
                sim, variable, station=observed_station, label="scatter_one_to_one"
            )
        except ValueError as exc:
            raise FigureNotApplicable(str(exc)) from exc
        # Paired as the run's score pairs them: a flux observed day by day is
        # averaged over each simulated period, a state read at its stamp.
        first_start = run_period_start(sim, sim_ts.index)
        joined = align_observed_simulated(
            obs_ts, sim_ts, method=time_method_for(variable), start=first_start
        )
        if joined.empty:
            raise FigureNotApplicable(
                f"scatter_one_to_one: the simulated {variable!r} at {station!r} and the "
                f"observed one at {obs_station!r} share no timestamp"
            )
        score = run_score(sim, stations=[obs_station], variable=variable)
        scored = np.ones(len(joined), dtype=bool)
        if score is not None:
            on_grid = pd.Series(
                score.scored(pd.DatetimeIndex(sim_ts.index), first_start), index=sim_ts.index
            )
            scored = on_grid.reindex(joined.index, fill_value=False).to_numpy(dtype=bool)
        s = joined["sim"].to_numpy(dtype=float)
        o = joined["obs"].to_numpy(dtype=float)

        if score is not None and not scored.all():
            ax.scatter(
                o[~scored],
                s[~scored],
                s=14,
                color="0.7",
                alpha=0.7,
                edgecolor="none",
                label="not scored",
            )
        ax.scatter(o[scored], s[scored], s=18, color="steelblue", alpha=0.7, edgecolor="none")
        lo = float(min(o.min(), s.min()))
        hi = float(max(o.max(), s.max()))
        ax.plot([lo, hi], [lo, hi], color="black", lw=0.8, ls="--", label="1:1")

        if score is None:
            text = "the run holds no score of this series"
        else:
            named = [
                f"{label} {score.values[metric]:{spec}}"
                for metric, label, spec in (
                    ("nse", "NSE", ".3f"),
                    ("rmse", "RMSE", ".3g"),
                    ("bias", "BIAS", ".3g"),
                )
                if metric in score.values
            ]
            text = "\n".join([*named, score.window_line()])
        ax.text(
            0.04,
            0.96,
            text,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none"},
        )

        label = axis_label(variable)
        ax.set_xlabel(f"observed {label}")
        ax.set_ylabel(f"simulated {label}")
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_title(f"1:1{run_suffix(sim)} @ {station_label(station)}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend(loc="lower right")
        return ax
