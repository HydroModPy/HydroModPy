"""How a one-instant figure names the stress period it draws.

A run stamps each period with its end, so the state of October 2002 is
stamped 2002-11-01. A title that printed the stamp named the wrong month.
The title names the period instead, through
:func:`hydromodpy.core.time.selection.period_label`, the one rule the
figures and the exports share. A calendar month reads as ``"October 2002"``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.time.selection import period_label

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

__all__ = ("instant_label", "run_edges")

_MONTH = re.compile(r"^\d{4}-\d{2}$")

_NO_DATES = (AttributeError, KeyError, ValueError, RuntimeError, FileNotFoundError)
"""What a run without a time axis raises when its edges are asked for."""


def run_edges(sim: Run) -> pd.DatetimeIndex | None:
    """Return the ``n + 1`` period edges of a run, or None without dates.

    A run-shaped object that exposes only :attr:`time_index` gets edges
    rebuilt from its end stamps.
    """
    try:
        edges = sim.periods.edges
    except _NO_DATES:
        edges = _edges_from_stamps(sim)
    if edges is None or len(edges) < 2:
        return None
    return pd.DatetimeIndex(edges)


def _edges_from_stamps(sim: Any) -> pd.DatetimeIndex | None:
    """Rebuild the edges from the end stamps, or None when there are none."""
    from hydromodpy.core.time.period_aggregation import period_edges

    try:
        stamps = sim.time_index
        return period_edges(stamps)
    except _NO_DATES:
        return None


def instant_label(sim: Run, timestep: int) -> str:
    """Return how a title names period ``timestep`` of ``sim``, or ``""``.

    ``"October 2002"`` for a calendar month, ``"2002"`` for a year,
    ``"2002-10-15"`` for a day, ``"2000-01-01 to 2002-12-31"`` for any
    other span. A negative index counts from the end. A run without dates,
    or an index it does not hold, has no label.
    """
    edges = run_edges(sim)
    if edges is None:
        return ""
    try:
        label = period_label(int(timestep), edges)
    except ValueError:
        # TimeSelectionError included: an index the run does not hold.
        return ""
    if _MONTH.match(label):
        return pd.Timestamp(f"{label}-01").strftime("%B %Y")
    return label
