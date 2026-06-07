"""Parameter-pair objective landscape for a calibration session."""

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
class CalibrationLandscapeFigure(BaseFigure):
    """2D landscape(s) of the objective in parameter space.

    With exactly two parameters, shows a single scatter with a colorbar.
    With more, produces an upper-triangle grid of pair scatters so the
    overall objective structure is readable at a glance.
    """

    spec = FigureSpec(
        name="calibration_landscape",
        title="Calibration objective landscape",
        kind="comparison",
        required_tables=("calibration_iterations",),
        default_figsize=(8.0, 7.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        **_,
    ) -> Axes:
        # render() is a no-op: the landscape needs its own grid layout,
        # so plot() is overridden below.
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "calibration_landscape has its own plot()",
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
        cmap: str = "viridis",
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        import pandas as pd

        iters = getattr(sim, "calibration_iterations", None)
        if iters is None:
            raise ValueError("calibration_landscape: simulation has no calibration_iterations")
        df = pd.DataFrame(iters)
        if session_id is not None and "session_id" in df.columns:
            df = df[df["session_id"].astype(str) == str(session_id)]
        if len(df) == 0:
            raise ValueError("calibration_landscape: no iteration rows available")

        if parameters is None:
            parameters = [c for c in df.columns if c not in _META_COLUMNS and c != objective]
        if len(parameters) < 2:
            raise ValueError("calibration_landscape: need at least two parameter columns")
        obj = df[objective].to_numpy(dtype=float) if objective in df.columns else None

        n = len(parameters)
        if n == 2:
            fig, ax = plt.subplots(
                figsize=figsize or self.spec.default_figsize,
                dpi=dpi,
                constrained_layout=True,
            )
            sc = ax.scatter(
                df[parameters[0]].to_numpy(dtype=float),
                df[parameters[1]].to_numpy(dtype=float),
                c=obj,
                cmap=cmap,
                s=22,
                edgecolors="white",
                linewidths=0.3,
            )
            ax.set_xlabel(parameters[0])
            ax.set_ylabel(parameters[1])
            ax.grid(True, ls=":", lw=0.4)
            if obj is not None:
                fig.colorbar(sc, ax=ax, label=objective)
            fig.suptitle(f"Objective landscape - {sim.name or sim.sim_id}")
            if save_path is not None:
                from pathlib import Path

                self._save(fig, Path(save_path), dpi=dpi)
            return fig

        fig, axes = plt.subplots(
            n - 1,
            n - 1,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        sc = None
        for i in range(n - 1):
            for j in range(n - 1):
                ax = axes[i, j]
                pj = parameters[j]
                pi = parameters[i + 1]
                if j > i:
                    ax.set_axis_off()
                    continue
                sc = ax.scatter(
                    df[pj].to_numpy(dtype=float),
                    df[pi].to_numpy(dtype=float),
                    c=obj,
                    cmap=cmap,
                    s=10,
                )
                if i == n - 2:
                    ax.set_xlabel(pj)
                if j == 0:
                    ax.set_ylabel(pi)
                ax.grid(True, ls=":", lw=0.3)
        if sc is not None and obj is not None:
            fig.colorbar(sc, ax=axes[:, -1], label=objective)
        fig.suptitle(f"Objective landscape - {sim.name or sim.sim_id}")
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig
