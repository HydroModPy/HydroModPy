"""``[site] gauge`` as the single source of the station of a catchment.

Before the site existed the station was written in up to seven keys of one
project. Each of them now falls back to ``[site] gauge``; a key that writes a
different station is refused by name when the file is read. A station list
(``station_ids``) that contains the gauge is accepted: loading several
stations and scoring one is a legitimate choice.
"""

from __future__ import annotations

from collections.abc import Sequence

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.site.config import SiteConfig


class GaugeConflictError(ConfigError):
    """A station key names another station than ``[site] gauge``."""


def resolve_gauge(
    site: SiteConfig | None,
    declared: str | Sequence[str] | None,
    *,
    field: str,
) -> str | None:
    """Return the station a key resolves to, or refuse a conflict with the site.

    ``declared`` is the value the key writes (one station, a list, or nothing)
    and ``field`` its dotted name, used in the message. Without a declared
    value the site gauge is returned. A declared value equal to the gauge, or
    a list that contains it, returns the gauge. Without a site gauge the
    declared value is returned (the first one of a list). Anything else raises
    :class:`GaugeConflictError` naming both keys.
    """
    gauge = site.gauge if site is not None else None
    if declared is None or (not isinstance(declared, str) and len(declared) == 0):
        return gauge
    stations = [declared] if isinstance(declared, str) else [str(item) for item in declared]
    if gauge is None:
        return stations[0]
    if gauge in stations:
        return gauge
    written = stations[0] if isinstance(declared, str) else list(stations)
    raise GaugeConflictError(
        f"site.gauge = {gauge!r} but {field} = {written!r}. [site] gauge is the station "
        f"of the catchment: remove {field} to take the gauge, or write the gauge in it."
    )


__all__ = ["GaugeConflictError", "resolve_gauge"]
