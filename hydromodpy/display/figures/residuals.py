"""Residuals (sim minus obs) as time series and histogram."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display._map_axes import style_date_axis
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


@register
class Residuals(BaseFigure):
    """Time-series of residuals (sim - obs) and their histogram."""

    spec = FigureSpec(
        name="residuals",
        title="Residuals (sim - obs)",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(10.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        **_,
    ) -> Axes:
        # render() is a no-op: residuals need two side-by-side subplots,
        # so plot() is overridden below.
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "residuals has its own plot()",
            ha="center",
            va="center",
        )
        return ax

    def plot(
        self,
        sim: Run,
        *,
        station: str = "_catchment",
        variable: str = "discharge",
        bins: int = 30,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path: str | Path | None = None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        import pandas as pd

        sim_ts = sim.timeseries(variable, station=station)
        obs_df = sim.observed(variable, station=station)
        obs_ts = pd.Series(
            obs_df["value"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(obs_df["datetime"]),
            name=variable,
        )
        joined = pd.concat([sim_ts.rename("sim"), obs_ts.rename("obs")], axis=1).dropna()
        if joined.empty:
            raise ValueError(
                f"residuals: no overlapping sim/obs samples for '{variable}' @ '{station}'"
            )
        residuals = (joined["sim"] - joined["obs"]).to_numpy(dtype=float)

        fig, (ax_ts, ax_hist) = plt.subplots(
            1,
            2,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            gridspec_kw={"width_ratios": [3, 1]},
            constrained_layout=True,
        )

        ax_ts.plot(joined.index, residuals, color="firebrick", lw=0.9)
        ax_ts.axhline(0.0, color="black", lw=0.6)
        ax_ts.set_xlabel("Date")
        ax_ts.set_ylabel(f"residual {axis_label(variable)}")
        ax_ts.grid(True, ls=":", lw=0.4)
        ax_ts.set_title(f"Residuals - {sim.name or sim.sim_id} @ {station}")
        style_date_axis(ax_ts)

        ax_hist.hist(
            residuals,
            bins=bins,
            orientation="horizontal",
            color="firebrick",
            alpha=0.8,
            edgecolor="white",
        )
        ax_hist.axhline(0.0, color="black", lw=0.6)
        mean = float(np.mean(residuals))
        std = float(np.std(residuals))
        ax_hist.set_xlabel("count")
        ax_hist.set_title(f"mean={mean:.3g}\nstd={std:.3g}", fontsize=9)
        ax_hist.grid(True, axis="x", ls=":", lw=0.4)

        if save_path is not None:
            self._save(fig, Path(save_path), dpi=dpi)
        return fig
