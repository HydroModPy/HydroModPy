"""Per-parameter and objective trace across calibration iterations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


_META_COLUMNS = frozenset(
    {
        "iter",
        "iteration",
        "i",
        "session_id",
        "sim_id",
        "params_hash",
        "status",
        "from_cache",
        "duration_s",
        "metrics",
        "parameters",
    }
)


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
        objective: str = "objective",
        session_id: str | None = None,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        iters = getattr(sim, "calibration_iterations", None)
        if iters is None:
            raise ValueError("calibration_trace: simulation has no calibration_iterations")
        df = pd.DataFrame(iters)
        if session_id is not None and "session_id" in df.columns:
            df = df[df["session_id"].astype(str) == str(session_id)]
        if len(df) == 0:
            raise ValueError("calibration_trace: no iteration rows available")

        if parameters is None:
            parameters = [c for c in df.columns if c not in _META_COLUMNS and c != objective]
        if not parameters:
            raise ValueError("calibration_trace: no parameter columns found")

        iter_col = next((c for c in ("iter", "iteration", "i") if c in df.columns), None)
        x = df[iter_col].to_numpy() if iter_col else np.arange(len(df))

        n_panels = len(parameters) + (1 if objective in df.columns else 0)
        fig, axes = plt.subplots(
            n_panels,
            1,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            sharex=True,
            constrained_layout=True,
        )
        axes = np.atleast_1d(axes)
        for ax, name in zip(axes[: len(parameters)], parameters, strict=False):
            y = df[name].to_numpy(dtype=float)
            ax.plot(x, y, color="#888", lw=0.8, zorder=1)
            ax.scatter(x, y, s=12, color="steelblue", zorder=2)
            ax.set_ylabel(name)
            ax.grid(True, ls=":", lw=0.4)
        if objective in df.columns:
            ax = axes[-1]
            y = df[objective].to_numpy(dtype=float)
            ax.plot(x, y, color="#888", lw=0.8, zorder=1)
            ax.scatter(x, y, s=12, color="tab:red", zorder=2)
            ax.set_ylabel(objective)
            ax.grid(True, ls=":", lw=0.4)
        axes[-1].set_xlabel("Iteration")
        fig.suptitle(f"Calibration trace - {sim.name or sim.sim_id}")
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig
