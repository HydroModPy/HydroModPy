"""Convergence trace of a calibration session (objective vs iteration)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec, run_suffix
from hydromodpy.display.figure_options import ObjectiveName
from hydromodpy.display.figures._trial_diagnostics import no_trial_reason, trial_table

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.session.view import Session


class CalibrationConvergenceFigure(BaseFigure):
    """Best-so-far and per-iteration objective values over a calibration run."""

    spec = FigureSpec(
        name="calibration_convergence",
        title="Calibration convergence",
        kind="timeseries",
        subject="session",
        default_figsize=(8.0, 4.5),
    )

    def unavailable_reason(self, session: Session) -> str | None:
        """Refuse a session that recorded no trial, before drawing."""
        return no_trial_reason(session)

    def render(
        self,
        session: Session,
        ax: Axes,
        *,
        objective: ObjectiveName = None,
        **_,
    ) -> Axes:
        table = trial_table(session)
        iters = table.iterations()
        if objective is not None or table.has_objective():
            label, values = table.cost_values(objective)
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
        ax.set_title(f"Calibration convergence{run_suffix(session)}")
        ax.legend()
        return ax
