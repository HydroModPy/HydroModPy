"""The stress periods of a run, placed on the calendar.

A request names instants by date (``"2002-10-15"``, ``"last"``) or a window
(``("2002-10-01", "2003-03-31")``). A run stores its fields by period index.
:class:`RunPeriods`, exposed as ``run.periods``, turns the first into the
second: ``edges`` are the period bounds, ``step_at`` finds the period that
holds one instant, ``steps_for`` the periods a request names.
"""

from __future__ import annotations

import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.core.time.selection import resolve_instant, resolve_instants, resolve_period

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


class RunPeriods:
    """Stress-period bounds and date lookups bound to one :class:`Run`."""

    def __init__(self, run: Run) -> None:
        self._run = run

    @cached_property
    def edges(self) -> pd.DatetimeIndex | None:
        """The ``n + 1`` edges of the run's stress periods, or ``None`` without dates.

        Period ``i`` is ``[edges[i], edges[i + 1])``. The first edge is the
        ``period_start`` the catalog stores, the others are the end stamps of
        ``run.time_index``. A steady run over a window has one period over the
        whole window. A run registered without a period, a steady run without
        ``[simulation.time]``, has no dates and returns ``None``.
        """
        start = self._run._load_row().get("period_start")
        if start is None or pd.isna(start):
            return None
        # The same wall clock as time_index: the catalog stores naive strings.
        start = pd.Timestamp(start)
        start = start.tz_localize(None) if start.tz is not None else start
        return period_edges(self._run.time_index, start=start)

    def _count(self) -> int | None:
        """Number of stored periods, ``None`` when the catalog records none."""
        n = self._run._load_row().get("n_timesteps")
        if n is None or pd.isna(n):
            return None
        return int(n)

    def step_at(self, time: str | int | datetime.date | pd.Timestamp) -> int:
        """Return the index of the stress period that holds ``time``.

        ``time`` is an ISO date or datetime, ``"first"``, ``"last"``, or an
        integer index (negative counts from the end). A date on the last edge
        is the last period. A steady run over a window resolves every date of
        its window to 0. Raises
        :class:`~hydromodpy.core.time.selection.TimeSelectionError`, a
        ``ValueError``, on a date outside the record or on a run without dates.
        """
        edges = self.edges
        return resolve_instant(time, edges, n_periods=None if edges is not None else self._count())

    def steps_for(
        self,
        time: Any = None,
        period: tuple[Any, Any] | None = None,
    ) -> tuple[int, ...]:
        """Return the stress-period indexes a request names, in order.

        ``time`` is one selector or a list of them, as :meth:`step_at` reads
        them. ``period`` is a ``(start, end)`` pair and keeps every period that
        overlaps it. Give one of them, or neither for every period.
        """
        if time is not None and period is not None:
            raise ValueError("steps_for takes time or period, not both.")
        edges = self.edges
        n_periods = None if edges is not None else self._count()
        if time is not None:
            return resolve_instants(time, edges, n_periods=n_periods)
        if period is not None:
            start, end = period
            return resolve_period(start, end, edges, n_periods=n_periods)
        count = len(edges) - 1 if edges is not None else (n_periods or 1)
        return tuple(range(count))


__all__ = ["RunPeriods"]
