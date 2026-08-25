"""Every evaluated point of a root search, in order, with the bracket closing.

The signed residual ``J = D_so - D_os`` is what a bisection reads, and the
calibrated point is its zero. This figure puts one marker per evaluation on
the order it happened, the zero on a line, and the current bracket as a band
between the residuals of its two ends. A converging search shows that band
squeezing onto the line.

It also shows the failure that matters, and that no convergence plot of a
minimisation can show: a bracket that never changes sign. Every marker then
sits on the same side of zero and no band is ever drawn, which says there is
no root on the sampled interval rather than pointing at the least bad point.
Reading the lowest residual as an answer there would be a minimised mean
distance in disguise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._trial_diagnostics import trial_table

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

_EXCESS_COLOR = HIGH_CONTRAST_TRIPLET[0]
_MISSING_COLOR = HIGH_CONTRAST_TRIPLET[2]


@dataclass(frozen=True, slots=True)
class _BracketTrace:
    """The tightest sign-changing interval known after each evaluation."""

    parameter_low: np.ndarray
    parameter_high: np.ndarray
    residual_low: np.ndarray
    residual_high: np.ndarray

    @property
    def is_closed(self) -> bool:
        """Whether a bracket exists at the last evaluation."""
        return bool(self.parameter_low.size) and bool(np.isfinite(self.parameter_low[-1]))


@register
class BisectionBracketTraceFigure(BaseFigure):
    """Signed residual per evaluation, and the bracket closing onto zero."""

    spec = FigureSpec(
        name="bisection_bracket_trace",
        title="Bisection bracket trace",
        kind="timeseries",
        required_tables=("calibration_iterations",),
        default_figsize=(8.0, 4.8),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        parameter: str | None = None,
        session_id: str | None = None,
        output: str | None = None,
        **_,
    ) -> Axes:
        from matplotlib.ticker import MaxNLocator

        table = trial_table(sim, session_id=session_id)
        name, values = table.parameter_values(parameter)
        residual = table.diagnostic("J_signed", output=output)
        if np.any(np.isfinite(values) & (values <= 0.0)):
            raise ValueError(
                f"the parameter {name!r} carries a non-positive value, and a bracket over "
                "a ratio is measured as a factor between its two ends."
            )

        steps = np.arange(1, residual.size + 1, dtype=float)
        trace = _running_bracket(values, residual)
        finite = np.isfinite(residual)
        excess = finite & (residual >= 0.0)
        missing = finite & (residual < 0.0)

        ax.fill_between(
            steps,
            trace.residual_low,
            trace.residual_high,
            step="post",
            color="0.55",
            alpha=0.25,
            linewidth=0.0,
            zorder=1,
            label=(
                "bracket: the two ends that change sign"
                if np.any(np.isfinite(trace.residual_low))
                else None
            ),
        )
        ax.axhline(0.0, color="black", lw=1.1, zorder=2, label="zero residual: the root")
        ax.vlines(steps[finite], 0.0, residual[finite], color="0.7", lw=0.8, zorder=2)
        ax.scatter(
            steps[excess],
            residual[excess],
            marker="^",
            s=44,
            color=_EXCESS_COLOR,
            zorder=4,
            label="D_so - D_os >= 0: the network spills outside",
        )
        ax.scatter(
            steps[missing],
            residual[missing],
            marker="v",
            s=44,
            color=_MISSING_COLOR,
            zorder=4,
            label="D_so - D_os < 0: the network never grew",
        )
        if np.any(~finite):
            # A failed evaluation still consumed a solve and still moved the
            # order, so it keeps its abscissa on the zero line rather than
            # disappearing and shifting everything after it.
            ax.scatter(
                steps[~finite],
                np.zeros(int(np.sum(~finite))),
                marker="x",
                s=44,
                color="0.35",
                zorder=4,
                label="failed evaluation: no residual",
            )

        ax.annotate(
            _bracket_note(trace, name=name),
            xy=(0.02, 0.02),
            xycoords="axes fraction",
            ha="left",
            va="bottom",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
            zorder=6,
        )

        ax.set_xlabel("Evaluation order (-)")
        ax.set_ylabel("Signed residual D_so - D_os (m)")
        ax.set_xlim(0.5, float(residual.size) + 0.5)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(True, ls=":", lw=0.4)
        ax.set_title(f"Bisection bracket trace - {sim.name or sim.sim_id}")
        ax.legend(loc="best", fontsize=8.5, framealpha=0.9)
        return ax


def _running_bracket(values: np.ndarray, residual: np.ndarray) -> _BracketTrace:
    """Return the tightest sign-changing interval known after each evaluation.

    Tightness is measured as a factor between the two ends, which is the width
    a search over a ratio halves, and not as their difference.
    """
    size = residual.size
    empty = np.full(size, np.nan)
    trace = {key: empty.copy() for key in ("x_low", "x_high", "r_low", "r_high")}
    known: list[tuple[float, float]] = []
    for step in range(size):
        if np.isfinite(values[step]) and np.isfinite(residual[step]):
            known.append((float(values[step]), float(residual[step])))
        best = _tightest_bracket(sorted(known))
        if best is None:
            continue
        (x_low, r_low), (x_high, r_high) = best
        trace["x_low"][step] = x_low
        trace["x_high"][step] = x_high
        trace["r_low"][step] = min(r_low, r_high)
        trace["r_high"][step] = max(r_low, r_high)
    return _BracketTrace(
        parameter_low=trace["x_low"],
        parameter_high=trace["x_high"],
        residual_low=trace["r_low"],
        residual_high=trace["r_high"],
    )


def _tightest_bracket(
    points: list[tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return the closest pair of consecutive points whose residuals differ in sign."""
    found = [
        (low, high)
        for low, high in zip(points[:-1], points[1:], strict=False)
        if low[1] * high[1] < 0.0
    ]
    if not found:
        return None
    return min(found, key=lambda pair: pair[1][0] / pair[0][0])


def _bracket_note(trace: _BracketTrace, *, name: str) -> str:
    """Return the one-line reading of the final bracket."""
    if not trace.is_closed:
        return "no sign change: no root is bracketed"
    low = float(trace.parameter_low[-1])
    high = float(trace.parameter_high[-1])
    return f"bracket: {name} in [{low:.4g}, {high:.4g}], a factor {high / low:.4g}"
