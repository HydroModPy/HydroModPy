"""Turn a date a user writes into the stress period a run stored.

A user asks for an instant by its date: ``"2002-10-15"``. A run stores its
periods by index. This module is the one place the two meet, shared by the
figures and the exports.

The convention is the one of :mod:`hydromodpy.core.time.period_aggregation`
and of :class:`hydromodpy.core.time.window.ResolvedSimulationTimeGrid`. A run
of ``n`` periods has ``n + 1`` edges, and the stamp of period ``i`` is its end,
``edges[i + 1]``. A date ``t`` reads the period ``(edges[i], edges[i + 1]]`` that
holds it, so a date equal to a stamp reads the period that stamp closes. A date
copied from the time axis of a NetCDF or from a CSV finds its own value again.
The first edge opens the record and closes nothing, so it reads the first period.

A steady run over a window has one period over the whole window, so every date
of the record resolves to 0. A steady run without a window has no dates at
all: its edges are ``None``, and only ``"first"``, ``"last"`` or an index can
name its one period.

A selector is one of:

- an ISO date or datetime string, or a ``date``, ``datetime`` or
  ``Timestamp`` (a bare TOML date reads as a ``date``);
- ``"first"`` or ``"last"``;
- an integer period index, negative counting from the end.

``period_label`` names a period (``2002-10``, ``2002-10-15`` or a span), and
``grid_edges`` reads the edges of a resolved time grid when a config is checked. A date
outside the record raises ``TimeSelectionError``, which names the record span.
``in_series_window`` is the one reading of a window over a series: it keeps the periods
that ``resolve_period`` keeps, a simulated value by its stamp and a measurement by its
date.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import ResultsError
from hydromodpy.core.time.period_aggregation import naive_timestamp

__all__ = (
    "TimeSelectionError",
    "grid_edges",
    "in_series_window",
    "period_label",
    "resolve_instant",
    "resolve_instants",
    "resolve_period",
    "resolve_state",
)

_NO_DATES = 'this run has no dates; write "last"'
_KEYWORDS = ("first", "last")
# Spelled with a unit: ``pd.Timedelta(days=1)`` warns under the pinned NumPy.
_ONE_DAY = pd.Timedelta(1, unit="D")


class TimeSelectionError(ResultsError, ValueError):
    """A time selector names no period of the run."""


def _edges(edges: Any) -> pd.DatetimeIndex | None:
    """Return ``edges`` as a checked tz-naive index, or ``None`` for a run without dates.

    A tz-naive index is taken as it is, so a caller that reads several selectors
    against one grid converts its edges once.
    """
    if edges is None:
        return None
    if isinstance(edges, pd.DatetimeIndex) and edges.tz is None:
        index = edges
    else:
        index = pd.DatetimeIndex([naive_timestamp(edge) for edge in edges])
    if len(index) < 2:
        raise ValueError(f"a record needs at least two edges, got {len(index)}.")
    if not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("the period edges must be strictly increasing.")
    return index


def _count(edges: pd.DatetimeIndex | None, n_periods: int | None) -> int:
    """Return the number of periods, checked against the edges when both are given."""
    if edges is not None:
        n = len(edges) - 1
        if n_periods is not None and int(n_periods) != n:
            raise ValueError(f"{len(edges)} edges hold {n} periods, not {n_periods}.")
        return n
    n = 1 if n_periods is None else int(n_periods)
    if n < 1:
        raise ValueError(f"a run holds at least one period, got {n_periods}.")
    return n


def _instant_text(ts: pd.Timestamp) -> str:
    """Return a timestamp as a date when it falls on midnight, else to the minute."""
    if ts == ts.normalize():
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def _span(edges: pd.DatetimeIndex) -> str:
    """Return the record span a message names."""
    return f"the record runs from {_instant_text(edges[0])} to {_instant_text(edges[-1])}"


def _is_index(selector: Any) -> bool:
    """Return whether ``selector`` is an integer index, a bool excluded."""
    return isinstance(selector, int | np.integer) and not isinstance(selector, bool | np.bool_)


def _as_date(selector: Any) -> pd.Timestamp:
    """Return a date selector as a tz-naive timestamp, or raise a named error."""
    refused = f'{selector!r} is not a date (YYYY-MM-DD), "first", "last" or a period index.'
    if isinstance(selector, str):
        text = selector.strip()
        # pandas reads "now" and "today" as the wall clock, never a date of a record.
        if not text[:1].isdigit():
            raise TimeSelectionError(refused)
        try:
            instant = naive_timestamp(text)
        except (ValueError, TypeError) as exc:
            raise TimeSelectionError(refused) from exc
    elif isinstance(selector, _dt.date | pd.Timestamp | np.datetime64):
        instant = naive_timestamp(selector)
    else:
        raise TimeSelectionError(refused)
    if pd.isna(instant):
        raise TimeSelectionError(refused)
    return instant


def _keyword(selector: Any) -> str | None:
    """Return ``"first"`` or ``"last"`` when ``selector`` spells one, else ``None``."""
    if isinstance(selector, str):
        word = selector.strip().lower()
        if word in _KEYWORDS:
            return word
    return None


def _from_index(selector: Any, n: int) -> int:
    """Return an integer index within ``[0, n)``, negative counting from the end."""
    i = int(selector)
    position = i + n if i < 0 else i
    if not 0 <= position < n:
        raise TimeSelectionError(
            f"period index {i} is out of range: the run holds {n} period"
            f"{'s' if n > 1 else ''} (0 to {n - 1}, or -{n} to -1)."
        )
    return position


def resolve_instant(selector: Any, edges: Any, *, n_periods: int | None = None) -> int:
    """Return the index of the period ``selector`` names.

    Parameters
    ----------
    selector
        An ISO date or datetime, ``"first"``, ``"last"``, or an integer
        index (negative counts from the end).
    edges
        The ``n + 1`` period edges of the run, or ``None`` for a run without
        dates.
    n_periods
        The number of periods. Checked against ``edges`` when both are given.
        A run without dates defaults to one period.

    Raises
    ------
    TimeSelectionError
        The selector names no period: a date before the first edge or after
        the last one, a date on a run without dates, an index out of range, or
        a value that is none of the accepted forms.
    """
    index = _edges(edges)
    n = _count(index, n_periods)
    word = _keyword(selector)
    if word is not None:
        return 0 if word == "first" else n - 1
    if _is_index(selector):
        return _from_index(selector, n)
    instant = _as_date(selector)
    if index is None:
        raise TimeSelectionError(f"{_instant_text(instant)}: {_NO_DATES}.")
    if instant < index[0] or instant > index[-1]:
        raise TimeSelectionError(f"{_instant_text(instant)} is outside the record: {_span(index)}.")
    return max(int(index.searchsorted(instant, side="left")) - 1, 0)


def resolve_state(selector: Any, edges: Any, *, n_periods: int) -> int:
    """Return the index of the one state a single-state reader takes.

    ``selector`` is read as :func:`resolve_instant` reads it: a date takes the
    period ``(s, e]`` that holds it, and a state is the value at the stamp ``e``.
    A run of one period with no dates serves that state to any selector: nothing
    is there to tell a date from another.
    ``edges`` are the run's ``n_periods + 1`` period edges, or ``None``.

    The calibration scores a network output at this state, and a figure of the
    run redraws it at the same one.
    """
    usable = edges if edges is not None and len(edges) >= 2 else None
    if usable is None and n_periods == 1:
        return 0
    return resolve_instant(selector, usable, n_periods=n_periods)


def _scalar(selectors: Any) -> bool:
    """Return whether ``selectors`` is one selector rather than a list of them."""
    return isinstance(selectors, str | int | np.integer | _dt.date | pd.Timestamp | np.datetime64)


def resolve_instants(
    selectors: Any, edges: Any, *, n_periods: int | None = None
) -> tuple[int, ...]:
    """Return the period index of every selector, in the order given.

    ``selectors`` is an iterable of selectors. A single selector is read as a
    list of one. A list where two selectors read one period is refused, naming
    them: under ``(s, e]`` the first edge and the first stamp read the same
    period, so a list of month starts would read January twice and lose the last
    month without a word.
    """
    items: tuple[Any, ...] = (selectors,) if _scalar(selectors) else tuple(selectors)
    steps = tuple(resolve_instant(item, edges, n_periods=n_periods) for item in items)
    seen: dict[int, Any] = {}
    for item, step in zip(items, steps, strict=True):
        if step in seen:
            raise TimeSelectionError(
                f"{seen[step]!r} and {item!r} read the same period, number {step}: a date "
                "reads the period that ends on or after it. Keep one of them, or write a "
                "window, period = (start, end), to read every period between two dates."
            )
        seen[step] = item
    return steps


def _period_bound(bound: Any, index: pd.DatetimeIndex | None, n: int, *, start: bool) -> int:
    """Return the index of the first (``start``) or last period a bound keeps.

    A date start keeps the first period that ends after it, a date end the
    last period that starts before it, the one its date reads. Either is clamped
    to the record, so a window that runs past the record keeps the periods inside
    it. A start on the last edge or past it has no period after it, and an end on
    the first edge or before it has none before it, so both raise.
    """
    word = _keyword(bound)
    if word is not None:
        return 0 if word == "first" else n - 1
    if _is_index(bound):
        return _from_index(bound, n)
    instant = _as_date(bound)
    if index is None:
        raise TimeSelectionError(f"{_instant_text(instant)}: {_NO_DATES}.")
    outside = instant >= index[-1] if start else instant <= index[0]
    if outside:
        side = "starting" if start else "ending"
        raise TimeSelectionError(
            f"the period {side} {_instant_text(instant)} is outside the record: {_span(index)}. "
            "To read the period a date falls in, give that one date."
        )
    position = int(index.searchsorted(instant, side="right" if start else "left")) - 1
    return min(max(position, 0), n - 1)


def resolve_period(
    start: Any, end: Any, edges: Any, *, n_periods: int | None = None
) -> tuple[int, ...]:
    """Return every period with time inside the window from ``start`` to ``end``.

    ``start`` and ``end`` are selectors as :func:`resolve_instant` reads
    them. A date bound keeps the periods that overlap the window, so a window
    that runs past the record keeps the periods inside it, and two stamps keep
    the periods between them. A window of one date reads the period that date
    reads. A window that overlaps no period raises, and so does a start after
    the end.
    """
    index = _edges(edges)
    n = _count(index, n_periods)
    if _same_date(start, end):
        return (resolve_instant(start, index, n_periods=n),)
    first = _period_bound(start, index, n, start=True)
    last = _period_bound(end, index, n, start=False)
    if first > last:
        raise TimeSelectionError(
            f"the period from {start!r} to {end!r} ends before it starts "
            f"(period {first} to period {last})."
        )
    return tuple(range(first, last + 1))


def _same_date(start: Any, end: Any) -> bool:
    """Return whether two bounds name one date, indexes and keywords left out."""
    if _keyword(start) is not None or _keyword(end) is not None:
        return False
    if _is_index(start) or _is_index(end):
        return False
    return _as_date(start) == _as_date(end)


def _window_bounds(period: Any) -> tuple[Any, Any]:
    """Return the two bounds of a window, a year as text standing for that calendar year."""
    if isinstance(period, str):
        if not period.strip().isdigit():
            raise TimeSelectionError(f"{period!r} is not a year nor a (start, end) pair.")
        year = int(period)
        return f"{year}-01-01", f"{year + 1}-01-01"
    start, end = period
    return start, end


def _series_span(period: Any, edges: Any) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the span a window over a series reads.

    On a run with dates this is the span of the periods :func:`resolve_period`
    keeps, so a series and a field read one window the same way. Without edges
    the two bounds are the span, and only a date range has a meaning there.
    """
    start, end = _window_bounds(period)
    index = _edges(edges)
    if index is not None:
        periods = resolve_period(start, end, index)
        return index[periods[0]], index[periods[-1] + 1]
    if _same_date(start, end):
        resolve_period(start, end, None)
    lo, hi = _as_date(start), _as_date(end)
    if lo > hi:
        raise TimeSelectionError(f"the period from {start!r} to {end!r} ends before it starts.")
    return lo, hi


def in_series_window(times: Any, *, observed: Any, period: Any, edges: Any = None) -> np.ndarray:
    """Return the mask of the rows of a series a window keeps.

    This is the one reading of a window over a series, shared by ``Run.read``,
    ``Run.timeseries``, the catalog and the CSV export. A simulated value is
    stamped at the end of its period, so a window keeps ``(lo, hi]``. An
    observation is stamped when it was taken, so a window keeps ``[lo, hi)``. Each
    keeps what falls in the periods of the window.

    Parameters
    ----------
    times
        The stamps of the rows, read in UTC.
    observed
        One boolean for all the rows, or one per row: whether the row is a measurement.
    period
        ``(start, end)`` selectors as :func:`resolve_period` reads them, or a
        year as text, ``"2002"``.
    edges
        The ``n + 1`` period edges of the run. ``None`` reads the two bounds as they
        are, for a caller that holds the span already or a run without edges.
    """
    lo, hi = _series_span(period, edges)
    stamps = pd.DatetimeIndex(times)
    if stamps.tz is not None:
        stamps = stamps.tz_convert("UTC").tz_localize(None)
    taken = np.asarray((stamps >= lo) & (stamps < hi))
    closed = np.asarray((stamps > lo) & (stamps <= hi))
    return np.where(np.asarray(observed, dtype=bool), taken, closed)


def _is_midnight(ts: pd.Timestamp) -> bool:
    """Return whether ``ts`` falls on midnight."""
    return ts == ts.normalize()


def period_label(i: int, edges: Any) -> str:
    """Return how a title names period ``i`` of a run.

    ``"2002"`` for one calendar year, ``"2002-10"`` for one calendar month,
    ``"2002-10-15"`` for one day, and ``"2000-01-01 to 2002-12-31"`` for any
    other span, its last day included. A span that does not fall on midnight
    names its exclusive end to the minute. A run without dates has no label and
    returns ``""``. ``i`` may be negative, counting from the end.
    """
    index = _edges(edges)
    if index is None:
        return ""
    position = _from_index(i, len(index) - 1)
    start, end = index[position], index[position + 1]
    if _is_midnight(start) and _is_midnight(end):
        if start.day == 1 and end == start + pd.DateOffset(months=1):
            return start.strftime("%Y-%m")
        if start.dayofyear == 1 and end == start + pd.DateOffset(years=1):
            return start.strftime("%Y")
        if end == start + _ONE_DAY:
            return start.strftime("%Y-%m-%d")
        last_day = end - _ONE_DAY
        return f"{start.strftime('%Y-%m-%d')} to {last_day.strftime('%Y-%m-%d')}"
    return f"{_instant_text(start)} to {_instant_text(end)}"


def grid_edges(grid: Any) -> pd.DatetimeIndex | None:
    """Return the period edges of a resolved simulation time grid.

    ``grid`` is a :class:`~hydromodpy.core.time.window.ResolvedSimulationTimeGrid`
    or a :class:`~hydromodpy.core.time.window.ResolvedSteadySimulationTimeGrid`.
    A grid without boundaries, the steady grid of a run without a window, and
    ``None`` return ``None``: the run has no dates.
    """
    if grid is None:
        return None
    boundaries: Sequence[Any] = tuple(getattr(grid, "boundaries", ()) or ())
    if len(boundaries) < 2:
        return None
    return _edges(boundaries)
