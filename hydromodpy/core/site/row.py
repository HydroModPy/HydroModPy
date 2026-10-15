"""One row of a site table: the columns of ``data/sites/catalog.csv``.

The workspace keeps its declared sites in ``data/sites/catalog.csv``, and
``hmp project collect --write-sites`` writes the same columns. A
:class:`SiteRow` fixes those columns and their order, so the catalog writer,
its readers and the plan of a ``[sites]`` project without ``bind`` agree on
one shape. Reading and writing the CSV file belongs to the data layer; this
module only maps one row to and from a plain mapping.

Columns, in order: ``site, label, gauge, uri, x_outlet, y_outlet, crs, tags``.
``tags`` is stored as one cell, the tags joined by ``;``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hydromodpy.core.site.config import SITE_NAME_PATTERN, SITE_URI_PATTERN

SITE_ROW_COLUMNS: tuple[str, ...] = (
    "site",
    "label",
    "gauge",
    "uri",
    "x_outlet",
    "y_outlet",
    "crs",
    "tags",
)
"""The columns of a site table, in the order a writer emits them."""

TAG_SEPARATOR = ";"
"""Separator of the tags inside the ``tags`` cell."""

_NAME_RE = re.compile(SITE_NAME_PATTERN)
_URI_RE = re.compile(SITE_URI_PATTERN)


def _text(value: Any) -> str | None:
    """Return a stripped string, or None for an empty or missing cell."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _number(column: str, value: Any) -> float | None:
    """Return a float, or None for an empty cell; refuse anything else by name."""
    text = _text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"column {column}: {text!r} is not a number") from exc


def _tags(value: Any) -> tuple[str, ...]:
    """Return the tags of one cell, a list or a ``;``-joined string."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        items = [_text(item) for item in value]
    else:
        text = _text(value)
        items = [_text(item) for item in text.split(TAG_SEPARATOR)] if text else []
    return tuple(item for item in items if item)


@dataclass(frozen=True, slots=True)
class SiteRow:
    """One declared site, as a row of a site table."""

    site: str
    label: str | None = None
    gauge: str | None = None
    uri: str | None = None
    x_outlet: float | None = None
    y_outlet: float | None = None
    crs: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a name or a URI that the ``[site]`` section would refuse."""
        if not _NAME_RE.fullmatch(self.site):
            raise ValueError(
                f"column site: {self.site!r} is not a site name; write letters, digits "
                "and underscores only."
            )
        if self.uri is not None and not _URI_RE.fullmatch(self.uri):
            raise ValueError(
                f"column uri: {self.uri!r} is not a site URI; write hubeau:<code> or "
                "bdtopage:<code>."
            )
        if (self.x_outlet is None) != (self.y_outlet is None):
            raise ValueError("columns x_outlet and y_outlet: write both or neither.")

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> SiteRow:
        """Build a row from a mapping of column to cell, as a CSV reader yields it.

        Unknown columns are refused by name: a site table has fixed columns, and
        a free column belongs to a campaign table read through ``bind``.
        """
        unknown = sorted(set(row) - set(SITE_ROW_COLUMNS))
        if unknown:
            raise ValueError(
                f"unknown site table column(s): {', '.join(unknown)}; the columns are "
                f"{', '.join(SITE_ROW_COLUMNS)}."
            )
        site = _text(row.get("site"))
        if site is None:
            raise ValueError("column site: a site row needs a name.")
        return cls(
            site=site,
            label=_text(row.get("label")),
            gauge=_text(row.get("gauge")),
            uri=_text(row.get("uri")),
            x_outlet=_number("x_outlet", row.get("x_outlet")),
            y_outlet=_number("y_outlet", row.get("y_outlet")),
            crs=_text(row.get("crs")),
            tags=_tags(row.get("tags")),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return the row as a mapping in column order, tags joined into one cell."""
        return {
            "site": self.site,
            "label": self.label,
            "gauge": self.gauge,
            "uri": self.uri,
            "x_outlet": self.x_outlet,
            "y_outlet": self.y_outlet,
            "crs": self.crs,
            "tags": TAG_SEPARATOR.join(self.tags),
        }


__all__ = ["SITE_ROW_COLUMNS", "TAG_SEPARATOR", "SiteRow"]
