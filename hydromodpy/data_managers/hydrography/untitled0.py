# -*- coding: utf-8 -*-
"""
Created on Fri Feb 27 11:18:35 2026

@author: rabherve
"""

#%% OSM

import requests
import geopandas as gpd
import json
import gc
from shapely.geometry import LineString

def osm_waterway_download_optim2(mask_gdf, folder_outpath):
    """
    Efficiently download and process OSM waterway data for a given polygon mask.
    
    Parameters:
    - mask_gdf: GeoDataFrame of the area to extract waterways from (should be in EPSG:4326)
    - folder_outpath: Path to save the output shapefile
    
    Returns:
    - None (saves shapefiles)
    """
    
    # Ensure mask is in WGS84 (EPSG:4326)
    mask_gdf = mask_gdf.to_crs("EPSG:4326")

    # Get bounding box
    minx, miny, maxx, maxy = mask_gdf.total_bounds

    # Overpass API Query
    overpass_url = "https://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json];
    (
      way["waterway"="river"]({miny},{minx},{maxy},{maxx});
      way["waterway"="stream"]({miny},{minx},{maxy},{maxx});
      relation["waterway"="river"]({miny},{minx},{maxy},{maxx});
      relation["waterway"="stream"]({miny},{minx},{maxy},{maxx});
    );
    out geom;
    """

    try:
        response = requests.get(overpass_url, params={"data": overpass_query}, stream=True)
        response.raise_for_status()  # Raise error if response is bad
    except requests.RequestException as e:
        print(f"Error: Overpass API request failed - {e}")
        return None

    # Stream JSON response to avoid large memory usage
    try:
        data = json.loads(response.text)
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e}")
        return None
    finally:
        response.close()  # Ensure response is closed

    # Process JSON Data using a generator (reduces memory use)
    def extract_waterway_features(data):
        for element in data.get("elements", []):
            if "geometry" in element:
                coords = [(node["lon"], node["lat"]) for node in element["geometry"]]
                water_type = element["tags"].get("waterway", "")
                intermittent = 2 if element["tags"].get("intermittent", "no") == "yes" else 1

                if water_type in ["river", "stream"]:
                    yield {
                        "geometry": LineString(coords),
                        "id": element["id"],
                        "waterway": water_type,
                        "intermit": intermittent
                    }

    # Convert to GeoDataFrame using a generator
    gdf_rivers = gpd.GeoDataFrame(list(extract_waterway_features(data)),
                                  crs="EPSG:4326")

    if gdf_rivers.empty:
        print("⚠️ No waterway data found.")
        return None

    # Clip and transform coordinate system
    gdf_rivers = gdf_rivers.clip(mask_gdf).to_crs("EPSG:3035")

    # Save to file
    output_path = folder_outpath + "osm_rivers.shp"
    gdf_rivers.to_file(output_path)

    print(f"✅ Waterway data saved successfully")

    # Cleanup large objects
    del response, data, gdf_rivers
    gc.collect()

path_shp = 'C:/Users/rabherve/GitHub/HMP_refact/examples/results/11S_short/results_stable/geographic/watershed.shp'       
mask_gdf = gpd.read_file(path_shp)
folder_outpath = 'C:/Users/rabherve/Downloads/'
osm_waterway_download_optim2(mask_gdf, folder_outpath)

#%% BDTOPAGE

#!/usr/bin/env python3
# -- coding: utf-8 --

import xml.etree.ElementTree as ET

import geopandas as gpd
import requests
from shapely.geometry import box

# Sandre / BD Topage (Metropole 2025) - WFS
WFS_URL = "https://services.sandre.eaufrance.fr/geo/sandre"
TYPENAME = "sa:CoursEau_FXX_Topage2025"
OUT_GEOJSON = "application/json; subtype=geojson"

# Area of interest (WGS84, lon/lat)
BBOX_WGS84 = (-1.85, 47.95, -1.45, 48.25)

# Output
OUT_CRS = "EPSG:2154"  # Lambert-93
OUT_GPKG = "cours_eau_topage2025_bbox_clipped.gpkg"
OUT_LAYER = "watercourses"


def bbox_crs84(bbox_wgs84: tuple[float, float, float, float]) -> str:
    """CRS84 keeps axis order as lon,lat for WFS 2.0 bbox."""
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    return f"{lon_min},{lat_min},{lon_max},{lat_max},urn:ogc:def:crs:OGC:1.3:CRS84"


def wfs_hits(typename: str, bbox_wgs84: tuple[float, float, float, float]) -> int:
    """Fast count in bbox (resultType=hits)."""
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "resulttype": "hits",
        "bbox": bbox_crs84(bbox_wgs84),
    }
    r = requests.get(WFS_URL, params=params, timeout=120)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    return int(root.attrib.get("numberMatched", "0"))


def fetch_bbox_geojson(
    typename: str,
    bbox_wgs84: tuple[float, float, float, float],
    page_size: int = 2000,
) -> gpd.GeoDataFrame:
    """Download features intersecting bbox (server-side filter)."""
    n = wfs_hits(typename, bbox_wgs84)
    print(f"[WFS] matched features in bbox: {n}")
    if n == 0:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    features = []
    start = 0

    while True:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": typename,
            "outputFormat": OUT_GEOJSON,
            "bbox": bbox_crs84(bbox_wgs84),
            "count": page_size,
            "startIndex": start,
        }
        r = requests.get(WFS_URL, params=params, timeout=120)
        r.raise_for_status()

        data = r.json()
        page = data.get("features", [])
        features.extend(page)

        print(f"[WFS] page startIndex={start}: {len(page)} features")

        if len(page) < page_size:
            break
        start += page_size

    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def clip_to_bbox(
    gdf: gpd.GeoDataFrame,
    bbox_wgs84: tuple[float, float, float, float],
    out_crs: str = "EPSG:2154",
) -> gpd.GeoDataFrame:
    """Hard clip so geometries do not extend outside the bbox."""
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    aoi = gpd.GeoDataFrame(geometry=[box(lon_min, lat_min, lon_max, lat_max)], crs="EPSG:4326").to_crs(out_crs)
    gdf = gdf.to_crs(out_crs)
    clipped = gpd.clip(gdf, aoi)
    return clipped[clipped.geometry.notnull() & ~clipped.geometry.is_empty].copy()


# def main():
gdf = fetch_bbox_geojson(TYPENAME, BBOX_WGS84, page_size=2000)
if gdf.empty:
    print("No features found.")
    # return

gdf = clip_to_bbox(gdf, BBOX_WGS84, out_crs=OUT_CRS)
gdf.to_file(OUT_GPKG, layer=OUT_LAYER, driver="GPKG")

print(f"Saved: {OUT_GPKG} | {len(gdf)} features | CRS={gdf.crs}")


# if _name_ == "_main_":
#     main()

#%% EU-HYDRO

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import box
from tqdm import tqdm

# ============================================================
# EU-Hydro River Network Database (EEA Discomap) - ESRI REST
# ============================================================
BASE_URL = "https://image.discomap.eea.europa.eu/arcgis/rest/services/EUHydro/EUHydro_RiverNetworkDatabase/MapServer"
GROUP_NAME = "River_Net_lines"

# Area of interest (WGS84, lon/lat)
BBOX_WGS84 = (-5.0963971002187138, 44.5831879307599621, 4.6183608681344559, 48.8431028722756224)

# Download / paging
PAGE_SIZE = 1000   # server MaxRecordCount = 1000 (hard limit)
TIMEOUT = None     # no client-side timeout → wait as long as needed

# Output
OUT_CRS = "EPSG:2154"  # Lambert-93
OUT_GPKG = "euhydro_rivernet_bbox_clipped.gpkg"
OUT_LAYER = "river_net"


def mapserver_pjson() -> dict:
    r = requests.get(BASE_URL, params={"f": "pjson"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def feature_layer_ids_in_group(ms: dict, group_name: str) -> list[int]:
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


def layer_name(layer_id: int) -> str:
    r = requests.get(f"{BASE_URL}/{layer_id}", params={"f": "pjson"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("name", str(layer_id))


def query_page_geojson(
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
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()

    # If the server returns an ArcGIS error, make it explicit
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"ArcGIS error for layer {layer_id}: {data['error']}")

    return data


def fetch_bbox_geojson(
    layer_id: int,
    bbox_wgs84: tuple[float, float, float, float],
    page_size: int = 1000,
    label: str = "",
) -> gpd.GeoDataFrame:
    """Download features intersecting bbox (server-side filter) with pagination."""
    features = []
    offset = 0

    desc = label or f"layer {layer_id}"
    pbar = tqdm(
        unit=" feat", desc=f"  {desc}",
        dynamic_ncols=True, position=1, leave=False,
    )

    while True:
        data = query_page_geojson(layer_id, bbox_wgs84, offset, page_size)
        batch = data.get("features", [])
        features.extend(batch)

        got = len(batch)
        pbar.update(got)

        if got < page_size and not data.get("exceededTransferLimit", False):
            break

        offset += page_size
        if offset > 2_000_000:
            pbar.close()
            raise RuntimeError("Paging guard triggered (too many features).")

    pbar.close()

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def clip_to_bbox(
    gdf: gpd.GeoDataFrame,
    bbox_wgs84: tuple[float, float, float, float],
    out_crs: str = "EPSG:2154",
) -> gpd.GeoDataFrame:
    """Hard clip so geometries do not extend outside the bbox."""
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    aoi = gpd.GeoDataFrame(
        geometry=[box(lon_min, lat_min, lon_max, lat_max)],
        crs="EPSG:4326",
    ).to_crs(out_crs)

    gdf = gdf.to_crs(out_crs)
    clipped = gpd.clip(gdf, aoi)
    return clipped[clipped.geometry.notnull() & ~clipped.geometry.is_empty].copy()


def main():
    ms = mapserver_pjson()
    layer_ids = feature_layer_ids_in_group(ms, GROUP_NAME)
    print(f"[REST] feature layers under '{GROUP_NAME}': {layer_ids}")

    if not layer_ids:
        print("No feature layers found for the requested group.")
        return

    names = {lid: layer_name(lid) for lid in layer_ids}

    gdfs = []
    layer_bar = tqdm(layer_ids, desc="Layers", unit="layer", position=0)
    for lid in layer_bar:
        lname = names.get(lid, str(lid))
        layer_bar.set_postfix_str(lname)
        gdf = fetch_bbox_geojson(lid, BBOX_WGS84, page_size=PAGE_SIZE, label=lname)
        if not gdf.empty:
            gdf["layer_id"] = lid
            gdf["layer_name"] = lname
            gdfs.append(gdf)
    layer_bar.close()

    if not gdfs:
        print("No features found.")
        return

    rivers = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")

    rivers = clip_to_bbox(rivers, BBOX_WGS84, out_crs=OUT_CRS)
    rivers.to_file(OUT_GPKG, layer=OUT_LAYER, driver="GPKG")

    print(f"Saved: {OUT_GPKG} | {len(rivers)} features | CRS={rivers.crs}")


if __name__ == "__main__":
    main()