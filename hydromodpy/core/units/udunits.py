"""The one spelling of a unit in a stored table: udunits, as the field registry writes it.

A table takes its units from solvers, data providers and hand-written TOML, each
with its own habit: ``m3/s``, ``mm/day``, ``D``, ``-``. A reader that compares two
of them needs one spelling, so the store writes ``m3 s-1``, ``mm d-1``, ``d`` and
``1``. This changes how a unit is written and never which unit it is. A text this
grammar cannot read, such as a provider's ``mg(NO3)/L``, is kept as it was written.
"""

from __future__ import annotations

import re

_DIMENSIONLESS = frozenset({"-", "1", "dimensionless", "unitless", "adimensional"})
_PERCENT = frozenset({"%", "percent", "pct"})

_NAMES: dict[str, str] = {
    "D": "d",
    "day": "d",
    "days": "d",
    "j": "d",
    "jour": "d",
    "hour": "h",
    "hours": "h",
    "hr": "h",
    "minute": "min",
    "minutes": "min",
    "mn": "min",
    "sec": "s",
    "second": "s",
    "seconds": "s",
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
    "l": "L",
    "liter": "L",
    "liters": "L",
    "litre": "L",
    "litres": "L",
    "°C": "degC",
    "Celsius": "degC",
    "celsius": "degC",
}

_TOKEN = re.compile(r"^(?P<name>[^\W\d_]+|°C)(?:\^|\*\*)?(?P<power>[+-]?\d+)?$")
_SEPARATOR = re.compile(r"[\s.·]+|(?<!\*)\*(?!\*)")


def udunits_spelling(unit: str | None) -> str:
    """Return ``unit`` in udunits spelling, ``""`` when no unit is given."""
    text = str(unit or "").strip()
    if not text:
        return ""
    if text in _DIMENSIONLESS:
        return "1"
    if text in _PERCENT:
        return "percent"
    terms: list[str] = []
    for position, group in enumerate(text.split("/")):
        for token in _SEPARATOR.split(group.strip()):
            term = _term(token, sign=1 if position == 0 else -1)
            if term is None:
                return text
            terms.append(term)
    kept = [term for term in terms if term != "1"]
    return " ".join(kept) if kept else "1"


def _term(token: str, *, sign: int) -> str | None:
    """Return one factor of a unit with its power, None when it is no factor."""
    if token == "1":
        return "1"
    match = _TOKEN.match(token)
    if match is None:
        return None
    name = _NAMES.get(match["name"], match["name"])
    power = sign * int(match["power"] or 1)
    return name if power == 1 else f"{name}{power}"


__all__ = ["udunits_spelling"]
