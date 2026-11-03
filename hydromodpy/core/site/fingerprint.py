"""The fingerprint of a site: a pure function of its declaration.

Two projects on the same catchment carry the same fingerprint, whatever they
call the site and whatever DEM they delineate it on. The fingerprint reads the
declaration only (CRS, kind of definition, outlet rounded to the meter, or the
digest of the polygon file) and never a computed product: the same outlet on a
25 m and on a 75 m DEM gives one fingerprint and two areas, so a comparison
table carries the area and the DEM resolution beside it.

Form: the first 16 hex digits of the SHA-256 of a canonical JSON document
(sorted keys, no spaces).
"""

from __future__ import annotations

import hashlib
import json

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


__all__ = ["FINGERPRINT_LENGTH", "site_fingerprint"]
