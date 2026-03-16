"""Fetch hydrography from the Sandre BD Topage WFS service."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import geopandas as gpd
import requests

from hydromodpy.support.tools import get_logger

from hydromodpy.data_managers.variables.hydrography.config import HydrographySourceConfig

logger = get_logger(__name__)

WFS_URL = "https://services.sandre.eaufrance.fr/geo/sandre"
OUT_GEOJSON = "application/json; subtype=geojson"


def _bbox_crs84(bbox_wgs84: tuple[float, float, float, float]) -> str:
    """Format *bbox_wgs84* for WFS 2.0 CRS84 axis order (lon, lat)."""
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    return f"{lon_min},{lat_min},{lon_max},{lat_max},urn:ogc:def:crs:OGC:1.3:CRS84"


def _wfs_hits(typename: str, bbox_wgs84: tuple[float, float, float, float]) -> int:
    """Fast count of features in *bbox_wgs84* (resultType=hits)."""
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "resulttype": "hits",
        "bbox": _bbox_crs84(bbox_wgs84),
    }
    r = requests.get(WFS_URL, params=params, timeout=120)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    return int(root.attrib.get("numberMatched", "0"))


def fetch(
    config: HydrographySourceConfig,
    bbox_wgs84: tuple[float, float, float, float],
) -> gpd.GeoDataFrame:
    """Download BD Topage features inside *bbox_wgs84*.

    Returns a GeoDataFrame in EPSG:4326.
    """
    typename = config.typename
    page_size = config.page_size

    n = _wfs_hits(typename, bbox_wgs84)
    logger.info("[WFS] BD Topage matched features in bbox: %d", n)
    if n == 0:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    features: list = []
    start = 0

    while True:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": typename,
            "outputFormat": OUT_GEOJSON,
            "bbox": _bbox_crs84(bbox_wgs84),
            "count": page_size,
            "startIndex": start,
        }
        r = requests.get(WFS_URL, params=params, timeout=120)
        r.raise_for_status()

        data = r.json()
        page = data.get("features", [])
        features.extend(page)

        logger.debug("[WFS] page startIndex=%d: %d features", start, len(page))

        if len(page) < page_size:
            break
        start += page_size

    logger.info("[WFS] BD Topage: fetched %d features total", len(features))
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
