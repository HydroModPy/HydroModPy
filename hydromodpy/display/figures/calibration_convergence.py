"""Convergence trace of a calibration session (objective vs iteration)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class CalibrationConvergenceFigure(BaseFigure):
    """Best-so-far and per-iteration objective values over a calibration run."""

    spec = FigureSpec(
        name="calibration_convergence",
        title="Calibration convergence",
        kind="timeseries",
        required_tables=("calibration_iterations",),
        default_figsize=(8.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        objective: str = "objective",
        **_,
    ) -> Axes:
        try:
            df = sim.timeseries(objective, station="_calibration")
        except (KeyError, AttributeError):
            df = None
        if df is None or len(df) == 0:
            if hasattr(sim, "calibration_iterations"):
                df = sim.calibration_iterations  # type: ignore[attr-defined]
        if df is None or len(df) == 0:
            raise ValueError("calibration_convergence: no iteration data available")
        values = np.asarray(getattr(df, "values", df), dtype=float)
        if values.ndim > 1:
            values = values.ravel()
        iters = np.arange(values.size)
        best = np.minimum.accumulate(values)
        ax.plot(iters, values, color="#999", lw=0.8, label="iteration")
        ax.plot(iters, best, color="steelblue", lw=1.5, label="best so far")
        ax.set_xlabel("Iteration")
        ax.set_ylabel(objective)
        ax.grid(True, ls=":", lw=0.4)
        ax.set_title(f"Calibration convergence - {sim.name or sim.sim_id}")
        ax.legend()
        return ax
