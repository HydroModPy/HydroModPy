"""Cost of each trial of a calibration, the best so far and the trial the session returned.

Each completed trial is a marker at its cost. The best cost reached so far is a step
that only goes down. A star marks the trial the session returned, which is not always
the lowest cost (ties and rules of the search decide). When that trial is not among the
trials drawn, there is no star and the note says so. The note also gives the returned
value of each parameter with the interval of its tolerance. A dashed line marks the
acceptable cost, the session's own threshold when it has one, else 1.15 times the
cost of the returned trial. A staged session is drawn phase by phase, side by side, each with its own
cost axis, because the costs of two phases do not share a unit.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.core.scoring.metric_table import NETWORK_METRIC_NAMES
from hydromodpy.display import static
from hydromodpy.display.special.records import completed_trials, mark_returned
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.session.acceptance import acceptable_cost, phase_returned

GAP = 0.13
LOG_SPAN = 20.0
MAX_LABEL = 24


def _phases(session: Any, trials: Any) -> list[tuple[str, str | None, Any, Any, dict]]:
    """Return name, cost label, trials, returned trial and widths of each phase."""
    staged = [phase for phase in session.phases if phase.best is not None]
    if not staged:
        best, widths = phase_returned(session, "")
        return [("", None, trials, best, widths)]
    return [
        (phase.name, phase.cost_label or phase.cost_name, trials[trials["phase"] == phase.name],
         phase.best, phase.widths)
        for phase in staged
    ]  # fmt: skip


def _returned_note(best: Any, widths: dict) -> str:
    """Return the returned values of the parameters, each with the interval of its tolerance."""
    lines = []
    for name, value in best.parameters.items():
        interval = widths[name].interval if name in widths else None
        span = ""
        if interval is not None and interval.lower is not None and interval.upper is not None:
            span = f" [{interval.lower:.3g}, {interval.upper:.3g}]"
        lines.append(f"{name} = {value:.4g}{span}")
    return "\n".join(lines)


def _panels(ax: Any, shares: list[int]) -> list[Any]:
    """Return one axes for a single phase, else insets of the host side by side."""
    if len(shares) == 1:
        return [ax]
    ax.set_axis_off()
    room = 1.0 - GAP * (len(shares) - 1)
    panels, left = [], 0.0
    for share in shares:
        width = room * share / sum(shares)
        panels.append(ax.inset_axes([left, 0.0, width, 1.0]))
        left += width + GAP
    return panels


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the cost by trial on ``ax``, one panel per phase of a staged session."""
    trials = completed_trials(subject)
    if trials.empty:
        raise FigureNotApplicable("The session has no completed trial with a cost to draw.")
    phases = _phases(subject, trials)
    total = sum(len(frame) for _, _, frame, _, _ in phases)
    panels = _panels(ax, [max(len(frame), (total + 1) // 2, 1) for _, _, frame, _, _ in phases])
    for panel, (name, label, frame, best, widths) in zip(panels, phases, strict=True):
        if frame.empty:
            raise FigureNotApplicable(f"Phase {name or 'search'!r} has no completed trial.")
        number = frame["trial"].to_numpy(float)
        cost = frame["cost"].to_numpy(float)
        held = best is not None and best.trial in set(frame["trial"])
        panel.scatter(number, cost, s=9, color=theme.roles["trial"], linewidths=0, zorder=3,
                      label="Trial")  # fmt: skip
        panel.step(number, np.minimum.accumulate(cost), where="post", zorder=4, label="Best so far",
                   **static.line_style(theme, "simulated"))  # fmt: skip
        threshold = acceptable_cost(
            best, widths, float(frame.loc[frame["trial"] == best.trial, "cost"].iloc[0]) if held else None
        )  # fmt: skip
        if threshold is not None:
            panel.axhline(threshold, color=theme.roles["bounds"], linewidth=theme.line_width,
                          linestyle="--", zorder=2,
                          label=f"Acceptable cost {threshold:.3g}")  # fmt: skip
        note = [] if best is None else [_returned_note(best, widths)]
        if held:
            mark_returned(panel, best.trial, float(frame.loc[frame["trial"] == best.trial, "cost"].iloc[0]), theme)  # fmt: skip
        else:
            note.append("The returned trial is not among the trials drawn")
        if text := "\n".join(line for line in note if line):
            static.note(panel, text, theme, loc="upper right")
        if cost.min() > 0 and cost.max() / cost.min() > LOG_SPAN:
            panel.set_yscale("log")
        unit = unit_text("m") if label in NETWORK_METRIC_NAMES else ""
        head = f"Cost, {label}" if label and len(label) <= MAX_LABEL else "Cost"
        panel.set_ylabel(f"{head} ({unit})" if unit else head)
        panel.set_xlabel("Trial")
        panel.margins(x=0.08)
        if name:
            panel.set_title(name.replace("_", " "))
        static.style_axes(panel, theme)
    static.legend(panels[0], theme)
