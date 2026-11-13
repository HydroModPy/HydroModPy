"""Parameter-pair scatter grid from a calibration session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.figure import BaseFigure, FigureSpec, new_subplots
from hydromodpy.display.figure_options import ObjectiveName, ParameterNames
from hydromodpy.display.figures._trial_diagnostics import no_trial_reason, trial_table
from hydromodpy.display.subject import FigureNotApplicable

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.session.view import Session


class CalibrationPairplotFigure(BaseFigure):
    """Scatter matrix of calibrated parameter values, colored by objective."""

    spec = FigureSpec(
        name="calibration_pairplot",
        title="Calibration parameter pairs",
        kind="comparison",
        subject="session",
        default_figsize=(8.0, 8.0),
    )

    def unavailable_reason(self, session: Session) -> str | None:
        """Refuse a session that recorded no trial, before drawing."""
        return no_trial_reason(session)

    def render(
        self,
        session: Session,
        ax: Axes,
        **_,
    ) -> Axes:
        # render() is a no-op; the pairplot needs its own grid, so plot() is overridden.
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "calibration_pairplot has its own plot()",
            ha="center",
            va="center",
        )
        return ax

    def plot(
        self,
        session: Session,
        *,
        parameters: ParameterNames = None,
        objective: ObjectiveName = None,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:

        table = trial_table(session)
        names = list(parameters) if parameters is not None else list(table.parameters)
        if len(names) < 2:
            # The session decides when no parameter is named; a short
            # `parameters=` is a fault of the caller.
            refusal = ValueError if parameters is not None else FigureNotApplicable
            raise refusal(
                "calibration_pairplot: need at least two parameter columns; the session "
                f"sampled {', '.join(names) or '<none>'}"
            )
        sampled = dict(table.parameter_values(name) for name in names)
        cost_name, obj = (
            table.cost_values(objective)
            if objective is not None or table.has_objective()
            else (None, None)
        )

        n = len(names)
        fig, axes = new_subplots(
            n,
            n,
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        for i, pi in enumerate(names):
            for j, pj in enumerate(names):
                ax = axes[i, j] if n > 1 else axes
                if i == j:
                    ax.hist(sampled[pi], bins=20, color="steelblue")
                else:
                    sc = ax.scatter(
                        sampled[pj],
                        sampled[pi],
                        c=obj,
                        cmap="viridis",
                        s=8,
                    )
                    if i == n - 1 and j == n - 1 and obj is not None:
                        fig.colorbar(sc, ax=axes[:, -1], label=cost_name)
                if i == n - 1:
                    ax.set_xlabel(pj)
                if j == 0:
                    ax.set_ylabel(pi)
        fig.suptitle("Calibration pairplot")
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig
