"""Convergence trace of a calibration session (objective vs iteration)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._trial_diagnostics import trial_table

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
        if df is not None and len(df) > 0:
            label = objective
            values = np.asarray(getattr(df, "values", df), dtype=float)
            iters = np.arange(values.size, dtype="float64")
        else:
            # No objective series was recorded: read the trials, and take the
            # cost BY COLUMN. The frame also carries the session and simulation
            # ids, which are UUIDs, so casting the whole frame raises.
            table = trial_table(sim)
            iters = table.iterations()
            if table.has_objective():
                label, values = table.objective_values()
            else:
                # A bare column of costs, under no name the table knows.
                numeric = table.frame.select_dtypes("number")
                if numeric.shape[1] != 1:
                    raise ValueError(
                        "calibration_convergence: no trial recorded an objective, and "
                        f"the session holds {numeric.shape[1]} numeric columns. Name "
                        "the one to read with objective=."
                    )
                label = str(numeric.columns[0])
                values = np.asarray(numeric.iloc[:, 0], dtype=float)
        if values.ndim > 1:
            values = values.ravel()
        if values.size == 0:
            raise ValueError("calibration_convergence: no iteration data available")
        # A trial that failed publishes no cost. Carrying its NaN forward would
        # flatten the best-so-far curve from that trial on.
        best = np.fmin.accumulate(np.where(np.isnan(values), np.inf, values))
        best[~np.isfinite(best)] = np.nan
        ax.plot(iters, values, color="#999", lw=0.8, label="iteration")
        ax.plot(iters, best, color="steelblue", lw=1.5, label="best so far")
        ax.set_xlabel("Iteration")
        ax.set_ylabel(label)
        ax.grid(True, ls=":", lw=0.4)
        ax.set_title(f"Calibration convergence - {sim.name or sim.sim_id}")
        ax.legend()
        return ax
