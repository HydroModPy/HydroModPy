"""Ensemble envelope band for a RunSet."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import numpy as np

from hydromodpy.core.units.labels import CATCHMENT_OUTLET_STATION, axis_label, station_label
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_options import Opt, Station, Variable
from hydromodpy.display.figure_registry import register

if TYPE_CHECKING:
    from matplotlib.axes import Axes


@register
class EnsembleBandFigure(BaseFigure):
    """Median and a quantile band across an ensemble of simulations."""

    spec = FigureSpec(
        name="ensemble_band",
        title="Ensemble envelope",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(8.5, 4.5),
    )

    def unavailable_reason(self, sim: Any) -> str | None:
        """Require a set of runs: one run has no envelope.

        A ``RunSet`` is checked member by member while drawing, where a member
        without the series is left out.
        """
        if not hasattr(sim, "__iter__"):
            return "draws the envelope of several runs, and a run is one; pass a RunSet"
        return None

    def render(
        self,
        sim: Any,
        ax: Axes,
        *,
        station: Station = CATCHMENT_OUTLET_STATION,
        variable: Variable = "discharge",
        observed: Annotated[
            Any | None,
            Opt(
                "Observed series drawn over the band, a pandas Series indexed by date.",
                python_only=True,
            ),
        ] = None,
        q_low: Annotated[float, Opt("Quantile of the lower edge of the band.", unit="-")] = 0.1,
        q_high: Annotated[float, Opt("Quantile of the upper edge of the band.", unit="-")] = 0.9,
        **_,
    ) -> Axes:
        import pandas as pd

        # ``sim`` is expected to be a RunSet (iterable of Run).
        if not hasattr(sim, "__iter__"):
            raise TypeError("ensemble_band: 'sim' must be a RunSet (iterable)")
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
        ax.set_title(f"Ensemble envelope - {len(series)} runs @ {station_label(station)}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend()
        return ax
