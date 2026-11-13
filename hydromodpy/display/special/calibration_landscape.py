"""Cost over the plane of each pair of searched parameters, one marker per trial.

Each trial that searched both parameters of a pair is a marker coloured by its cost
(a log scale when the costs span more than one decade). The star is the trial the
session returned, not the lowest cost, and it is left out with a note when that trial is
not among those drawn. A ring marks each trial whose cost is under the acceptable cost of
the phase, its own threshold else 1.15 times the cost of the returned trial. A parameter searched on a log scale gets a log
axis, with the bounds of the search as limits. Two parameters give one plane on the
axes. More give the lower triangle of the pairs as inset axes of the one axes, whose own
frame is hidden, because a figure has one axes and the pairs share one colour bar.
"""

from __future__ import annotations

from typing import Any

from matplotlib.colors import LogNorm, Normalize
from matplotlib.ticker import NullFormatter

from hydromodpy.display import static
from hydromodpy.display.special.records import (
    axis_label,
    completed_trials,
    mark_returned,
    ring_acceptable,
)
from hydromodpy.display.subject import FigureNotApplicable, read_table
from hydromodpy.display.theme import Theme
from hydromodpy.results.session.acceptance import acceptable_cost, phase_returned

GAP = 0.14
LOG_SPAN = 10.0


def _plane(panel: Any, frame: Any, bounds: Any, x: str, y: str, best: Any, norm: Any,
           threshold: float | None, theme: Theme) -> Any:  # fmt: skip
    """Draw the trials of the pair ``(x, y)`` on ``panel`` and return the markers."""
    points = panel.scatter(frame[x], frame[y], c=frame["cost"], cmap=theme.ramps["sequential"],
                           norm=norm, s=12, linewidths=0, zorder=3)  # fmt: skip
    ring_acceptable(panel, frame[x], [frame[y]], frame["cost"], threshold, theme)
    if best is not None and best[x] == best[x] and best[y] == best[y]:
        mark_returned(panel, best[x], best[y], theme)
    for name, axis in ((x, "x"), (y, "y")):
        low, high = bounds.loc[name, ["lower", "upper"]].astype(float)
        if bounds.loc[name, "search_space"] == "log":
            getattr(panel, f"set_{axis}scale")("log")
            getattr(panel, f"{axis}axis").set_minor_formatter(NullFormatter())
        getattr(panel, f"set_{axis}lim")(low, high)
    return points


def _together(trials: Any, names: list[str]) -> list[tuple[str, str]]:
    """Return the pairs of ``names`` that some trial of ``trials`` searched together."""
    pairs = [(names[j], names[i]) for i in range(1, len(names)) for j in range(i)]
    return [(x, y) for x, y in pairs if trials[[x, y]].notna().all(axis=1).any()]


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the pairs of searched parameters coloured by cost, with the returned trial.

    One phase is drawn, the first that searched two parameters together, since the costs
    of two phases are not one scale.
    """
    every = completed_trials(subject)
    bounds = read_table(subject, "bounds")
    for phase in dict.fromkeys(every["phase"]):
        trials = every[every["phase"] == phase]
        names = [name for name in bounds.index if name in trials and trials[name].notna().any()]
        if _together(trials, names):
            break
    else:
        raise FigureNotApplicable(
            "No phase of the session searched two parameters together, so there is no plane "
            "to draw."
        )
    pairs = _together(trials, names)
    returned, widths = phase_returned(subject, phase)
    held = trials[trials["trial"] == (returned.trial if returned else None)]
    best = None if held.empty else held.iloc[0]
    threshold = acceptable_cost(returned, widths, None if best is None else float(best["cost"]))
    cost = trials["cost"].to_numpy(float)
    spans = cost.min() > 0 and cost.max() / cost.min() > LOG_SPAN
    norm = LogNorm(cost.min(), cost.max()) if spans else Normalize(cost.min(), cost.max())
    names = [name for name in names if any(name in pair for pair in pairs)]
    count = len(names) - 1
    if count == 1:
        panels = {pairs[0]: ax}
    else:
        ax.set_axis_off()
        size = (1.0 - GAP * (count - 1)) / count
        panels = {}
        for i in range(1, len(names)):
            for j in range(i):
                where = [j * (size + GAP), 1.0 - i * size - (i - 1) * GAP, size, size]
                panels[(names[j], names[i])] = ax.inset_axes(where)
    points = None
    for (x, y), panel in panels.items():
        frame = trials[trials[[x, y]].notna().all(axis=1)]
        points = _plane(panel, frame, bounds, x, y, best, norm, threshold, theme)
        panel.set_xlabel(axis_label(x, bounds.loc[x, "units"]))
        panel.set_ylabel(axis_label(y, bounds.loc[y, "units"]))
        static.style_axes(panel, theme)
    static.colorbar(ax.figure, points, ax, theme, label="Cost")
    if best is None:
        static.note(ax, "The returned trial is not among the trials drawn", theme)
    static.legend(next(iter(panels.values())), theme)
