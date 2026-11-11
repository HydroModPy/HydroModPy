"""Ensemble envelope band for a RunSet.

The subject is a ``RunSet``. A member without the series is left out while
drawing, and a set with no member that has it is an error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import numpy as np

from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.units.labels import axis_label, station_label
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_options import Opt, Station, Variable

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run.group import RunSet


class EnsembleBandFigure(BaseFigure):
    """Median and a quantile band across an ensemble of simulations."""

    spec = FigureSpec(
        name="ensemble_band",
        title="Ensemble envelope",
        kind="comparison",
        subject="runset",
        default_figsize=(8.5, 4.5),
    )

    def render(
        self,
        runset: RunSet,
        ax: Axes,
        *,
        station: Station = CATCHMENT,
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

        series: list[pd.Series] = []
        for member in runset:
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
