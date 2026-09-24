"""Fetch hydrography from OpenStreetMap via Overpass API.

``fetch`` serves the hydrography manager. :class:`OsmSource` puts the same
function behind the data-source port. The third ``features`` source
and the one that shows what the payload kind does **not** promise: Overpass
answers with whatever contributors tagged, so two calls a year apart over one
basin are not the same linework. The port says the shape of the answer, never
its authority.

Like :class:`~hydromodpy.data.variables.hydrography.apis.bdtopage.BdTopageSource` it builds the
Pydantic section its provider function demands, from the one field that
function reads. Rewriting the function to take that field directly is the
better end state and not this phase.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.io.http_client import get_default_client
from hydromodpy.core.logging import get_logger
from hydromodpy.data.variables.hydrography.apis.features import FeatureSource

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

logger = get_logger(__name__)


def fetch(
    config: HydrographySourceConfig, bbox_wgs84: tuple[float, float, float, float]
) -> gpd.GeoDataFrame:
    """Download OSM waterways inside *bbox_wgs84* ``(lon_min, lat_min, lon_max, lat_max)``.

    Returns a GeoDataFrame in EPSG:4326.
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    minx, miny, maxx, maxy = bbox_wgs84
    waterway_types = config.waterway_types

    type_clauses = "\n".join(
        f'  way["waterway"="{wt}"]({miny},{minx},{maxy},{maxx});\n'
        f'  relation["waterway"="{wt}"]({miny},{minx},{maxy},{maxx});'
        for wt in waterway_types
    )
    overpass_query = f"[out:json];\n(\n{type_clauses}\n);\nout geom;"

    overpass_url = "https://overpass-api.de/api/interpreter"
    logger.info("Querying Overpass API for waterway types %s", waterway_types)

    response = get_default_client().get(
        overpass_url,
        params={"data": overpass_query},
        stream=True,
        timeout=300,
    )
    response.raise_for_status()

    try:
        data = json.loads(response.text)
    finally:
        response.close()

    features: list[dict] = []
    for element in data.get("elements", []):
        if "geometry" not in element:
            continue
        coords = [(node["lon"], node["lat"]) for node in element["geometry"]]
        if len(coords) < 2:
            continue
        water_type = element.get("tags", {}).get("waterway", "")
        if water_type not in waterway_types:
            continue
        intermittent = 2 if element.get("tags", {}).get("intermittent", "no") == "yes" else 1
        features.append(
            {
                "geometry": LineString(coords),
                "id": element["id"],
                "waterway": water_type,
                "intermit": intermittent,
            }
        )

    if not features:
        logger.warning("No OSM waterway data found in bbox %s", bbox_wgs84)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
    logger.info("OSM: fetched %d waterway features", len(gdf))
    return gdf


DEFAULT_WATERWAY_TYPES: tuple[str, ...] = ("river", "stream")
"""The default ``HydrographySourceConfig`` declares for this source.

Repeated here rather than imported, so constructing a source pulls in neither
pydantic nor the config kit. ``test_the_declared_defaults_match_the_config``
keeps the two in step.
"""


class OsmSource(FeatureSource):
    """OpenStreetMap waterways, served by the Overpass API."""

    source_id: ClassVar[str] = "osm"
    hosts: ClassVar[tuple[str, ...]] = ("overpass-api.de",)

    def __init__(self, *, waterway_types: tuple[str, ...] = DEFAULT_WATERWAY_TYPES) -> None:
        types = tuple(waterway_types)
        if not types:
            raise DataRequestError(
                "OSM waterway_types is empty, and an Overpass query with no waterway "
                "clause asks for nothing at all."
            )
        for waterway_type in types:
            if not isinstance(waterway_type, str) or not waterway_type.strip():
                raise DataRequestError(f"OSM waterway type {waterway_type!r} is empty.")
        self.waterway_types = types

    def download(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

        config = HydrographySourceConfig(source="osm", waterway_types=list(self.waterway_types))
        return fetch(config, bbox)

    def metadata(self) -> dict[str, Any]:
        return {"waterway_types": list(self.waterway_types)}


__all__ = [
    "DEFAULT_WATERWAY_TYPES",
    "OsmSource",
    "fetch",
]
