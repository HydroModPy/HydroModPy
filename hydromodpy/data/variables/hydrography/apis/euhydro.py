"""Fetch hydrography from the EU-Hydro River Network Database (EEA Discomap)."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import requests

from hydromodpy.core.logging import get_logger

from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

logger = get_logger(__name__)

BASE_URL = (
    "https://image.discomap.eea.europa.eu/arcgis/rest/services"
    "/EUHydro/EUHydro_RiverNetworkDatabase/MapServer"
)
_TIMEOUT = 300
_PAGING_GUARD = 2_000_000


def _mapserver_pjson() -> dict:
    r = requests.get(BASE_URL, params={"f": "pjson"}, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _feature_layer_ids_in_group(ms: dict, group_name: str) -> list[int]:
    layers = ms.get("layers", [])
    group_ids = {
        ly["id"]
        for ly in layers
        if ly.get("type") == "Group Layer" and ly.get("name") == group_name
    }
    ids: list[int] = []
    for ly in layers:
        if ly.get("type") != "Feature Layer":
            continue
        if ly.get("parentLayerId") in group_ids:
            ids.append(int(ly["id"]))
    # Fallback: any feature layer containing 'Strahler'
    if not ids:
        for ly in layers:
            if ly.get("type") == "Feature Layer" and "Strahler" in (ly.get("name") or ""):
                ids.append(int(ly["id"]))
    return sorted(set(ids))


def _layer_name(layer_id: int) -> str:
    r = requests.get(f"{BASE_URL}/{layer_id}", params={"f": "pjson"}, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("name", str(layer_id))


def _query_page_geojson(
    layer_id: int,
    bbox_wgs84: tuple[float, float, float, float],
    offset: int,
    limit: int,
) -> dict:
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    url = f"{BASE_URL}/{layer_id}/query"
    params = {
        "f": "geojson",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "resultOffset": offset,
        "resultRecordCount": limit,
        "orderByFields": "OBJECTID",
    }
    r = requests.get(url, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"ArcGIS error for layer {layer_id}: {data['error']}")
    return data


def _fetch_layer(
    layer_id: int,
    bbox_wgs84: tuple[float, float, float, float],
    page_size: int,
    label: str,
) -> gpd.GeoDataFrame:
    """Download features for a single layer with pagination."""
    features: list = []
    offset = 0

    while True:
        data = _query_page_geojson(layer_id, bbox_wgs84, offset, page_size)
        batch = data.get("features", [])
        features.extend(batch)
        got = len(batch)
        logger.debug("[EU-Hydro] %s offset=%d: %d features", label, offset, got)

        if got < page_size and not data.get("exceededTransferLimit", False):
            break
        offset += page_size
        if offset > _PAGING_GUARD:
            raise RuntimeError("Paging guard triggered (too many features).")

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def fetch(
    config: HydrographySourceConfig,
    bbox_wgs84: tuple[float, float, float, float],
) -> gpd.GeoDataFrame:
    """Download EU-Hydro features inside *bbox_wgs84*.

    Returns a GeoDataFrame in EPSG:4326.
    """
    group_name = config.group_name
    page_size = config.euhydro_page_size

    ms = _mapserver_pjson()
    layer_ids = _feature_layer_ids_in_group(ms, group_name)
    logger.info("[EU-Hydro] feature layers under '%s': %s", group_name, layer_ids)

    if not layer_ids:
        logger.warning("No EU-Hydro feature layers found for group '%s'.", group_name)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    names = {lid: _layer_name(lid) for lid in layer_ids}

    gdfs: list[gpd.GeoDataFrame] = []
    for lid in layer_ids:
        lname = names.get(lid, str(lid))
        gdf = _fetch_layer(lid, bbox_wgs84, page_size, label=lname)
        if not gdf.empty:
            gdf["layer_id"] = lid
            gdf["layer_name"] = lname
            gdfs.append(gdf)

    if not gdfs:
        logger.warning("No EU-Hydro features found in bbox %s", bbox_wgs84)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    combined = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")
    logger.info("[EU-Hydro] fetched %d features total", len(combined))
    return combined
