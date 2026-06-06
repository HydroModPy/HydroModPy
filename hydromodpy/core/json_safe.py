"""JSON serialization helpers for mixed scientific Python payloads."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any


def json_safe_value(value: Any) -> Any:
    """Return a value made of JSON-serializable Python primitives."""

    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [json_safe_value(item) for item in value]
    if isinstance(value, set):
        return [json_safe_value(item) for item in sorted(value, key=str)]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return json_safe_value(item())
        except (TypeError, ValueError):
            pass
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return json_safe_value(tolist())
        except (TypeError, ValueError):
            pass
    return str(value)


def json_safe_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe dict with string keys."""

    return {str(key): json_safe_value(value) for key, value in mapping.items()}


__all__ = ["json_safe_mapping", "json_safe_value"]
