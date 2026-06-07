"""Ensemble envelope band for a SimulationGroup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes


@register
class EnsembleBandFigure(BaseFigure):
    """Median + inter-quartile band across an ensemble of simulations."""

    spec = FigureSpec(
        name="ensemble_band",
        title="Ensemble envelope",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(8.5, 4.5),
    )

    def render(
        self,
        sim: Any,
        ax: Axes,
        *,
        station: str = "_catchment",
        variable: str = "discharge",
        observed: Any | None = None,
        q_low: float = 0.1,
        q_high: float = 0.9,
        **_,
    ) -> Axes:
        import pandas as pd

        # ``sim`` is expected to be a SimulationGroup (iterable of Run).
        if not hasattr(sim, "__iter__"):
            raise TypeError("ensemble_band: 'sim' must be a SimulationGroup (iterable)")
        series: list[pd.Series] = []
        for member in sim:
            try:
                series.append(member.timeseries(variable, station=station))
            except KeyError:
                continue
        if not series:
            raise ValueError(f"ensemble_band: no '{variable}' series at '{station}' in group")
        df = pd.concat(series, axis=1)
        median = df.median(axis=1)
        low = df.quantile(q_low, axis=1)
        high = df.quantile(q_high, axis=1)
        ax.fill_between(
            median.index,
            low,
            high,
            alpha=0.3,
            color="steelblue",
            label=f"q{int(q_low * 100)}-q{int(q_high * 100)}",
        )
        ax.plot(median.index, median, color="navy", lw=1.0, label="median")
        if observed is not None:
            ax.plot(
                np.asarray(observed.index),
                np.asarray(observed.values),
                color="black",
                lw=0.8,
                ls="--",
                label="observed",
            )
        ax.set_xlabel("Date")
        ax.set_ylabel(axis_label(variable))
        ax.set_title(f"Ensemble envelope - {len(series)} runs @ {station}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend()
        return ax
