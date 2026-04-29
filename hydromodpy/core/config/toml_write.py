"""Lightweight TOML writing helpers with an internal fallback serializer.

HydroModPy prefers :mod:`tomli_w` when it is installed, but parts of the
runtime only need a small subset of TOML serialisation.  This module keeps
those paths working in lightweight environments by falling back to a small
dependency-free renderer that supports the document shapes HydroModPy emits:

- scalar key/value pairs
- nested tables
- arrays
- arrays of tables
- inline tables inside arrays
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from numbers import Integral, Real
from pathlib import Path
from typing import Any

try:
    import tomli_w as _tomli_w
except Exception:  # pragma: no cover - exercised only when the dependency exists
    _tomli_w = None

_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _format_key(key: str) -> str:
    if _BARE_KEY_RE.fullmatch(key):
        return key
    return json.dumps(key)


def _is_mapping_array(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and bool(value)
        and all(isinstance(item, Mapping) for item in value)
    )


def _format_inline_table(mapping: Mapping[str, Any]) -> str:
    parts = [f"{_format_key(str(key))} = {_format_value(value)}" for key, value in mapping.items()]
    return "{ " + ", ".join(parts) + " }"


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Integral) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, Real) and not isinstance(value, bool):
        number = float(value)
        if math.isnan(number):
            return "nan"
        if math.isinf(number):
            return "+inf" if number > 0 else "-inf"
        return repr(number)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return json.dumps(str(value))
    if isinstance(value, str):
        return json.dumps(value)
    raise TypeError(f"Unsupported TOML scalar type: {type(value).__name__}")


def _format_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return _format_inline_table(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        inner = ", ".join(_format_value(item) for item in value)
        return f"[{inner}]"
    return _format_scalar(value)


def _render_mapping(
    mapping: Mapping[str, Any],
    *,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    lines: list[str] = []
    scalar_items: list[tuple[str, Any]] = []
    nested_items: list[tuple[str, Mapping[str, Any]]] = []
    array_items: list[tuple[str, Sequence[Mapping[str, Any]]]] = []

    for raw_key, value in mapping.items():
        key = str(raw_key)
        if isinstance(value, Mapping):
            nested_items.append((key, value))
        elif _is_mapping_array(value):
            array_items.append((key, value))
        else:
            scalar_items.append((key, value))

    for key, value in scalar_items:
        lines.append(f"{_format_key(key)} = {_format_value(value)}")

    for key, value in nested_items:
        if lines and lines[-1] != "":
            lines.append("")
        section = ".".join(_format_key(part) for part in (*prefix, key))
        lines.append(f"[{section}]")
        lines.extend(_render_mapping(value, prefix=(*prefix, key)))

    for key, items in array_items:
        section = ".".join(_format_key(part) for part in (*prefix, key))
        for item in items:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[[{section}]]")
            lines.extend(_render_mapping(item, prefix=(*prefix, key)))

    return lines


def dumps(payload: Mapping[str, Any]) -> str:
    """Return *payload* rendered as TOML text."""
    if _tomli_w is not None:
        return _tomli_w.dumps(payload)
    lines = _render_mapping(payload)
    return "\n".join(lines).rstrip() + "\n"


def dump(payload: Mapping[str, Any], fp: Any) -> None:
    """Write *payload* to a file object."""
    if _tomli_w is not None:
        _tomli_w.dump(payload, fp)
        return
    text = dumps(payload)
    try:
        fp.write(text)
    except TypeError:
        fp.write(text.encode("utf-8"))


__all__ = ["dump", "dumps"]
