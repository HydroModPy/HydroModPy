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
- ``HautChutEtObstEcoul`` is the drop in meters, as a string, empty for most
  obstacles. ``CdHautChutClObstEcoul`` is a class of drop that is filled more
  often, and is not read: a class is not a height.
- ``NomPrincipalObstEcoul`` is the name.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, ClassVar, Final

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.logging import get_logger
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    require_period,
    require_selectors,
    shipped_hosts,
)
from hydromodpy.data.variables.crossings import records
from hydromodpy.data.variables.crossings.apis import bdtopo, wfs

if TYPE_CHECKING:
    import geopandas as gpd

logger = get_logger(__name__)

SOURCE_ID: Final = "roe"
WFS_URL: Final = "https://services.sandre.eaufrance.fr/geo/obs"
HOST: Final = "services.sandre.eaufrance.fr"
LAYER: Final = "sa:ObstEcoul_FXX"

DEFAULT_PAGE_SIZE: Final = bdtopo.DEFAULT_PAGE_SIZE
"""The page size ``_ApiCrossingsSource`` declares for this source."""

_SA: Final = "{http://xml.sandre.eaufrance.fr/}"
_GML: Final = "{http://www.opengis.net/gml/3.2}"
_GML_ID: Final = f"{_GML}id"
_EXISTING: Final = "existant"


def fetch_pages(
    *,
    bbox: tuple[float, float, float, float],
    page_size: int,
) -> Iterator[gpd.GeoDataFrame]:
    """The existing obstacles touching *bbox*, one page of records at a time (EPSG:2154)."""
    for rows in wfs.iter_pages(
        WFS_URL,
        LAYER,
        bbox,
        page_size=int(page_size),
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


class RoeCrossings:
    """The obstacles of the ROE, one GeoPackage per request box.

    The port class over :func:`fetch_pages`: the existing obstacles of the
    request's extent, written page by page so memory holds one page however
    many features the box holds. The file is ``crossings_roe_<bbox
    hash>.gpkg``, the name the catalog caches a download under, and it is
    ``state = "raw"``: the provider's records as it answered them.
    """

    source_id: ClassVar[str] = SOURCE_ID
    section: ClassVar[str] = "crossings"
    payload_kind: ClassVar[PayloadKind] = "files"
    extent_crs: ClassVar[str] = wfs.QUERY_CRS
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    writes_out_dir: ClassVar[bool] = True

    def __init__(self, *, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        self.page_size = int(page_size)
        self.variables = ("crossings",)
        self.hosts = shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Write the obstacles of the request's extent into a GeoPackage."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        request.out_dir.mkdir(parents=True, exist_ok=True)
        from hydromodpy.data.variables.crossings.manager import cache_file_name

        out_path = request.out_dir / cache_file_name(self.source_id, extent.bbox)
        started = time.perf_counter()
        with staged_path(out_path) as staged:
            count = records.append_pages(
                staged,
                fetch_pages(bbox=extent.bbox, page_size=self.page_size),
                wfs.QUERY_CRS,
            )
            if count == 0:
                records.empty(wfs.QUERY_CRS).to_file(staged, driver="GPKG")
        logger.info(
            "Crossings from %s: %d features in %s, %.1f s",
            self.source_id,
            count,
            out_path,
            time.perf_counter() - started,
        )
        from hydromodpy.data.contracts.file_record import FileRecord

        record = FileRecord.of(out_path, state="raw", nodata=None, origin=WFS_URL)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            files=(record,),
            records=count,
            metadata={"page_size": self.page_size},
        )
