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

A search on two bounds (a transient extent scored on a minimal and a maximal
map) closes one root per bound. Each trial then publishes one residual per
bound, ``J_signed_minimal`` and ``J_signed_maximal``, and no unsuffixed one.
The figure draws both series, both brackets and each root, and the combined
value the search returned when the session journal names it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._calibration_session import (
    chosen_session,
    float_or,
    int_or_none,
    session_descriptor,
    two_roots,
)
from hydromodpy.display.figures._trial_diagnostics import TrialTable, trial_table
from hydromodpy.display.figures.network_extent_bounds_map import (
    SIMULATED_MAXIMAL_COLOR,
    SIMULATED_MINIMAL_COLOR,
)
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET, place_legend

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

_EXCESS_COLOR = HIGH_CONTRAST_TRIPLET[0]
_MISSING_COLOR = HIGH_CONTRAST_TRIPLET[2]

BOUNDS: tuple[str, str] = ("minimal", "maximal")
"""The two bounds of an extent, as the criterion suffixes their residuals."""

_BOUND_COLORS: dict[str, str] = {
    "minimal": SIMULATED_MINIMAL_COLOR,
    "maximal": SIMULATED_MAXIMAL_COLOR,
}
_BOUND_MARKERS: dict[str, str] = {"minimal": "o", "maximal": "s"}
_BOUND_OFFSET: dict[str, float] = {"minimal": -0.12, "maximal": 0.12}
"""Half a stem apart, so the two residuals of one evaluation never hide each other."""

_NOTE_FONTSIZE = 9.0


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

    def unavailable_reason(self, sim: Run) -> str | None:
        """Refuse a session that published no signed residual, before drawing.

        A staged calibration promotes a run per stage, and only the root
        search publishes the residual this figure traces. The storage stage of
        the same method records a cost and no network diagnostic, so asking it
        for one raised mid-render, and ``on_error = "raise"`` turned a stage
        that had converged into a failed run. The resolver's own message is
        the reason, so an ambiguity between two outputs reads as an ambiguity
        rather than as an absence. A search on two bounds publishes one
        residual per bound and is traced as such.
        """
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        table = trial_table(sim)
        if _two_bounds(table, output=None):
            return None
        try:
            table.diagnostic_column("J_signed")
        except ValueError as exc:
            return str(exc)
        return None

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

        chosen = chosen_session(sim, session_id)
        table = trial_table(sim, session_id=chosen)
        name, values = table.parameter_values(parameter)
        if np.any(np.isfinite(values) & (values <= 0.0)):
            raise ValueError(
                f"the parameter {name!r} carries a non-positive value, and a bracket over "
                "a ratio is measured as a factor between its two ends."
            )

        size = values.size
        if _two_bounds(table, output=output):
            lines = _draw_two_bounds(
                ax,
                table,
                values,
                name=name,
                output=output,
                roots=two_roots(session_descriptor(sim, chosen)),
            )
        else:
            residual = table.diagnostic("J_signed", output=output)
            lines = [_draw_one_bound(ax, values, residual, name=name)]

        ax.set_xlabel("Evaluation order (-)")
        ax.set_ylabel("Signed residual D_so - D_os (m)")
        ax.set_xlim(0.5, float(size) + 0.5)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(True, ls=":", lw=0.4)
        ax.set_title(f"Bisection bracket trace - {sim.name or sim.sim_id}")

        # The note sits in a band kept free of evaluations at the bottom, and
        # the legend is placed above it, so neither covers a marker.
        band = _reserve_bottom_band(ax, len(lines))
        ax.annotate(
            "\n".join(lines),
            xy=(0.02, 0.02),
            xycoords="axes fraction",
            ha="left",
            va="bottom",
            fontsize=_NOTE_FONTSIZE,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
            zorder=6,
        )
        place_legend(
            ax,
            fontsize=8.5,
            framealpha=0.9,
            bbox_to_anchor=(0.0, band, 1.0, 1.0 - band),
        )
        return ax


def _draw_one_bound(ax: Axes, values: np.ndarray, residual: np.ndarray, *, name: str) -> str:
    """Draw the residual of a search on one bound, and return the note's line."""
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
    _draw_failed(ax, steps, ~finite)
    return _bracket_note(trace, name=name)


def _draw_two_bounds(
    ax: Axes,
    table: TrialTable,
    values: np.ndarray,
    *,
    name: str,
    output: str | None,
    roots: Mapping[str, Any] | None,
) -> list[str]:
    """Draw one residual series, one bracket and one root per bound; return the note."""
    steps = np.arange(1, values.size + 1, dtype=float)
    record = roots or {}
    ax.axhline(0.0, color="black", lw=1.1, zorder=2, label="zero residual: the root")
    lines: list[str] = []
    answered = np.zeros(values.size, dtype=bool)
    for bound in BOUNDS:
        residual = table.diagnostic(f"J_signed_{bound}", output=output)
        answered |= np.isfinite(residual)
        color = _BOUND_COLORS[bound]
        trace = _running_bracket(values, residual)
        ax.fill_between(
            steps,
            trace.residual_low,
            trace.residual_high,
            step="post",
            color=color,
            alpha=0.35,
            linewidth=0.0,
            zorder=1,
            label=f"bracket {bound}" if np.any(np.isfinite(trace.residual_low)) else None,
        )
        finite = np.isfinite(residual)
        where = steps + _BOUND_OFFSET[bound]
        ax.vlines(where[finite], 0.0, residual[finite], color=color, lw=0.9, zorder=2)
        ax.scatter(
            where[finite],
            residual[finite],
            marker=_BOUND_MARKERS[bound],
            s=36,
            color=color,
            edgecolors="0.25",
            linewidths=0.6,
            zorder=4,
            label=f"D_so - D_os, {bound} bound",
        )
        root = _root(table, values, residual, entry=_entry(record, bound))
        if root is None:
            lines.append(f"{bound}: no sign change, no root is bracketed")
            continue
        row, k_star = root
        if row is not None:
            ax.scatter(
                [where[row]],
                [residual[row]],
                marker="o",
                s=150,
                facecolors="none",
                edgecolors=color,
                linewidths=1.8,
                zorder=5,
                label=f"{name}*_{bound} = {k_star:.4g}",
            )
        lines.append(_root_note(trace, name=name, bound=bound, k_star=k_star))
    _draw_failed(ax, steps, ~answered)
    lines.extend(_combined_lines(ax, table, record, name=name))
    return lines


def _combined_lines(
    ax: Axes, table: TrialTable, record: Mapping[str, Any], *, name: str
) -> list[str]:
    """Mark the combined value the search returned, and say it with ``Delta``."""
    if not record:
        return ["roots record not in the session journal: Delta and the combined value unknown"]
    lines = []
    delta = float_or(record.get("delta_log10"), float("nan"))
    if np.isfinite(delta):
        lines.append(f"Delta = log10({name}*_maximal / {name}*_minimal) = {delta:.3g} decade(s)")
    value = float_or(record.get("value"), float("nan"))
    if not np.isfinite(value):
        lines.append("combined value not solved: the search did not converge")
        return lines
    trial = int_or_none(record.get("combined_trial_id"))
    row = None if trial is None else table.row_of_trial(trial)
    if row is not None:
        ax.axvline(
            row + 1.0,
            color="black",
            lw=1.2,
            ls="--",
            zorder=3,
            label=f"returned: {name} = {value:.4g}",
        )
    where = "" if trial is None else f", trial {trial}"
    lines.append(f"returned {name} = {value:.4g}, the weighted geometric mean of the roots{where}")
    return lines


def _root(
    table: TrialTable,
    values: np.ndarray,
    residual: np.ndarray,
    *,
    entry: Mapping[str, Any],
) -> tuple[int | None, float] | None:
    """Return the row and the value of the root one bound closed on, or None.

    The journal's record names the trial and the value. Without it, the root
    is the end of the tightest bracket with the smaller residual, the rule
    the search applies.
    """
    k_star = float_or(entry.get("k_star"), float("nan"))
    if np.isfinite(k_star):
        trial = int_or_none(entry.get("trial_id"))
        return (None if trial is None else table.row_of_trial(trial)), k_star
    known = sorted(
        (float(values[row]), float(residual[row]), row)
        for row in range(values.size)
        if np.isfinite(values[row]) and np.isfinite(residual[row])
    )
    pairs = [
        (low, high)
        for low, high in zip(known[:-1], known[1:], strict=False)
        if low[1] * high[1] < 0.0
    ]
    if not pairs:
        return None
    low, high = min(pairs, key=lambda pair: pair[1][0] / pair[0][0])
    closest = low if abs(low[1]) <= abs(high[1]) else high
    return closest[2], closest[0]


def _entry(record: Mapping[str, Any], bound: str) -> Mapping[str, Any]:
    """Return the entry of one bound in a roots record, empty when absent."""
    entry = record.get(bound)
    return entry if isinstance(entry, Mapping) else {}


def _draw_failed(ax: Axes, steps: np.ndarray, failed: np.ndarray) -> None:
    """Keep a failed evaluation on the zero line, at its place in the order.

    A failed evaluation still consumed a solve and still moved the order, so
    it keeps its abscissa rather than disappearing and shifting everything
    after it.
    """
    if not np.any(failed):
        return
    ax.scatter(
        steps[failed],
        np.zeros(int(np.sum(failed))),
        marker="x",
        s=44,
        color="0.35",
        zorder=4,
        label="failed evaluation: no residual",
    )


def _reserve_bottom_band(ax: Axes, lines: int) -> float:
    """Lower the bottom of the axis so a note of ``lines`` lines covers no marker.

    Returns the upper edge of the band, in axes fraction. The height is read
    before the layout settles, where an axis is at its smallest, so the band
    is never too thin.
    """
    height_pt = ax.get_position().height * ax.figure.get_figheight() * 72.0
    note_pt = _NOTE_FONTSIZE * (1.2 * lines + 1.0)
    share = min(note_pt / max(height_pt, 1.0) + 0.05, 0.6)
    low, high = ax.get_ylim()
    ax.set_ylim(high - (high - low) / (1.0 - share), high)
    return share


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


def _two_bounds(table: TrialTable, *, output: str | None) -> bool:
    """Whether the trials hold one residual per bound and no unsuffixed one."""
    if table.has_diagnostic("J_signed", output=output):
        return False
    return all(table.has_diagnostic(f"J_signed_{bound}", output=output) for bound in BOUNDS)


def _bracket_note(trace: _BracketTrace, *, name: str) -> str:
    """Return the one-line reading of the final bracket."""
    if not trace.is_closed:
        return "no sign change: no root is bracketed"
    low = float(trace.parameter_low[-1])
    high = float(trace.parameter_high[-1])
    return f"bracket: {name} in [{low:.4g}, {high:.4g}], a factor {high / low:.4g}"


def _root_note(trace: _BracketTrace, *, name: str, bound: str, k_star: float) -> str:
    """Return the reading of one bound's root and of the bracket it closed in."""
    if not trace.is_closed:
        return f"{name}*_{bound} = {k_star:.4g}"
    low = float(trace.parameter_low[-1])
    high = float(trace.parameter_high[-1])
    return (
        f"{name}*_{bound} = {k_star:.4g}, bracket [{low:.4g}, {high:.4g}], "
        f"a factor {high / low:.4g}"
    )
