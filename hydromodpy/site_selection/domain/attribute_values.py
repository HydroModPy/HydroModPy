"""Read one value from the attributes of a candidate site.

Providers and imported tables name the same quantity in several ways, such as
``flow_station_id``, ``hydro_station_id`` or ``station_id``. Each reader takes
the names in order of preference and returns the first value it can use.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_TRUE_TEXTS = {"1", "true", "t", "yes", "y", "oui", "o"}
_FALSE_TEXTS = {"0", "false", "f", "no", "n", "non"}


def first_text(attributes: Mapping[str, Any], *keys: str) -> str | None:
    """Return the first value that is not blank once stripped, as text."""
    for key in keys:
        value = attributes.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def first_number(attributes: Mapping[str, Any], *keys: str) -> float | None:
    """Return the first value that reads as a float, skipping empty text."""
    for key in keys:
        value = attributes.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def first_bool(attributes: Mapping[str, Any], *keys: str) -> bool | None:
    """Return the first value that reads as a yes or a no, in English or French."""
    for key in keys:
        value = attributes.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE_TEXTS:
            return True
        if text in _FALSE_TEXTS:
            return False
    return None


__all__ = ["first_bool", "first_number", "first_text"]
