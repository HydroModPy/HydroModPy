# -*- coding: utf-8 -*-
"""
Created on Thu Feb 19 10:26:19 2026

@author: pelissierm
"""
import os
from pathlib import Path

import pandas as pd
from pyproj import Transformer

import rasterio
from rasterio.mask import mask
from shapely.geometry import box

from hydromodpy import watershed_root
from hydromodpy.watershed import climatic, driasclimat, driaseau, geographic, geology, hydraulic, \
                          hydrography, hydrometry, intermittency, oceanic, \
                          piezometry, safransurfex, subbasin
from hydromodpy.modeling import downslope, modflow, modpath, timeseries
from hydromodpy.display import visualization_watershed, visualization_results, export_vtuvtk
from hydromodpy.tools import toolbox

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large"""

from waterwise.waterwise_tools.geol_glim import process_geology_with_glim
from waterwise.waterwise_tools.elevation import plot_dem_hillshade_stream
from waterwise.waterwise_tools.open_street_map import open_street_map
from waterwise.waterwise_tools.google_satellite_map import google_satellite_map

def clip_raster_to_square(raster_path, output_path, center_coords, side_length):
    x_center, y_center = center_coords
    half_side = side_length / 2

    square = box(
        x_center - half_side,
        y_center - half_side,
        x_center + half_side,
        y_center + half_side
    )

    with rasterio.open(raster_path) as src:
        out_image, out_transform = mask(src, [square.__geo_interface__], crop=True)
        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform
        })
        with rasterio.open(output_path, "w", **out_meta) as dest:
            dest.write(out_image)


def convert_coordinates_inplace(df: pd.DataFrame):
    t = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    for i in df.index:
        if pd.isna(df.at[i, "x_LAEA"]) or pd.isna(df.at[i, "y_LAEA"]):
            lon = df.at[i, "longitude"]
            lat = df.at[i, "latitude"]
            if pd.notna(lon) and pd.notna(lat):
                x, y = t.transform(float(lon), float(lat))
                df.at[i, "x_LAEA"] = x
                df.at[i, "y_LAEA"] = y
                
                
def _csv_flag(row: pd.Series, col: str, default: int = 0) -> int:
    val = row.get(col, default)
    if pd.isna(val):
        return default
    return int(float(val))
                
                
def run_catchment(cfg, row, dem_path, out_path, sites, site_num):

    id_name = str(row["ID_name"])
    watershed_name = str(row.get("Name", id_name))
    x = float(row["x_LAEA"])
    y = float(row["y_LAEA"])
    shp_upload = _csv_flag(row, "shp_upload", 0)

    print("##########################################")
    print("##### Working on " + watershed_name.upper() + " #####")

    clipped_dem_fp = os.path.join(str(cfg.data_root), "_sites", id_name)
    os.makedirs(clipped_dem_fp, exist_ok=True)
    clipped_dem_path = os.path.join(clipped_dem_fp, f"{id_name}_clipped_dem.tif")

    clip_raster_to_square(dem_path, clipped_dem_path, (x, y), 100000)

    if shp_upload == 1:
        shp_path = Path(str(cfg.data_root), "_sites", id_name, f"watershed{id_name}.shp")

        if not os.path.exists(shp_path):
            raise FileNotFoundError(f"{id_name}: shapefile not found: {shp_path}")

        print("Using shapefile for catchment")

        BV = watershed_root.Watershed(
            dem_path=clipped_dem_path,
            out_path=out_path,
            load=False,
            watershed_name=id_name,
            from_lib=None,
            from_dem=None,
            from_shp=[shp_path,50, "EPSG:3035"],
            from_xyv=None,
            bottom_path=None,
            save_object=True
        )

    else:
        from_xyv = [x, y, 150, 50, "EPSG:3035"]

        BV = watershed_root.Watershed(
            dem_path=clipped_dem_path,
            out_path=out_path,
            load=False,
            watershed_name=id_name,
            from_lib=None,
            from_dem=None,
            from_shp=None,
            from_xyv=from_xyv,
            bottom_path=None,
            save_object=True
        )

    stable_folder = os.path.join(out_path, id_name, "results_stable")
    os.makedirs(os.path.join(stable_folder, "_figures"), exist_ok=True)
    os.makedirs(os.path.join(stable_folder, "geology"), exist_ok=True)

    data_path = str(cfg.data_root)

    try:
        plot_dem_hillshade_stream(data_path, stable_folder, clipped_dem_path, id_name, watershed_name)
        open_street_map(stable_folder, id_name, watershed_name)
        google_satellite_map(data_path, stable_folder, id_name, watershed_name)
    except Exception as e:
        print(f"Could not run map plots for {id_name}: {e}")

    geol_path = os.path.join(data_path, "_geology")

    try:
        BV.add_geology(geol_path, types_obs="GLiM_clip_EU.shp", fields_obs="xx")
    except Exception as e:
        print(f"Could not add the geology for {id_name}: {e}")

    try:
        sites = process_geology_with_glim(
            data_path, stable_folder, clipped_dem_path, id_name, sites, site_num, watershed_name
        )
    except Exception as e:
        print(f"Could not process geology with GLiM for {id_name}: {e}")

    print("Area: " + str(BV.geographic.area.round(2)) + "km^2")
    print("Slope: " + str(BV.geographic.slope.round(2)))

    try:
        visualization_watershed.watershed_local(clipped_dem_path, BV)
        visualization_watershed.watershed_dem(BV)
    except Exception as e:
        print(f"Could not run the visualization_watershed for {id_name}: {e}")

    clipper = Path(out_path) / id_name / "results_stable" / "geographic" / "box_buff.shp"
    if clipper.exists():
        return clipper
    return None