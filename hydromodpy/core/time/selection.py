"""Turn a date a user writes into the stress period a run stored.

A user asks for an instant by its date: ``"2002-10-15"``. A run stores its
periods by index. This module is the one place the two meet, shared by the
figures and the exports.

The convention is the one of :mod:`hydromodpy.core.time.period_aggregation`
and of :class:`hydromodpy.core.time.window.ResolvedSimulationTimeGrid`. A run
of ``n`` periods has ``n + 1`` edges and period ``i`` is the half-open interval
``[edges[i], edges[i + 1])``. A date resolves to the period that holds it. The
last edge closes the record, so it resolves to the last period.

A steady run over a window has one period over the whole window, so every date
of the record resolves to 0. A steady run without a window has no dates at
all: its edges are ``None``, and only ``"first"``, ``"last"`` or an index can
name its one period.

A selector is one of:

- an ISO date or datetime string, or a ``date``, ``datetime`` or
  ``Timestamp`` (a bare TOML date reads as a ``date``);
- ``"first"`` or ``"last"``;
- an integer period index, negative counting from the end.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

__all__ = (
    "TimeSelectionError",
    "grid_edges",
    "period_label",
    "resolve_instant",
    "resolve_instants",
    "resolve_period",
)

_NO_DATES = 'this run has no dates; write "last"'
_KEYWORDS = ("first", "last")
# Spelled with a unit: ``pd.Timedelta(days=1)`` warns under the pinned NumPy.
_ONE_DAY = pd.Timedelta(1, unit="D")


class TimeSelectionError(ValueError):
    """A time selector names no period of the run."""


def _naive(value: Any) -> pd.Timestamp:
    """Return one timestamp, tz-naive in UTC."""
    ts = pd.Timestamp(value)
    if ts.tz is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _edges(edges: Any) -> pd.DatetimeIndex | None:
    """Return ``edges`` as a checked tz-naive index, or ``None`` for a run without dates."""
    if edges is None:
        return None
    index = pd.DatetimeIndex([_naive(edge) for edge in edges])
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
            instant = _naive(text)
        except (ValueError, TypeError) as exc:
            raise TimeSelectionError(refused) from exc
    elif isinstance(selector, _dt.date | pd.Timestamp | np.datetime64):
        instant = _naive(selector)
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
    if instant == index[-1]:
        return n - 1
    return int(index.searchsorted(instant, side="right")) - 1


def _scalar(selectors: Any) -> bool:
    """Return whether ``selectors`` is one selector rather than a list of them."""
    return isinstance(selectors, str | int | np.integer | _dt.date | pd.Timestamp | np.datetime64)


def resolve_instants(
    selectors: Any, edges: Any, *, n_periods: int | None = None
) -> tuple[int, ...]:
    """Return the period index of every selector, in the order given.

    ``selectors`` is an iterable of selectors. A single selector is read as a
    list of one.
    """
    items: Iterable[Any] = (selectors,) if _scalar(selectors) else selectors
    return tuple(resolve_instant(item, edges, n_periods=n_periods) for item in items)


def _period_bound(bound: Any, index: pd.DatetimeIndex | None, n: int, *, start: bool) -> int:
    """Return the index of the first (``start``) or last period a bound keeps.

    A date start keeps the first period that ends after it, a date end the
    last period that starts at or before it. Either is clamped to the record,
    so a window that runs past the record keeps the periods inside it. A date
    wholly outside the record on its own side raises.
    """
    word = _keyword(bound)
    if word is not None:
        return 0 if word == "first" else n - 1
    if _is_index(bound):
        return _from_index(bound, n)
    instant = _as_date(bound)
    if index is None:
        raise TimeSelectionError(f"{_instant_text(instant)}: {_NO_DATES}.")
    outside = instant > index[-1] if start else instant < index[0]
    if outside:
        side = "starting" if start else "ending"
        raise TimeSelectionError(
            f"the period {side} {_instant_text(instant)} is outside the record: {_span(index)}."
        )
    position = int(index.searchsorted(instant, side="right")) - 1
    return min(max(position, 0), n - 1)


def resolve_period(
    start: Any, end: Any, edges: Any, *, n_periods: int | None = None
) -> tuple[int, ...]:
    """Return every period that overlaps the closed interval ``[start, end]``.

    ``start`` and ``end`` are selectors as :func:`resolve_instant` reads
    them. A date bound keeps the periods that overlap the interval, so a
    window that runs past the record keeps the periods inside it. A window
    that overlaps no period raises, and so does a start after the end.
    """
    index = _edges(edges)
    n = _count(index, n_periods)
    first = _period_bound(start, index, n, start=True)
    last = _period_bound(end, index, n, start=False)
    if first > last:
        raise TimeSelectionError(
            f"the period from {start!r} to {end!r} ends before it starts "
            f"(period {first} to period {last})."
        )
    return tuple(range(first, last + 1))


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
