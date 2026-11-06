"""Keys that belong to one catchment, and must vary from site to site.

A field marked ``site_scoped`` (``json_schema_extra = field_metadata(
site_scoped=True)``) holds a value of one catchment: an outlet, a station,
the path of a local series. In a ``[sites]`` project such a value may come
from the site table (``[sites.bind]``) or from ``site_overrides/<site>.toml``,
never from a file every case shares: ninety-nine catchments would run with
the recharge of the first. The plan refuses a case whose resolved document
holds a literal site scoped value, and lists the keys.

The patterns come from the schema
(:func:`hydromodpy.core.config_kit.introspect.site_scoped_paths`): a list
part ends in ``[]`` and a table key is ``*``. :data:`PLAN_SITE_SCOPED_PATHS`
adds the keys the schema cannot mark because they are keys of a free table.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import cache
from typing import Any

from hydromodpy.core.config_kit.introspect import (
    LIST_ITEM_MARK,
    TABLE_KEY_MARK,
    site_scoped_paths,
)

PLAN_SITE_SCOPED_PATHS: tuple[str, ...] = ("display.overrides.cross_section",)
"""Keys of free tables that belong to one catchment: a section oriented on its valley."""

ConcretePath = tuple[str | int, ...]
"""A key path in a resolved document, list indices as integers."""


@cache
def site_scoped_patterns() -> tuple[str, ...]:
    """Return every site scoped pattern of the project schema, sorted."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    return tuple(sorted({*site_scoped_paths(HydroModPyConfig), *PLAN_SITE_SCOPED_PATHS}))


def leaf_paths(payload: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Return the key paths a payload writes: every scalar, list or empty table."""
    found: set[tuple[str, ...]] = set()
    for key, value in payload.items():
        here = (*prefix, str(key))
        if isinstance(value, Mapping) and value:
            found |= leaf_paths(value, here)
        else:
            found.add(here)
    return found


def match_pattern(document: Mapping[str, Any], pattern: str) -> list[ConcretePath]:
    """Return the concrete paths of *document* that *pattern* names and that exist."""
    parts = pattern.split(".")
    return _match(document, parts, ())


def _match(node: Any, parts: Sequence[str], prefix: ConcretePath) -> list[ConcretePath]:
    if not parts:
        return [prefix]
    head, rest = parts[0], parts[1:]
    if head == TABLE_KEY_MARK:
        if not isinstance(node, Mapping):
            return []
        out: list[ConcretePath] = []
        for key, value in node.items():
            out.extend(_match(value, rest, (*prefix, str(key))))
        return out
    if head.endswith(LIST_ITEM_MARK):
        name = head[: -len(LIST_ITEM_MARK)]
        if not isinstance(node, Mapping) or not isinstance(node.get(name), list):
            return []
        out = []
        for index, item in enumerate(node[name]):
            out.extend(_match(item, rest, (*prefix, name, index)))
        return out
    if not isinstance(node, Mapping) or head not in node:
        return []
    return _match(node[head], rest, (*prefix, head))


def is_covered(path: ConcretePath, varying: set[tuple[str, ...]]) -> bool:
    """Whether a site-varying layer writes *path*, a key above it or a key inside it."""
    for leaf in varying:
        shorter = min(len(leaf), len(path))
        if all(path[i] == leaf[i] for i in range(shorter)):
            return True
    return False


def render_path(path: ConcretePath) -> str:
    """Render a concrete path as ``data.hydrometry.sources[0].station_ids``."""
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else part)
    return text


def literal_site_scoped_keys(
    document: Mapping[str, Any], varying: set[tuple[str, ...]]
) -> list[str]:
    """Return the site scoped keys of *document* that no site-varying layer wrote."""
    literal: list[str] = []
    for pattern in site_scoped_patterns():
        for path in match_pattern(document, pattern):
            if not is_covered(path, varying):
                literal.append(render_path(path))
    return sorted(literal)


__all__ = [
    "PLAN_SITE_SCOPED_PATHS",
    "ConcretePath",
    "is_covered",
    "leaf_paths",
    "literal_site_scoped_keys",
    "match_pattern",
    "render_path",
    "site_scoped_patterns",
]
