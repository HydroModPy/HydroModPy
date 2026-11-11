"""How a one-instant figure names the stress period it draws.

A run stamps each period with its end, so the state of October 2002 is
stamped 2002-11-01. A title that printed the stamp named the wrong month.
The title names the period instead, through
:func:`hydromodpy.core.time.selection.period_label`, the one rule the
figures and the exports share. A calendar month reads as ``"October 2002"``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.core.time.selection import period_label
from hydromodpy.results.derive.time_alignment import run_period_edges

if TYPE_CHECKING:
    from hydromodpy.results.run.view import Run

__all__ = ("instant_label",)

_MONTH = re.compile(r"^\d{4}-\d{2}$")


def instant_label(sim: Run, timestep: int) -> str:
    """Return how a title names period ``timestep`` of ``sim``, or ``""``.

    ``"October 2002"`` for a calendar month, ``"2002"`` for a year,
    ``"2002-10-15"`` for a day, ``"2000-01-01 to 2002-12-31"`` for any
    other span. A negative index counts from the end. A run without dates,
    or an index it does not hold, has no label.
    """
    edges = run_period_edges(sim)
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
