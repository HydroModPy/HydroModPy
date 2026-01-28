# run_waterwise.py
# -*- coding: utf-8 -*-

#%%Import packages   

import os
from pathlib import Path
import sys

import pandas as pd
from pyproj import Transformer

import rasterio
from rasterio.mask import mask
from shapely.geometry import box


EXTERNAL_DIR = Path(r"C:\Users\Pelissierm\Hydromodpy")
sys.path.insert(0, str(EXTERNAL_DIR))
import src
import importlib
importlib.reload(src)

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

from waterwise.config import Paths, ClimateWindow, RunOptions
from waterwise.logging_utils import setup_logger
from waterwise.io.paths import site_paths
from waterwise.io.pyhelp_diagnostics import diag_reset, diag_section, diag_line

import waterwise.plots.pyhelp_plots as pop
from waterwise.plots.parameters_plots import export_param_maps, plot_param_boxplots

import waterwise.pipelines.grid_preprocessing as pgp
from waterwise.pipelines.grid import GridRasters, run_grid_preprocessing
from waterwise.pipelines.climate import copy_climate_from_cerra, preprocess_climate_inputs
from waterwise.pipelines.pyhelp import run_pyhelp_simulation, run_pyhelp_plots
from waterwise.pipelines.help_example_WW import run_pyhelp
from waterwise.pipelines.climate import climate_stats

import logging
logging.raiseExceptions = False



#%%Helpers
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


def run_catchment(cfg, row, dem_path, out_path, sites, site_num):

    id_name = str(row["ID_name"])
    watershed_name = str(row.get("Name", id_name))
    x = float(row["x_LAEA"])
    y = float(row["y_LAEA"])
    shp_upload = str(row.get("shp_upload", "0"))

    print("##########################################")
    print("##### Working on " + watershed_name.upper() + " #####")

    clipped_dem_fp = os.path.join(str(cfg.data_root), "_sites", id_name)
    os.makedirs(clipped_dem_fp, exist_ok=True)
    clipped_dem_path = os.path.join(clipped_dem_fp, f"{id_name}_clipped_dem.tif")

    clip_raster_to_square(dem_path, clipped_dem_path, (x, y), 100000)

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

    if BV.geographic.area.round(2) <= 1 and shp_upload == "1":
        BV = watershed_root.Watershed(
            dem_path=clipped_dem_path,
            out_path=out_path,
            load=False,
            watershed_name=id_name,
            from_lib=None,
            from_dem=None,
            from_shp=["Y:/HDPY_database_forModelling/_sites/_zugs/watershed_zugs.shp", 50, "EPSG:3035"],
            from_xyv=None,
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
        print(f" Could not run map plots for {id_name}: {e}")
    
    geol_path = os.path.join(data_path, "_geology")
    
    try:
        BV.add_geology(geol_path, types_obs="GLiM_clip_EU.shp", fields_obs="xx")
    except Exception as e:
        print(f"Could not add the geology for {id_name}: {e}")
    
    try:
        sites = process_geology_with_glim(data_path, stable_folder, clipped_dem_path, id_name, sites, site_num, watershed_name)
    except Exception as e:
        print(f"Could not process geology with GLiM for {id_name}: {e}")

    simulations_folder = os.path.join(out_path, id_name, "results_simulations")

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

#%%MAIN

if __name__ == "__main__":

    # PARAMS
    SITES_XLSX = Path(r"C:\Users\Pelissierm\Waterwise_0.0.0\Waterwise_sites_may2025_test.xlsx")
    XLSX_OUT = Path(r"C:\Users\Pelissierm\Waterwise_0.0.0\Waterwise_sites_may2025_updated.xlsx")

    CFG = Paths(
        data_root=Path(r"Z:\HDPY_database_forModelling"),
        out_root=Path(r"C:\Users\Pelissierm\Waterwise\HDPY_models"),
        climate_root=Path(r"Z:\HDPY_database_forModelling\_climate\_cerra\_pyHelpInput"),
        base_grid_csv=Path(r"C:\Users\Pelissierm\Waterwise_0.0.0\data\PyHELP\Geomatics\test\input_grid_base.csv"),
    )

    RASTERS_DIR = Path(r"Z:\HDPY_database_forModelling\pyHELP_rasters")
    DEM_PATH = "Z:/HDPY_database_forModelling/_dem/gedtm30_alps_epsg3035.tif"  

    DATE_WINDOW = ClimateWindow("01/01/1993", "31/12/2020", "%d/%m/%Y")
    OPT = RunOptions(True, True, True, True, True, True)

    # log global
    CFG.out_root.mkdir(parents=True, exist_ok=True)
    global_logger = setup_logger("waterwise", log_file=CFG.out_root / "run_waterwise.log")

    df = pd.read_excel(SITES_XLSX)
    convert_coordinates_inplace(df)
    
    PYHELP_DIAG_DIR = str(CFG.out_root)
    diag_reset(PYHELP_DIAG_DIR)

    for c in ["catchment_bnd", "catchment_characteristics", "local_climate", "Pyhelp"]:
        if c not in df.columns:
            df[c] = 0

    for i in df.index:
        site_id = str(df.at[i, "ID_name"])
        sp = site_paths(CFG.out_root, site_id)
        sp.results_pyhelp.mkdir(parents=True, exist_ok=True)
        sp.clipped_rasters.mkdir(parents=True, exist_ok=True)

        logger = global_logger

        diag_section(str(CFG.out_root), site_id)
        
        diag_line(
            str(CFG.out_root),
            "shp.create",
            int(str(df.at[i, "shp_upload"]) == "1") if "shp_upload" in df.columns else 0
        )
  
        ############CATCHMENT
        if OPT.make_catchment and int(df.at[i, "catchment_bnd"]) == 0:
            clip_shp = run_catchment(CFG, df.loc[i], DEM_PATH, str(CFG.out_root), sites=df, site_num=i)
            df.at[i, "catchment_bnd"] = 1
        else:
            clip_shp = Path(CFG.out_root) / site_id / "results_stable" / "geographic" / "box_buff.shp"

        ############GRID 
        if OPT.make_grid and int(df.at[i, "catchment_characteristics"]) == 0:
            
            rasters = GridRasters(
                dem_250m=RASTERS_DIR / "dem_250m.tif",
                cn=RASTERS_DIR / "CN.tif",
                slope=RASTERS_DIR / "Slope.tif",
                soil_depth=RASTERS_DIR / "soil_depth.tif",
                hydroprops=RASTERS_DIR / "Hydroprops.tif",
                worldcover=RASTERS_DIR / "Cover.tif",
                rgi_shp=RASTERS_DIR / "rgi_clip.shp",
            )

            run_grid_preprocessing(
                pgp_module=pgp,
                in_grid=CFG.base_grid_csv,
                out_grid=sp.results_pyhelp / "input_grid.csv",
                rasters=rasters,
                clip_shp=clip_shp,
                out_raster_dir=sp.clipped_rasters,
                save_png=OPT.save_png,
                logger=logger,
            )
            
            #add in class
            watershed_shp = CFG.out_root / site_id / "results_stable" / "geographic" / "watershed.shp"         
            clipped_dem_path = os.path.join(str(CFG.data_root), "_sites", site_id, f"{site_id}_clipped_dem.tif")
            
            export_param_maps(
                out_dir=sp.clipped_rasters,
                clip_shp=clip_shp,
                watershed_shp=watershed_shp,
                dem_250m=rasters.dem_250m,          
                hillshade_dem=clipped_dem_path,     
                cn=rasters.cn,
                slope=rasters.slope,
                soil_depth=rasters.soil_depth,
                hydroprops=rasters.hydroprops,
                worldcover=rasters.worldcover,
            )

            base = sp.results_pyhelp / "input_grid.csv"
            
            plot_param_boxplots(
                csv_path=str(base),
                save_dir=str(sp.results_pyhelp / "boxplots_params"),
            )
            
            df.at[i, "catchment_characteristics"] = 1

        ############CLIMATE
        if OPT.make_climate and int(df.at[i, "local_climate"]) == 0:
            copy_climate_from_cerra(site_id, CFG.climate_root, sp.results_pyhelp, logger)
            preprocess_climate_inputs(sp.results_pyhelp, decimals=1, date_window=DATE_WINDOW, logger=logger)
             
            pop.plot_climate_boxplots(workdir=str(sp.results_pyhelp), save_dir=str(sp.results_pyhelp / "boxplots_climate"))
            pop.plot_climate_mean_maps(workdir=str(sp.results_pyhelp), save_dir=str(sp.results_pyhelp / "climate_mean_map"))
            pop.plot_climate_timeseries_batch(workdir=str(sp.results_pyhelp), save_dir=str(sp.results_pyhelp / "climate_timeseries"))

            df.at[i, "local_climate"] = 1

        ############PYHELP + PLOTS
        if OPT.run_pyhelp and int(df.at[i, "Pyhelp"]) == 0:
            (sp.results_pyhelp / "plots_pyhelp").mkdir(parents=True, exist_ok=True)
            ret, diag = run_pyhelp_simulation(run_pyhelp, sp.results_pyhelp, logger)
            diag_line(str(CFG.out_root), "pyhelp.ok", diag)
            if ret == 0:
                df.at[i, "Pyhelp"] = 1
                if OPT.make_plots:
                    run_pyhelp_plots(pop, sp.results_pyhelp, site_id, logger)

    df.to_excel(XLSX_OUT, index=False)
    global_logger.info(f"[done] wrote {XLSX_OUT}")
