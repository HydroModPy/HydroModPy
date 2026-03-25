"""Fetch hydrography from OpenStreetMap via Overpass API."""

from __future__ import annotations

import json

import geopandas as gpd
import requests
from shapely.geometry import LineString

from hydromodpy.core.tools import get_logger

from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

logger = get_logger(__name__)


def fetch(config: HydrographySourceConfig, bbox_wgs84: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Download OSM waterways inside *bbox_wgs84* ``(lon_min, lat_min, lon_max, lat_max)``.

    Returns a GeoDataFrame in EPSG:4326.
    """
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

    response = requests.get(overpass_url, params={"data": overpass_query}, stream=True, timeout=300)
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
        features.append({
            "geometry": LineString(coords),
            "id": element["id"],
            "waterway": water_type,
            "intermit": intermittent,
        })

    if not features:
        logger.warning("No OSM waterway data found in bbox %s", bbox_wgs84)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
    logger.info("OSM: fetched %d waterway features", len(gdf))
    return gdf
