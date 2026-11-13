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
