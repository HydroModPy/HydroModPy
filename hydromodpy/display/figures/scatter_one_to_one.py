"""Scatter 1:1 plot of simulated vs observed values."""

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
class ScatterOneToOne(BaseFigure):
    """Sim vs obs scatter with 1:1 line and goodness-of-fit metrics."""

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
        station: str = "_catchment",
        variable: str = "discharge",
        **_,
    ) -> Axes:
        sim_ts = sim.timeseries(variable, station=station)
        obs_df = sim.observed(variable, station=station)
        import pandas as pd

        obs_ts = pd.Series(
            obs_df["value"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(obs_df["datetime"]),
            name=variable,
        )

        joined = pd.concat([sim_ts.rename("sim"), obs_ts.rename("obs")], axis=1).dropna()
        if joined.empty:
            raise ValueError(
                f"scatter_one_to_one: no overlapping sim/obs samples for '{variable}' @ '{station}'"
            )
        s = joined["sim"].to_numpy(dtype=float)
        o = joined["obs"].to_numpy(dtype=float)

        ax.scatter(o, s, s=18, color="steelblue", alpha=0.7, edgecolor="none")
        lo = float(min(o.min(), s.min()))
        hi = float(max(o.max(), s.max()))
        ax.plot([lo, hi], [lo, hi], color="black", lw=0.8, ls="--", label="1:1")

        rmse = float(np.sqrt(np.mean((s - o) ** 2)))
        bias = float(np.mean(s - o))
        denom = float(np.sum((o - o.mean()) ** 2))
        nse = float(1.0 - np.sum((s - o) ** 2) / denom) if denom > 0 else float("nan")
        text = f"n={len(s)}\nRMSE={rmse:.3g}\nBIAS={bias:.3g}\nNSE={nse:.3f}"
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
        ax.set_title(f"1:1 - {sim.name or sim.sim_id} @ {station}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend(loc="lower right")
        return ax
