"""The cost of a calibration against one parameter, and how lopsided it is.

A calibrated value alone says nothing about what was learned. The shape of
``cost(theta)`` around the optimum does: steep on one side and flat on the
other means the parameter is bounded in one direction and free in the other,
and a report that gives the optimum without that shape overstates the result.

So the profile is drawn, the trial the calibration returned is marked, and the
asymmetry is measured rather than left to the eye. The shaded interval is the
one the calibration summary and ``calibration_progress`` report: the sampled
values whose cost stays within the calibration's own width of the best cost,
one mesh cell on network distances in metres, five per cent of the best cost
otherwise, or the width ``[calibration.uncertainty]`` wrote. Its two
half-widths are written out side by side: on a log axis they are factors, on
a linear one differences, because that is the width the search actually
walked. A value combined from two roots gets no interval, as in the summary:
its width is the spread of the roots.

A failed trial keeps its abscissa and carries NaN, so the profile breaks. It
is never drawn as a high cost, which would read as an explored bound, and
never dropped, because where the solver stops converging is part of what the
sweep found out.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._calibration_session import (
    Interval,
    Tolerance,
    chosen_session,
    cost_blocks,
    cost_label,
    float_or,
    parameter_declaration,
    read_tolerance,
    returned_row,
    session_config,
    session_descriptor,
    text,
    tolerance_interval,
    two_roots,
)
from hydromodpy.display.figures._trial_diagnostics import trial_table
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

_PROFILE_COLOR = HIGH_CONTRAST_TRIPLET[0]
_BAND_COLOR = HIGH_CONTRAST_TRIPLET[1]
_BEST_COLOR = HIGH_CONTRAST_TRIPLET[2]
_ROOT_COLOR = "0.35"

_DECADE = 10.0
"""A sweep wider than this factor is read as a search over the decades."""

_NOTE_FONTSIZE = 9.0

_NOTE_WIDTH = 78
"""Characters per line of the note, so a long reason never widens the figure."""

_NO_OTHER_TRIAL = "no other trial within"
"""What the calibration summary says of an interval holding the best trial alone."""


@dataclass(frozen=True, slots=True)
class _Profile:
    """The sampled values and their cost, sorted along the parameter.

    ``returned`` is the position of the trial the calibration returned, None
    when the session does not say which. ``lowest`` is the position of the
    lowest cost, the one the interval is measured from.
    """

    name: str
    units: str
    values: np.ndarray
    cost: np.ndarray
    returned: int | None
    lowest: int | None
    bounds: tuple[float, float] | None

    def value_text(self, value: float) -> str:
        """Return one value with its unit."""
        unit = "" if self.units == "-" else f" {self.units}"
        return f"{self.name} = {value:.4g}{unit}"


@dataclass(frozen=True, slots=True)
class _Ends:
    """How each end of the interval was reached.

    ``crossed`` when the next sampled trial rose above the threshold, ``open``
    when the sweep ended first, ``blocked`` when the next trial failed. Only a
    crossed end measures a half-width; the other two are bounds of the
    sampling, not of the parameter.
    """

    low: str
    high: str

    @property
    def is_measured(self) -> bool:
        """Whether both ends were reached by a rise in cost."""
        return self.low == "crossed" and self.high == "crossed"


@register
class ParameterCostProfileFigure(BaseFigure):
    """Cost versus one calibrated parameter, with its asymmetry measured.

    ``parameter_units`` and ``objective_units`` default to what the session
    declared: the unit of the parameter, and the unit of the metric the cost
    is. ``log_scale`` defaults to reading the sweep: strictly positive samples
    spanning more than a decade were searched in log space.
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
        parameter_units: str | None = None,
        objective: str = "objective_value",
        objective_units: str | None = None,
        session_id: str | None = None,
        log_scale: bool | None = None,
        **_,
    ) -> Axes:
        chosen = chosen_session(sim, session_id)
        table = trial_table(sim, session_id=chosen)
        descriptor = session_descriptor(sim, chosen)
        name, values = table.parameter_values(parameter)
        cost = _completed_cost(table.diagnostic(objective), table.frame)
        blocks = cost_blocks(table, session_config(descriptor))
        if objective != "objective_value":
            # A diagnostic drawn in place of the cost is not what the
            # calibration read its interval on, so no block describes it.
            blocks = []
        tolerance = read_tolerance(cost, blocks, table, descriptor)
        declaration = parameter_declaration(table, descriptor, name)
        profile = _profile(
            name,
            values,
            cost,
            returned=returned_row(table, descriptor),
            units=parameter_units or text(declaration.get("units")) or "-",
            bounds=_bounds(declaration.get("bounds")),
        )
        log = _reads_log(profile.values, log_scale)

        ax.plot(
            profile.values,
            profile.cost,
            color=_PROFILE_COLOR,
            lw=1.7,
            marker="o",
            ms=4.5,
            zorder=3,
            label="cost: one point per trial",
        )
        failed = ~np.isfinite(profile.cost)
        if np.any(failed):
            ax.scatter(
                profile.values[failed],
                np.full(int(np.sum(failed)), 0.015),
                transform=ax.get_xaxis_transform(),
                marker="x",
                s=44,
                color="0.35",
                zorder=4,
                clip_on=False,
                label="failed trial: no cost",
            )

        lines = _wrapped(_draw_optimum(ax, profile, tolerance, descriptor=descriptor, log=log))
        if log:
            ax.set_xscale("log")
        ax.set_xlabel(f"{name} ({profile.units})")
        if objective == "objective_value":
            label = cost_label(blocks)
            if objective_units is not None:
                label = f"{label.rsplit(' (', 1)[0]} ({objective_units})"
        else:
            label = f"{objective} ({objective_units or '-'})"
        ax.set_ylabel(label)
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title(f"Parameter cost profile - {sim.name or sim.sim_id}")

        # The note sits in a band kept free of trials at the top, and the
        # legend is placed underneath, so neither covers a trial or the other.
        band = _reserve_top_band(ax, len(lines))
        ax.annotate(
            "\n".join(lines),
            xy=(0.02, 0.98),
            xycoords="axes fraction",
            ha="left",
            va="top",
            fontsize=_NOTE_FONTSIZE,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
            zorder=6,
        )
        ax.legend(
            loc="best",
            bbox_to_anchor=(0.0, 0.0, 1.0, band),
            fontsize=9,
            framealpha=0.9,
        )
        return ax


def _profile(
    name: str,
    values: np.ndarray,
    cost: np.ndarray,
    *,
    returned: int | None,
    units: str,
    bounds: tuple[float, float] | None,
) -> _Profile:
    """Sort the trials along the parameter and keep where the two marks land."""
    flag = np.zeros(values.size, dtype=bool)
    if returned is not None:
        flag[returned] = True
    keep = np.isfinite(values)
    values, cost, flag = values[keep], cost[keep], flag[keep]
    order = np.argsort(values, kind="stable")
    values, cost, flag = values[order], cost[order], flag[order]
    finite = np.flatnonzero(np.isfinite(cost))
    lowest = int(finite[np.argmin(cost[finite])]) if finite.size else None
    marked = np.flatnonzero(flag & np.isfinite(cost))
    return _Profile(
        name=name,
        units=units,
        values=values,
        cost=cost,
        returned=int(marked[0]) if marked.size else lowest,
        lowest=lowest,
        bounds=bounds,
    )


def _draw_optimum(
    ax: Axes,
    profile: _Profile,
    tolerance: Tolerance,
    *,
    descriptor: Mapping[str, Any],
    log: bool,
) -> list[str]:
    """Mark the returned trial and shade the interval, and return what the note says."""
    if profile.returned is None or profile.lowest is None:
        return ["no trial produced a cost: nothing is optimal here"]

    x_best = float(profile.values[profile.returned])
    c_best = float(profile.cost[profile.returned])
    word = "best trial" if profile.returned == profile.lowest else "returned trial"
    ax.axvline(x_best, color=_BEST_COLOR, lw=1.1, ls="--", zorder=2)
    ax.plot(
        [x_best],
        [c_best],
        color=_BEST_COLOR,
        marker="*",
        ms=14,
        ls="none",
        zorder=5,
        label=f"{word}: {profile.value_text(x_best)}",
    )
    heading = f"{word}: {profile.value_text(x_best)} at a cost of {c_best:.4g}"
    roots = two_roots(descriptor)
    if roots is not None:
        _draw_roots(ax, roots, profile)
    if tolerance.threshold is None:
        return [heading, tolerance.missing]

    interval = tolerance_interval(profile.values, profile.cost, tolerance.threshold)
    if interval is None:
        return [heading, "no trial scored within the tolerance of the best"]
    if interval.n_within <= 1 or interval.low == interval.high:
        lines = [
            heading,
            f"{_NO_OTHER_TRIAL} {tolerance.text} of the best, over {interval.n_trials} trials",
        ]
        return lines + _on_a_bound(profile, x_best)

    ax.axhline(tolerance.threshold, color=_BAND_COLOR, lw=1.0, ls=":", zorder=2)
    ax.axvspan(
        interval.low,
        interval.high,
        color=_BAND_COLOR,
        alpha=0.22,
        lw=0.0,
        zorder=1,
        label=f"within {tolerance.text} of the best",
    )
    ends = _ends(profile.cost, tolerance.threshold)
    x_lowest = float(profile.values[profile.lowest])
    return [
        f"{profile.name} in [{interval.low:.4g}, {interval.high:.4g}]{_unit(profile)}: "
        f"{interval.n_within} of {interval.n_trials} trials scored within "
        f"{tolerance.text} of the best",
        _half_widths(interval, ends, x_lowest=x_lowest, log=log),
        *_caveats(interval, ends, profile),
    ]


def _draw_roots(ax: Axes, roots: Mapping[str, Any], profile: _Profile) -> None:
    """Draw the root of each bound a two-root search combined into its value."""
    for bound, style in (("minimal", ":"), ("maximal", "-.")):
        entry = roots.get(bound)
        value = (
            float_or(entry.get("k_star"), float("nan")) if isinstance(entry, Mapping) else np.nan
        )
        if not np.isfinite(value):
            continue
        ax.axvline(
            value,
            color=_ROOT_COLOR,
            lw=1.1,
            ls=style,
            zorder=2,
            label=f"{profile.name}*_{bound} = {value:.4g}",
        )


def _wrapped(lines: list[str]) -> list[str]:
    """Break every note line longer than the note is wide, indenting what follows."""
    return [
        part
        for line in lines
        for part in textwrap.wrap(line, _NOTE_WIDTH, subsequent_indent="  ") or [""]
    ]


def _on_a_bound(profile: _Profile, value: float) -> list[str]:
    """Say so when a value sits on a search bound, as the calibration warns."""
    if profile.bounds is None:
        return []
    low, high = profile.bounds
    for side, bound in (("lower", low), ("upper", high)):
        if (value <= bound) if side == "lower" else (value >= bound):
            return [f"on the {side} search bound: the search was forbidden to look further"]
    return []


def _unit(profile: _Profile) -> str:
    """Return the unit of the parameter, as a suffix, empty when dimensionless."""
    return "" if profile.units == "-" else f" {profile.units}"


def _ends(cost: np.ndarray, threshold: float) -> _Ends:
    """Say how each end of the interval was reached, the trials sorted along the axis."""
    inside = np.flatnonzero(np.isfinite(cost) & (cost <= threshold))

    def kind(index: int) -> str:
        if index < 0 or index >= cost.size:
            return "open"
        return "crossed" if np.isfinite(cost[index]) else "blocked"

    return _Ends(low=kind(int(inside.min()) - 1), high=kind(int(inside.max()) + 1))


def _half_widths(interval: Interval, ends: _Ends, *, x_lowest: float, log: bool) -> str:
    """Return the two half-widths around the best trial, and which one is wider."""
    if log:
        below, above = x_lowest / interval.low, interval.high / x_lowest
        widths = f"half-widths: /{below:.4g} below, x{above:.4g} above"
        empty = 1.0
    else:
        below, above = x_lowest - interval.low, interval.high - x_lowest
        widths = f"half-widths: -{below:.4g} below, +{above:.4g} above"
        empty = 0.0
    if ends.is_measured and min(below, above) > empty:
        ratio = max(below, above) / min(below, above)
        side = "above" if above > below else "below"
        widths = f"{widths} -> {ratio:.4g}x wider {side}"
    return widths


def _caveats(interval: Interval, ends: _Ends, profile: _Profile) -> list[str]:
    """Return what an end that no rise in cost produced actually means."""
    if ends.low == "open" and ends.high == "open":
        return ["no trial rose above the tolerance: the sweep identifies nothing"]
    low_bound, high_bound = profile.bounds or (None, None)
    caveats = []
    for side, kind, end, bound in (
        ("below", ends.low, interval.low, low_bound),
        ("above", ends.high, interval.high, high_bound),
    ):
        reaches = bound is not None and (end <= bound if side == "below" else end >= bound)
        if reaches:
            which = "lower" if side == "below" else "upper"
            caveats.append(
                f"{side} reaches the {which} search bound: the search was forbidden to look further"
            )
        elif kind == "open":
            caveats.append(f"{side} is open: the sweep stops before the cost rises")
        elif kind == "blocked":
            caveats.append(f"{side} stops at a failed trial, not at a rise in cost")
    return caveats


def _reserve_top_band(ax: Axes, lines: int) -> float:
    """Raise the top of the axis so a note of ``lines`` lines covers no trial.

    Returns the lower edge of the band, in axes fraction. The height is read
    before the layout settles, where an axis is at its smallest, so the band
    is never too thin.
    """
    height_pt = ax.get_position().height * ax.figure.get_figheight() * 72.0
    note_pt = _NOTE_FONTSIZE * (1.2 * lines + 1.0)
    share = min(note_pt / max(height_pt, 1.0) + 0.05, 0.6)
    low, high = ax.get_ylim()
    ax.set_ylim(low, low + (high - low) / (1.0 - share))
    return 1.0 - share


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


def _bounds(value: Any) -> tuple[float, float] | None:
    """Return the search bounds as two finite floats, None otherwise."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    low, high = float_or(value[0], np.nan), float_or(value[1], np.nan)
    if not (np.isfinite(low) and np.isfinite(high)) or high <= low:
        return None
    return low, high


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
