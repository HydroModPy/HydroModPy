"""Per-parameter and objective trace across calibration iterations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._trial_diagnostics import trial_table

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


@register
class CalibrationTraceFigure(BaseFigure):
    """One line+scatter trace per parameter, plus a panel for the objective."""

    spec = FigureSpec(
        name="calibration_trace",
        title="Calibration parameter trace",
        kind="timeseries",
        required_tables=("calibration_iterations",),
        default_figsize=(8.0, 9.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        **_,
    ) -> Axes:
        # render() is a no-op: the trace needs its own stack of subplots,
        # so plot() is overridden below.
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "calibration_trace has its own plot()",
            ha="center",
            va="center",
        )
        return ax

    def plot(
        self,
        sim: Run,
        *,
        parameters: list[str] | None = None,
        objective: str | None = None,
        session_id: str | None = None,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        import numpy as np

        table = trial_table(sim, session_id=session_id)
        names = list(parameters) if parameters is not None else list(table.parameters)
        if not names:
            raise ValueError(
                "calibration_trace: no parameter columns found; the session recorded "
                f"{', '.join(sorted(table.frame.columns))}"
            )
        traces = [table.parameter_values(name) for name in names]

        x = table.iterations()
        cost_name, cost = (
            table.objective_values(objective)
            if objective is not None or table.has_objective()
            else (None, None)
        )

        n_panels = len(traces) + (1 if cost_name is not None else 0)
        fig, axes = plt.subplots(
            n_panels,
            1,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            sharex=True,
            constrained_layout=True,
        )
        axes = np.atleast_1d(axes)
        for ax, (name, y) in zip(axes, traces, strict=False):
            ax.plot(x, y, color="#888", lw=0.8, zorder=1)
            ax.scatter(x, y, s=12, color="steelblue", zorder=2)
            ax.set_ylabel(name)
            ax.grid(True, ls=":", lw=0.4)
        if cost_name is not None:
            ax = axes[-1]
            ax.plot(x, cost, color="#888", lw=0.8, zorder=1)
            ax.scatter(x, cost, s=12, color="tab:red", zorder=2)
            ax.set_ylabel(cost_name)
            ax.grid(True, ls=":", lw=0.4)
        axes[-1].set_xlabel("Iteration")
        fig.suptitle(f"Calibration trace - {sim.name or sim.sim_id}")
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig
