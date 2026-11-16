"""Short text summaries, for the objects a user reads at the Python prompt."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields
from typing import Any

LINE = 100
"""A value shown on one line is cut at this many characters."""


def one_line(value: object, none: str = "none") -> str:
    """Return ``value`` on one line: the keys of a mapping, else the first line of its repr."""
    if value is None:
        return none
    if isinstance(value, Mapping):
        return ", ".join(str(key) for key in value) or none
    text = repr(value).split("\n", 1)[0]
    return text if len(text) <= LINE else f"{text[: LINE - 4]} ..."


def members(value: object, none: str = "none") -> list[tuple[str, str]]:
    """Return each field of a dataclass with its value on one line, as the rows of a summary."""
    return [(item.name, one_line(getattr(value, item.name), none)) for item in fields(value)]


def extent(points: Any) -> str:
    """Say the box of an array of ``(x, y)`` points in m, as the row of a summary."""
    x, y = points[:, 0], points[:, 1]
    return f"x {x.min():.0f} to {x.max():.0f} m, y {y.min():.0f} to {y.max():.0f} m"


def area_span(areas: Any) -> str:
    """Say the areas of the cells in m2: their shape, their range and their sum."""
    low, high, total = areas.min(), areas.max(), areas.sum() / 1e6
    return f"array {areas.shape}, {low:.6g} to {high:.6g} m2, {total:.2f} km2 in all"


def summary(title: str, rows: Iterable[tuple[str, object]]) -> str:
    """Return ``title``, then one aligned ``name  value`` line per row, as a ``__repr__``."""
    lines = [(name, str(value)) for name, value in rows]
    width = max((len(name) for name, _ in lines), default=0)
    return "\n".join([title, *(f"  {name:<{width}}  {value}" for name, value in lines)])
