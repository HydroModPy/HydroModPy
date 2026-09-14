"""The cost of a calibration against one parameter, and how lopsided it is.

A calibrated value alone says nothing about what was learned. The shape of
``cost(theta)`` around the optimum does: steep on one side and flat on the
other means the parameter is bounded in one direction and free in the other,
and a report that gives the optimum without that shape overstates the result.

So the profile is drawn, the best trial is marked, and the asymmetry is
measured rather than left to the eye: the interval around the optimum where
the cost stays within a declared relative rise is shaded, and its two
half-widths are written out side by side. On a log axis they are factors, on a
linear one differences, because that is the width the search actually walked.

A failed trial keeps its abscissa and carries NaN, so the profile breaks. It
is never drawn as a high cost, which would read as an explored bound, and
never dropped, because where the solver stops converging is part of what the
sweep found out.
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
    import pandas as pd
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

_PROFILE_COLOR = HIGH_CONTRAST_TRIPLET[0]
_BAND_COLOR = HIGH_CONTRAST_TRIPLET[1]
_BEST_COLOR = HIGH_CONTRAST_TRIPLET[2]

_DECADE = 10.0
"""A sweep wider than this factor is read as a search over the decades."""

_DEFAULT_RISE = 0.1
"""Relative rise defining the interval read as "as good as the optimum".

Ten percent sits above the run-to-run noise of a solve, so the interval is not
an artefact of the solver tolerance, and stays low enough that a reader still
accepts every point inside it as an acceptable calibration.
"""


@dataclass(frozen=True, slots=True)
class _ToleranceInterval:
    """The span around the optimum where the cost stays under a threshold.

    Each end carries how it was reached: ``crossed`` when a sampled trial rose
    above the threshold, ``open`` when the sweep ended first, ``blocked`` when
    the next trial failed. Only a crossed end measures a half-width; the other
    two are bounds of the sampling, not of the parameter.
    """

    low: float
    high: float
    low_kind: str
    high_kind: str

    @property
    def is_measured(self) -> bool:
        """Whether both ends were reached by a rise in cost."""
        return self.low_kind == "crossed" and self.high_kind == "crossed"


@register
class ParameterCostProfileFigure(BaseFigure):
    """Objective versus one calibrated parameter, with its asymmetry measured.

    ``rise`` is the relative rise over the optimum that bounds the shaded
    interval. ``log_scale`` defaults to reading the sweep: strictly positive
    samples spanning more than a decade were searched in log space.
    """

    spec = FigureSpec(
        name="parameter_cost_profile",
        title="Parameter cost profile",
        kind="timeseries",
        required_tables=("calibration_iterations",),
        default_figsize=(7.6, 5.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        parameter: str | None = None,
        parameter_units: str = "-",
        objective: str = "objective_value",
        objective_units: str = "-",
        session_id: str | None = None,
        rise: float = _DEFAULT_RISE,
        log_scale: bool | None = None,
        **_,
    ) -> Axes:
        if not float(rise) > 0.0:
            raise ValueError(f"the tolerance rise must be positive, got {rise!r}.")

        table = trial_table(sim, session_id=session_id)
        name, values = table.parameter_values(parameter)
        cost = _completed_cost(table.diagnostic(objective), table.frame)

        keep = np.isfinite(values)
        values, cost = values[keep], cost[keep]
        order = np.argsort(values, kind="stable")
        values, cost = values[order], cost[order]
        log = _reads_log(values, log_scale)

        ax.plot(
            values,
            cost,
            color=_PROFILE_COLOR,
            lw=1.7,
            marker="o",
            ms=4.5,
            zorder=3,
            label="objective: one point per trial",
        )
        failed = ~np.isfinite(cost)
        if np.any(failed):
            ax.scatter(
                values[failed],
                np.full(int(np.sum(failed)), 0.015),
                transform=ax.get_xaxis_transform(),
                marker="x",
                s=44,
                color="0.35",
                zorder=4,
                clip_on=False,
                label="failed trial: no cost",
            )

        note = _draw_optimum(ax, values, cost, name=name, rise=float(rise), log=log)
        ax.annotate(
            note,
            xy=(0.02, 0.97),
            xycoords="axes fraction",
            ha="left",
            va="top",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
            zorder=6,
        )

        if log:
            ax.set_xscale("log")
        ax.set_xlabel(f"{name} ({parameter_units})")
        ax.set_ylabel(f"Objective ({objective_units})")
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title(f"Parameter cost profile - {sim.name or sim.sim_id}")
        ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
        return ax


def _draw_optimum(
    ax: Axes,
    values: np.ndarray,
    cost: np.ndarray,
    *,
    name: str,
    rise: float,
    log: bool,
) -> str:
    """Mark the best trial and shade its tolerance interval, and say what it is."""
    finite = np.isfinite(cost)
    if not np.any(finite):
        return "no trial produced a cost: nothing is optimal here"

    best = int(np.flatnonzero(finite)[np.argmin(cost[finite])])
    x_best, c_best = float(values[best]), float(cost[best])
    ax.axvline(x_best, color=_BEST_COLOR, lw=1.1, ls="--", zorder=2)
    ax.plot(
        [x_best],
        [c_best],
        color=_BEST_COLOR,
        marker="*",
        ms=14,
        ls="none",
        zorder=5,
        label=f"best trial: {name} = {x_best:.4g}",
    )
    if c_best <= 0.0:
        return (
            f"best {name} = {x_best:.4g} at a cost of {c_best:.4g}\n"
            "a relative rise over a cost that is not positive says nothing, "
            "so no interval is drawn"
        )

    threshold = c_best * (1.0 + rise)
    interval = _tolerance_interval(values, cost, best=best, threshold=threshold, log=log)
    ax.axhline(threshold, color=_BAND_COLOR, lw=1.0, ls=":", zorder=2)
    ax.axvspan(
        interval.low,
        interval.high,
        color=_BAND_COLOR,
        alpha=0.22,
        lw=0.0,
        zorder=1,
        label=f"cost within +{rise:.0%} of the optimum",
    )
    return _note(interval, name=name, x_best=x_best, threshold=threshold, rise=rise, log=log)


def _tolerance_interval(
    values: np.ndarray,
    cost: np.ndarray,
    *,
    best: int,
    threshold: float,
    log: bool,
) -> _ToleranceInterval:
    """Return the span around ``best`` over which the cost stays under ``threshold``."""
    axis = np.log10(values) if log else values.astype(float)
    low, low_kind = _walk(axis, cost, start=best, step=-1, threshold=threshold)
    high, high_kind = _walk(axis, cost, start=best, step=1, threshold=threshold)
    if log:
        low, high = 10.0**low, 10.0**high
    return _ToleranceInterval(
        low=float(low),
        high=float(high),
        low_kind=low_kind,
        high_kind=high_kind,
    )


def _walk(
    axis: np.ndarray,
    cost: np.ndarray,
    *,
    start: int,
    step: int,
    threshold: float,
) -> tuple[float, str]:
    """Return one end of the interval, and how the walk stopped.

    The walk never steps over a failed trial: past a gap nothing was measured,
    so an interval continued on the other side would claim a cost no trial
    ever produced.
    """
    inside = start
    index = start + step
    while 0 <= index < cost.size:
        if not np.isfinite(cost[index]):
            return float(axis[inside]), "blocked"
        if cost[index] > threshold:
            weight = (threshold - cost[inside]) / (cost[index] - cost[inside])
            return float(axis[inside] + weight * (axis[index] - axis[inside])), "crossed"
        inside = index
        index += step
    return float(axis[inside]), "open"


def _note(
    interval: _ToleranceInterval,
    *,
    name: str,
    x_best: float,
    threshold: float,
    rise: float,
    log: bool,
) -> str:
    """Return the two or three lines that read the interval out loud."""
    if log:
        below, above = x_best / interval.low, interval.high / x_best
        widths = f"/{below:.4g} below, x{above:.4g} above"
    else:
        below, above = x_best - interval.low, interval.high - x_best
        widths = f"-{below:.4g} below, +{above:.4g} above"

    lines = [
        f"cost <= {threshold:.4g}, a {rise:.0%} rise, for {name} in "
        f"[{interval.low:.4g}, {interval.high:.4g}]",
        f"half-widths: {widths}",
    ]
    if interval.is_measured and min(below, above) > 0.0:
        ratio = max(below, above) / min(below, above)
        side = "above" if above > below else "below"
        lines[1] = f"{lines[1]} -> {ratio:.4g}x wider {side}"
    lines.extend(_caveats(interval))
    return "\n".join(lines)


def _caveats(interval: _ToleranceInterval) -> list[str]:
    """Return what an end that no rise in cost produced actually means."""
    if interval.low_kind == "open" and interval.high_kind == "open":
        return ["no trial rose above the tolerance: the sweep identifies nothing"]
    caveats = []
    for side, kind in (("below", interval.low_kind), ("above", interval.high_kind)):
        if kind == "open":
            caveats.append(f"{side} is open: the sweep stops before the cost rises")
        elif kind == "blocked":
            caveats.append(f"{side} stops at a failed trial, not at a rise in cost")
    return caveats


def _completed_cost(cost: np.ndarray, frame: pd.DataFrame) -> np.ndarray:
    """Return the cost of every trial, NaN wherever the session did not complete one.

    A trial can carry a number and still have failed; the engine reads a cost
    only from a completed trial, and a figure that read the others would draw
    a bound the calibration never accepted.
    """
    if "status" not in frame.columns:
        return cost
    completed = frame["status"].astype(str).str.lower().to_numpy() == "completed"
    return np.where(completed, cost, np.nan)


def _reads_log(values: np.ndarray, log_scale: bool | None) -> bool:
    """Decide the axis: a positive sweep wider than a decade walked log space."""
    positive = bool(values.size) and bool(np.all(values > 0.0))
    if log_scale is not None:
        if log_scale and not positive:
            raise ValueError(
                "a log axis was asked for over a non-positive parameter value; a search "
                "walking the decades samples strictly positive values."
            )
        return bool(log_scale)
    if not positive:
        return False
    return float(np.max(values) / np.min(values)) > _DECADE
