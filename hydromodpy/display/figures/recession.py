"""Low-flow recession curve analysis."""

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
class RecessionCurveFigure(BaseFigure):
    """Recession limbs extracted from a discharge series, log-y axis."""

    spec = FigureSpec(
        name="recession",
        title="Recession analysis",
        kind="timeseries",
        required_tables=("timeseries",),
        default_figsize=(8.0, 4.5),
    )

    def render(
        self,
        sim: "Run",
        ax: "Axes",
        *,
        station: str = "_catchment",
        variable: str = "discharge",
        min_length: int = 5,
        **_,
    ) -> "Axes":
        ts = sim.timeseries(variable, station=station)
        values = np.asarray(ts.values, dtype=float)
        n = values.size
        if n == 0:
            raise ValueError(f"recession: empty series for '{variable}' @ '{station}'")

        # Walk the series and collect monotonically-decreasing limbs.
        limbs: list[np.ndarray] = []
        start = 0
        for i in range(1, n):
            if values[i] > values[i - 1] or np.isnan(values[i]):
                if i - start >= min_length:
                    limbs.append(values[start:i])
                start = i
        if n - start >= min_length:
            limbs.append(values[start:n])

        for limb in limbs:
            ax.plot(np.arange(limb.size), limb, color="#444", lw=0.8, alpha=0.7)

        ax.set_yscale("log")
        ax.set_xlabel("Days since start of recession")
        ax.set_ylabel(axis_label(variable))
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title(
            f"Recession curves — {sim.name or sim.sim_id} @ {station} ({len(limbs)} limbs)"
        )
        return ax
