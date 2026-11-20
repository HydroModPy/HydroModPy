"""The one check of an instant a user writes: a date, ``first``, ``last`` or a period index."""

from __future__ import annotations

import datetime as dt
from typing import Any

TIME_WORDS = ("first", "last")
"""The words that name the first and the last period of a run."""

TIME_FORMS = f"a date (YYYY-MM-DD), {' or '.join(map(repr, TIME_WORDS))}, or a period index"


def instant(value: Any, where: str) -> str | int:
    """Return ``value`` as an ISO date text, a word of ``TIME_WORDS`` or an integer index.

    Only the shape is checked. Whether a date falls inside the record needs the time
    grid of a run, which ``core/time/selection.py`` reads. A bare TOML date is kept as
    its ISO text. Refuses anything else with the forms an instant takes.
    """
    if isinstance(value, bool):
        raise ValueError(f"{where} = {value!r} is not a time; write {TIME_FORMS}.")
    if isinstance(value, int):
        return value
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in TIME_WORDS:
            return text.lower()
        if text[:1].isdigit():
            try:
                dt.datetime.fromisoformat(text)
            except ValueError:
                pass  # Not a date: refused below with the forms a time takes.
            else:
                return text
    raise ValueError(f"{where} = {value!r} is not a time; write {TIME_FORMS}.")


def calendar_instant(value: Any, where: str) -> dt.datetime:
    """Return a calendar instant a TOML file writes as a date, a datetime or an ISO 8601 string.

    A bare TOML date reads as its midnight. A number is refused, because a parser would
    take it for seconds since 1970, and so is a string that is not ISO 8601, such as
    ``"01/02/2003"``, whose day and month order is a guess.
    """
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    if isinstance(value, str) and len(value.strip()) >= 8:
        try:
            return dt.datetime.fromisoformat(value.strip())
        except ValueError:
            pass  # Not ISO 8601: refused below with the form a date takes.
    raise ValueError(
        f"{where} = {value!r} is not a date; write an ISO 8601 date such as 2003-01-01 "
        'or "2003-01-01T00:00:00".'
    )
