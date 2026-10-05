"""Obstacles to flow of the Sandre ROE (Referentiel des Obstacles a l'Ecoulement).

Source: ``https://services.sandre.eaufrance.fr/geo/obs``, layer
``sa:ObstEcoul_FXX`` (metropolitan France), a point per obstacle. The layer
answers GML 3.2 only, so it is read here with the standard library and the
fields it holds are named below, from ``DescribeFeatureType`` and a real
answer measured on 2026-10-05 over the upper Ille (Flume).

- ``CdTypeOuvrage`` is a code of a hierarchy, and a leaf carries its parents:
  ``1.1`` and ``1.1.7`` are dams, ``1.2``, ``1.2.1`` and ``1.2.X`` are weirs,
  ``1.4`` and ``1.4.1`` are obstacles induced by a bridge: the sill under it, a
  drop of the bed, so a weir and not a bridge (a bridge deck is an embankment
  and comes from the BD TOPO). Everything else, ``1.3`` a dike, ``1.5`` a groyne,
  ``1.6`` a fish farm grid and a missing code, is ``other``. So the kind is read
  from the first two levels.
- ``LbEtOuvrage`` is the state: ``Existant``, ``Detruit partiellement``,
  ``Detruit entierement``. Only ``Existant`` is kept.
- ``HautChutEtObstEcoul`` is the drop in metres, as a string, empty for most
  obstacles. ``CdHautChutClObstEcoul`` is a class of drop that is filled more
  often, and is not read: a class is not a height.
- ``NomPrincipalObstEcoul`` is the name.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.data.variables.crossings import records
from hydromodpy.data.variables.crossings.apis import wfs

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

    from hydromodpy.data.managers.base_manager_common import SourceContext

SOURCE_ID: Final = "roe"
WFS_URL: Final = "https://services.sandre.eaufrance.fr/geo/obs"
HOST: Final = "services.sandre.eaufrance.fr"
LAYER: Final = "sa:ObstEcoul_FXX"

_SA: Final = "{http://xml.sandre.eaufrance.fr/}"
_GML: Final = "{http://www.opengis.net/gml/3.2}"
_GML_ID: Final = f"{_GML}id"
_EXISTING: Final = "existant"


def fetch_pages(
    source_cfg: Any,
    *,
    bbox: tuple[float, float, float, float],
    context: SourceContext,
) -> Iterator[gpd.GeoDataFrame]:
    """The existing obstacles touching *bbox*, one page of records at a time (EPSG:2154)."""
    del context
    for rows in wfs.iter_pages(
        WFS_URL,
        LAYER,
        bbox,
        page_size=int(source_cfg.page_size),
        sort_by="gid",
        parse_page=parse_page,
        identify=lambda row: row["id"],
    ):
        yield to_records(rows)


def parse_page(body: bytes) -> list[dict[str, Any]]:
    """The obstacles of one GML page as plain rows, point included."""
    root = ET.fromstring(body)
    rows: list[dict[str, Any]] = []
    for member in root.iter(f"{_SA}ObstEcoul_FXX"):
        row = {child.tag.removeprefix(_SA): (child.text or "").strip() for child in member}
        row["id"] = member.get(_GML_ID, "")
        row["point"] = _point(member)
        rows.append(row)
    return rows


def to_records(rows: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    """The existing obstacles as records, in the fixed columns, EPSG:2154."""
    from shapely.geometry import Point

    geometry: list = []
    kind: list[str] = []
    name: list[str] = []
    drop_m: list[float] = []
    for row in rows:
        if row.get("LbEtOuvrage", "").strip().lower() != _EXISTING:
            continue
        x, y = row["point"]
        geometry.append(Point(x, y))
        kind.append(kind_of(row.get("CdTypeOuvrage")))
        name.append(row.get("NomPrincipalObstEcoul", ""))
        drop_m.append(_number(row.get("HautChutEtObstEcoul")))
    return records.build(
        geometry,
        kind=kind,
        source=SOURCE_ID,
        name=name,
        drop_m=drop_m,
        crs=wfs.QUERY_CRS,
    )


def kind_of(code: str | None) -> str:
    """``dam``, ``weir`` or ``other`` from a ``CdTypeOuvrage`` code."""
    head = ".".join(str(code or "").strip().split(".")[:2])
    return {"1.1": "dam", "1.2": "weir", "1.4": "weir"}.get(head, "other")


def _point(member: ET.Element) -> tuple[float, float]:
    position = member.find(f".//{_GML}Point/{_GML}pos")
    if position is None or not position.text:
        raise DataSourceError(
            f"ROE obstacle {member.get(_GML_ID)!r} has no gml:Point, and the layer is "
            "expected to hold points only."
        )
    x, y = (float(value) for value in re.split(r"\s+", position.text.strip())[:2])
    return x, y


def _number(text: str | None) -> float:
    try:
        return float(str(text).strip())
    except ValueError:
        return float("nan")
