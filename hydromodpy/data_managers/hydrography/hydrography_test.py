# Test des 3 méthodes d'extraction
       
import geopandas as gpd
import requests
import json
import gc
from shapely.geometry import LineString, box
import pandas as pd
from tqdm import tqdm
import xml.etree.ElementTree as ET
from typing import Literal, Optional

class Hydrography:
    
    def __init__(self, method: Literal['open-street-map', 'eu-hydro', 'bd-topage'], clip_shapefile: str):
        self.method = method
        self.clip_shapefile = clip_shapefile
        self.clip_shape = gpd.read_file(clip_shapefile)

    def download_and_clip(self, output_path: Optional[str] = None):
        if self.method == 'open-street-map':
            return self._osm_download_and_clip(output_path)
        elif self.method == 'eu-hydro':
            return self._euhydro_download_and_clip(output_path)
        elif self.method == 'bd-topage':
            return self._bdtopage_download_and_clip(output_path)
        else:
            raise ValueError(f"Méthode inconnue : {self.method}")

    def _osm_download_and_clip(self, output_path: Optional[str]):
        import osmnx as ox
        bbox = self.clip_shape.total_bounds
        minx, miny, maxx, maxy = bbox
        # Extraction des rivières et streams
        tags = {"waterway": ["river", "stream"]}
        rivers = ox.features_from_bbox(maxy, miny, maxx, minx, tags)
        if rivers.empty:
            print("No OSM waterway data found.")
            return None
        clipped = gpd.overlay(rivers, self.clip_shape, how='intersection')
        if output_path:
            clipped.to_file(output_path)
        return clipped

    def _euhydro_download_and_clip(self, output_path: Optional[str]):
        # EU-Hydro River Network Database (EEA Discomap) - ESRI REST
        BASE_URL = "https://image.discomap.eea.europa.eu/arcgis/rest/services/EUHydro/EUHydro_RiverNetworkDatabase/MapServer"
        GROUP_NAME = "River_Net_lines"
        PAGE_SIZE = 1000
        OUT_CRS = "EPSG:2154"
        OUT_LAYER = "river_net"
        bbox = self.clip_shape.total_bounds
        BBOX_WGS84 = (bbox[0], bbox[1], bbox[2], bbox[3])

        def mapserver_pjson():
            r = requests.get(BASE_URL, params={"f": "pjson"})
            r.raise_for_status()
            return r.json()

        def feature_layer_ids_in_group(ms, group_name):
            layers = ms.get("layers", [])
            group_ids = {ly["id"] for ly in layers if ly.get("type") == "Group Layer" and ly.get("name") == group_name}
            ids = []
            for ly in layers:
                if ly.get("type") != "Feature Layer":
                    continue
                if ly.get("parentLayerId") in group_ids:
                    ids.append(int(ly["id"]))
            if not ids:
                for ly in layers:
                    if ly.get("type") == "Feature Layer" and "Strahler" in (ly.get("name") or ""):
                        ids.append(int(ly["id"]))
            return sorted(set(ids))

        def layer_name(layer_id):
            r = requests.get(f"{BASE_URL}/{layer_id}", params={"f": "pjson"})
            r.raise_for_status()
            return r.json().get("name", str(layer_id))

        def query_page_geojson(layer_id, bbox_wgs84, offset, limit):
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
            r = requests.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(f"ArcGIS error for layer {layer_id}: {data['error']}")
            return data

        def fetch_bbox_geojson(layer_id, bbox_wgs84, page_size=1000, label=""):
            features = []
            offset = 0
            while True:
                data = query_page_geojson(layer_id, bbox_wgs84, offset, page_size)
                batch = data.get("features", [])
                features.extend(batch)
                got = len(batch)
                if got < page_size and not data.get("exceededTransferLimit", False):
                    break
                offset += page_size
                if offset > 2_000_000:
                    raise RuntimeError("Paging guard triggered (too many features).")
            if not features:
                return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
            return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")

        def clip_to_bbox(gdf, bbox_wgs84, out_crs="EPSG:2154"):
            lon_min, lat_min, lon_max, lat_max = bbox_wgs84
            aoi = gpd.GeoDataFrame(geometry=[box(lon_min, lat_min, lon_max, lat_max)], crs="EPSG:4326").to_crs(out_crs)
            gdf = gdf.to_crs(out_crs)
            clipped = gpd.clip(gdf, aoi)
            return clipped[clipped.geometry.notnull() & ~clipped.geometry.is_empty].copy()

        ms = mapserver_pjson()
        layer_ids = feature_layer_ids_in_group(ms, GROUP_NAME)
        if not layer_ids:
            print("No feature layers found for the requested group.")
            return None
        gdfs = []
        for lid in layer_ids:
            lname = layer_name(lid)
            gdf = fetch_bbox_geojson(lid, BBOX_WGS84, page_size=PAGE_SIZE, label=lname)
            if not gdf.empty:
                gdf["layer_id"] = lid
                gdf["layer_name"] = lname
                gdfs.append(gdf)
        if not gdfs:
            print("No features found.")
            return None
        rivers = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")
        rivers = clip_to_bbox(rivers, BBOX_WGS84, out_crs=OUT_CRS)
        if output_path:
            rivers.to_file(output_path, layer=OUT_LAYER, driver="GPKG")
        return rivers

    def _bdtopage_download_and_clip(self, output_path: Optional[str]):
        # Sandre / BD Topage (Metropole 2025) - WFS
        WFS_URL = "https://services.sandre.eaufrance.fr/geo/sandre"
        TYPENAME = "sa:CoursEau_FXX_Topage2025"
        OUT_GEOJSON = "application/json; subtype=geojson"
        OUT_CRS = "EPSG:2154"
        OUT_LAYER = "watercourses"
        bbox = self.clip_shape.total_bounds
        BBOX_WGS84 = (bbox[0], bbox[1], bbox[2], bbox[3])

        def bbox_crs84(bbox_wgs84):
            lon_min, lat_min, lon_max, lat_max = bbox_wgs84
            return f"{lon_min},{lat_min},{lon_max},{lat_max},urn:ogc:def:crs:OGC:1.3:CRS84"

        def wfs_hits(typename, bbox_wgs84):
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

        def fetch_bbox_geojson(typename, bbox_wgs84, page_size=2000):
            n = wfs_hits(typename, bbox_wgs84)
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
                if len(page) < page_size:
                    break
                start += page_size
            return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")

        def clip_to_bbox(gdf, bbox_wgs84, out_crs="EPSG:2154"):
            lon_min, lat_min, lon_max, lat_max = bbox_wgs84
            aoi = gpd.GeoDataFrame(geometry=[box(lon_min, lat_min, lon_max, lat_max)], crs="EPSG:4326").to_crs(out_crs)
            gdf = gdf.to_crs(out_crs)
            clipped = gpd.clip(gdf, aoi)
            return clipped[clipped.geometry.notnull() & ~clipped.geometry.is_empty].copy()

        gdf = fetch_bbox_geojson(TYPENAME, BBOX_WGS84, page_size=2000)
        if gdf.empty:
            print("No features found.")
            return None
        gdf = clip_to_bbox(gdf, BBOX_WGS84, out_crs=OUT_CRS)
        if output_path:
            gdf.to_file(output_path, layer=OUT_LAYER, driver="GPKG")
        return gdf


#%%

shp_path = "C:/Users/rabherve/GitHub/HMP_refact/examples/results/example13data/results_stable/geographic/watershed.shp"
out_dir = "C:/Users/rabherve/GitHub/HMP_refact/examples/results/example13data/results_stable/hydrography"

methods = [
    ("open-street-map", f"{out_dir}/osm_rivers.shp"),
    ("eu-hydro", f"{out_dir}/euhydro_rivernet.gpkg"),
    ("bd-topage", f"{out_dir}/bdtopage_watercourses.gpkg"),
]

for method, out_path in methods:
    print(f"\nMéthode : {method}")
    hydro = Hydrography(method, shp_path)
    try:
        result = hydro.download_and_clip(out_path)
        if result is not None:
            print(f"✅ Extraction réussie pour {method}, fichier sauvegardé : {out_path}")
        else:
            print(f"⚠️ Pas de données extraites pour {method}")
    except Exception as e:
        print(f"❌ Erreur pour {method} : {e}")