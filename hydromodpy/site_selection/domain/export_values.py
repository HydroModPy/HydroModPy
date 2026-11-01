"""Values that the vector exports of a site selection write.

A GeoJSON property or a GeoPackage column holds text, a number, a boolean or
nothing. These helpers turn the attributes of a site into such values, and
name the CRS of a set of features.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def single_or_mixed(values: Iterable[str]) -> str:
    """Return the one non-empty label, ``"mixed"`` for several, ``""`` for none."""
    clean = {value for value in values if value}
    if not clean:
        return ""
    if len(clean) == 1:
        return next(iter(clean))
    return "mixed"


def single_crs(values: Iterable[str]) -> str | None:
    """Return the first non-empty CRS label, or ``None`` when there is none."""
    clean = [value for value in values if value]
    if not clean:
        return None
    return clean[0]


def clean_value(value: Any) -> Any:
    """Return *value* as a property value.

    ``None``, text, numbers and booleans stay as they are, a path becomes its
    text, and anything else becomes JSON text with sorted keys.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def clean_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Return *properties* with text keys and every value passed through :func:`clean_value`."""
    return {str(key): clean_value(value) for key, value in properties.items()}


__all__ = ["clean_properties", "clean_value", "single_crs", "single_or_mixed"]
