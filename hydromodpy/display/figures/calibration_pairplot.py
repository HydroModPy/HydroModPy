"""Parameter-pair scatter grid from a calibration session."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


@register
class CalibrationPairplotFigure(BaseFigure):
    """Scatter matrix of calibrated parameter values, colored by objective."""

    spec = FigureSpec(
        name="calibration_pairplot",
        title="Calibration parameter pairs",
        kind="comparison",
        required_tables=("calibration_iterations",),
        default_figsize=(8.0, 8.0),
    )

    def render(
        self,
        sim: "Run",
        ax: "Axes",
        **_,
    ) -> "Axes":
        # render() is a no-op; the pairplot needs its own grid, so plot() is overridden.
        ax.set_axis_off()
        ax.text(
            0.5, 0.5,
            "calibration_pairplot has its own plot()",
            ha="center", va="center",
        )
        return ax

    def plot(
        self,
        sim: "Run",
        *,
        parameters: list[str] | None = None,
        objective: str = "objective",
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> "MplFigure":
        import matplotlib.pyplot as plt
        import pandas as pd

        iters = getattr(sim, "calibration_iterations", None)
        if iters is None:
            raise ValueError(
                "calibration_pairplot: simulation has no calibration_iterations"
            )
        df = pd.DataFrame(iters)
        if parameters is None:
            parameters = [c for c in df.columns if c not in {objective, "iter", "i"}]
        if len(parameters) < 2:
            raise ValueError(
                "calibration_pairplot: need at least two parameter columns"
            )
        obj = df[objective].to_numpy(dtype=float) if objective in df.columns else None

        n = len(parameters)
        fig, axes = plt.subplots(
            n, n,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        for i, pi in enumerate(parameters):
            for j, pj in enumerate(parameters):
                ax = axes[i, j] if n > 1 else axes
                if i == j:
                    ax.hist(df[pi].to_numpy(dtype=float), bins=20, color="steelblue")
                else:
                    sc = ax.scatter(
                        df[pj].to_numpy(dtype=float),
                        df[pi].to_numpy(dtype=float),
                        c=obj,
                        cmap="viridis",
                        s=8,
                    )
                    if i == n - 1 and j == n - 1 and obj is not None:
                        fig.colorbar(sc, ax=axes[:, -1], label=objective)
                if i == n - 1:
                    ax.set_xlabel(pj)
                if j == 0:
                    ax.set_ylabel(pi)
        fig.suptitle("Calibration pairplot")
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig
