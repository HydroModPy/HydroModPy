"""The trial a session returned and the cost under which a trial is acceptable, per phase.

A staged session scores each phase on its own output, so the returned trial and the
tolerance band belong to a phase. A session without phases holds them itself.
"""

from __future__ import annotations

from typing import Any

from hydromodpy.results.session.descriptor import BestTrial, ParameterWidth

RELATIVE_MARGIN = 0.15
"""Margin on the best cost of a session whose tolerance band has no threshold."""


def phase_returned(session: Any, phase: str) -> tuple[BestTrial | None, dict[str, ParameterWidth]]:
    """Return the returned trial and the widths of ``phase``, else those of the session."""
    for held in session.phases:
        if held.name == phase and held.best is not None:
            return held.best, held.widths
    return session.descriptor.best, session.descriptor.widths


def acceptable_cost(
    best: BestTrial | None, widths: dict[str, ParameterWidth], drawn: float | None = None
) -> float | None:
    """Return the cost under which a trial is acceptable, or None when nothing says.

    It is the threshold of the tolerance band when a width holds one, else the cost of the
    returned trial with a margin of ``RELATIVE_MARGIN``. The cost of the returned trial is
    the one its descriptor holds, else ``drawn``, the cost of that trial among the rows a
    figure draws. The minimum of the costs is never used, since the returned trial is not
    always the lowest.
    """
    for width in widths.values():
        if width.interval is not None and width.interval.threshold is not None:
            return float(width.interval.threshold)
    cost = drawn if best is None or best.cost is None else best.cost
    return None if cost is None else float(cost) * (1.0 + RELATIVE_MARGIN)
