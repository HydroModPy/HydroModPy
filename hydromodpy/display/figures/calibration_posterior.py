"""Marginal posterior histograms from calibration iterations."""

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
class CalibrationPosteriorFigure(BaseFigure):
    """One histogram per parameter, shaded by mean objective when available."""

    spec = FigureSpec(
        name="calibration_posterior",
        title="Calibration parameter posteriors",
        kind="comparison",
        required_tables=("calibration_iterations",),
        default_figsize=(8.0, 6.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        **_,
    ) -> Axes:
        # render() is a no-op: the posterior figure needs its own grid,
        # so plot() is overridden below.
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "calibration_posterior has its own plot()",
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
        bins: int = 20,
        cmap: str = "viridis",
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib import cm
        from matplotlib.colors import Normalize

        table = trial_table(sim, session_id=session_id)
        names = list(parameters) if parameters is not None else list(table.parameters)
        if not names:
            raise ValueError(
                "calibration_posterior: no parameter columns found; the session recorded "
                f"{', '.join(sorted(table.frame.columns))}"
            )
        sampled = [table.parameter_values(name) for name in names]

        objective_name, obj = (
            table.objective_values(objective)
            if objective is not None or table.has_objective()
            else (None, None)
        )
        norm = None
        colormap = plt.get_cmap(cmap)
        if obj is not None and np.any(np.isfinite(obj)):
            finite = obj[np.isfinite(obj)]
            norm = Normalize(vmin=float(finite.min()), vmax=float(finite.max()))

        n = len(sampled)
        ncols = min(3, n)
        nrows = (n + ncols - 1) // ncols
        fig, axes = plt.subplots(
            nrows,
            ncols,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        axes = np.atleast_1d(axes).ravel()
        for ax, (name, values) in zip(axes, sampled, strict=False):
            counts, edges, patches = ax.hist(
                values, bins=bins, color="steelblue", edgecolor="white", linewidth=0.5
            )
            if obj is not None and norm is not None:
                for lo, hi, patch in zip(edges[:-1], edges[1:], patches, strict=False):
                    mask = (values >= lo) & (values <= hi)
                    if np.any(mask) and np.any(np.isfinite(obj[mask])):
                        patch.set_facecolor(colormap(norm(float(np.nanmean(obj[mask])))))
            ax.set_xlabel(name)
            ax.set_ylabel("count")
            ax.grid(True, ls=":", lw=0.4)
        for ax in axes[n:]:
            ax.set_axis_off()
        if norm is not None:
            fig.colorbar(
                cm.ScalarMappable(norm=norm, cmap=colormap),
                ax=axes.tolist(),
                label=f"mean {objective_name}",
                shrink=0.7,
            )
        fig.suptitle(f"Parameter posteriors - {sim.name or sim.sim_id}")
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig
