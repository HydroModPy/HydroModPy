"""The ``[site]`` section: which catchment a project models.

A real catchment (``kind`` other than a synthetic domain) is named by a
site, so two projects on the same river recognize each other and an index can
group runs by catchment rather than by project folder. The section is a root
section of the project config, documented by the normal walk of the model.

TOML form::

    [site]
    name = "nancon"  # required, [A-Za-z0-9_]+
    label = "Le Nancon a Lecousse"  # optional, free text
    gauge = "J0014010"  # optional, the station scored by default
    uri = "hubeau:J0014010"  # optional, hubeau:<code> or bdtopage:<code>

Two functions of the declaration live here too. :func:`site_fingerprint`
recognizes a site from its declaration only (CRS, kind of definition, outlet
rounded to the meter, or the digest of the polygon file), never from a computed
product: the same outlet on a 25 m and on a 75 m DEM gives one fingerprint and
two areas. Its form is the first 16 hex digits of the SHA-256 of a canonical
JSON document (sorted keys, no spaces). :func:`resolve_gauge` makes
``[site] gauge`` the single source of the station of a catchment: each key that
names a station falls back to it, and a key that writes a different station is
refused by name. A station list (``station_ids``) that contains the gauge is
accepted.

``resolve_gauge`` is the one source of the station that other keys fall back to, and it
raises ``GaugeConflictError`` when they disagree.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import StationName
from hydromodpy.core.exceptions import ConfigError

SITE_NAME_PATTERN = r"^[A-Za-z0-9_]+$"
"""Grammar of a site name: letters, digits and underscores, case kept.

The dash is reserved: it separates the site from the recipe in a case id
(``<site>-<recipe>``).
"""

SITE_URI_PATTERN = r"^(hubeau|bdtopage):[A-Za-z0-9_-]+$"
"""Grammar of a site URI: a registry prefix, a colon and the code in that registry."""


class SiteConfig(HydroModelBase):
    """The catchment a project models, declared once for every key that needs it."""

    name: Annotated[str, Profile.USER] = Field(
        pattern=SITE_NAME_PATTERN,
        description=(
            "Name of the catchment: letters, digits and underscores, case kept. It is "
            "the identity of the site inside the workspace, the value of the site "
            "column of the index and of every exported table. A real catchment "
            "(geographic.catchment.kind from_outlet_coord, from_polyg_shp or "
            "dem) is refused without it. The dash is reserved: it separates the site "
            "from the recipe in a case id."
        ),
        examples=["nancon"],
    )
    label: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Readable name of the catchment, shown in reports, figure footers and "
            "tables. Free text; unset, the name is shown."
        ),
        examples=["Le Nançon à Lécousse"],
    )
    gauge: Annotated[StationName | None, Profile.USER] = Field(
        default=None,
        description=(
            "Station that measures the catchment, written once for every key that "
            "names it. A station source of [data.hydrometry], [data.recharge] or "
            "[data.runoff] (custom chronicles or hubeau) with no station_ids reads "
            "this station; a station_ids that leaves it out is refused by name. "
            "[metrics] station and a point output's observes default to it. "
            "Unset, a run that loads exactly one discharge station takes that station "
            "as its gauge and writes it in its manifest."
        ),
        examples=["J0014010"],
    )
    uri: Annotated[str | None, Profile.USER] = Field(
        default=None,
        pattern=SITE_URI_PATTERN,
        description=(
            "Identifier of the catchment in a public registry, written "
            "hubeau:<station code> or bdtopage:<code>. It is the only key that "
            "names the same catchment in two workspaces."
        ),
        examples=["hubeau:J0014010"],
    )


FINGERPRINT_LENGTH = 16
"""Number of hex digits kept from the SHA-256 digest."""


def site_fingerprint(
    *,
    crs: str,
    kind: str,
    outlet: tuple[float, float] | None = None,
    polygon_sha256: str | None = None,
) -> str:
    """Return the fingerprint of a site declaration.

    ``kind`` is the catchment definition (``from_outlet_coord``,
    ``from_polyg_shp``, ``dem``). ``outlet`` is rounded to the meter, so a
    coordinate copied with more or fewer decimals names the same site.
    ``polygon_sha256`` is the digest of the polygon file. One of the two is
    required.
    """
    if outlet is None and polygon_sha256 is None:
        raise ValueError("a site fingerprint needs an outlet or a polygon digest")
    document: dict[str, object] = {"crs": str(crs), "kind": str(kind)}
    if outlet is not None:
        x, y = outlet
        document["outlet"] = [round(float(x)), round(float(y))]
    if polygon_sha256 is not None:
        document["polygon_sha256"] = str(polygon_sha256).lower()
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


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


__all__ = [
    "FINGERPRINT_LENGTH",
    "SITE_NAME_PATTERN",
    "SITE_URI_PATTERN",
    "GaugeConflictError",
    "SiteConfig",
    "resolve_gauge",
    "site_fingerprint",
]
