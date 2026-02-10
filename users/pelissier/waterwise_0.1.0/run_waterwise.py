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


# MODIF 
EXTERNAL_DIR = Path(r"D:/git/hydromodpy-waterwise")
sys.path.insert(0, str(EXTERNAL_DIR))
import src
import importlib
import numpy as np
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

from waterwise.config import Paths, ClimateWindow, RunOptions, CerraPaths
from waterwise.config import CerraParams
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

from cerra.climate_cerra import make_local_mask, make_local_cerra, make_pyhelp_inputs, make_local_csv


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

# PARAMS PATHS
    # Processing controle file
    # Here version which start everything from scratch
    SITES_XLSX = Path(r"D:/git/HydroModPy-WaterWise/users/pelissier/waterwise_0.1.0/data/Waterwise_sites_may2025_full_reset.xlsx")
    # Processing controle file - copy for test
    XLSX_OUT = Path(r"D:/git/HydroModPy-WaterWise/users/pelissier/waterwise_0.1.0/data/Waterwise_sites_may2025_updated.xlsx")

    # CFG - configuration - Grid and climate data paths
    CFG = Paths(
        data_root=Path(r"Z:/HDPY_database_forModelling"),
        out_root=Path(r"D:/git/HydroModPy-WaterWise/users/pelissier/waterwise_0.1.0/output"),
        climate_root=Path(r"Z:/HDPY_database_forModelling/_climate/_cerra/_pyHelpInput"),
        base_grid_csv=Path(r"D:/git/HydroModPy-WaterWise/users/pelissier/waterwise_0.1.0/data/input_grid_base.csv"),
    )

    CFG_CERRA = CerraPaths(
        forecast_root = Path(r'Z:/_waterwise_data_process/_climate/_cerra_forecast/'),  #_{variable}/{year}/{year}_alps.nc,
        land_root = Path(r'Z:/_waterwise_data_process/_climate/_cerra_land/'),          #_{variable}/{year}/{year}_alps.nc,
        local_root = Path(r'Z:/HDPY_database_forModelling/_climate/_cerra/_local/'),    #_{siteId}/{siteId}_{variable}.nc
        timeserie_root = Path(r'Z:/HDPY_database_forModelling/_climate/_cerra/_timeserie/'), 
        alps_grid = Path(r'Z:/_waterwise_data_process/_climate/_cerra_forecast/cerra_grid_alps.nc'),
    )

    # to complite with relevant values
    PARAMS_CERRA = CerraParams()

    RASTERS_DIR = Path(r"Z:/HDPY_database_forModelling/pyHELP_rasters")
    DEM_PATH = "Z:/HDPY_database_forModelling/_dem/gedtm30_alps_epsg3035.tif"  

    DATE_WINDOW = ClimateWindow("01/01/1985", "31/12/2024", "%d/%m/%Y")
    OPT = RunOptions(
            make_catchment = False,
            make_grid = False,
            make_climate_locale = False,
            make_climate_timeserie = False,
            make_climate_pyHelp = True,            
            make_climate = False,
            run_pyhelp =False,
            make_plots = False,
            save_png = True
        )

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

    # site by site processing
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
        # we keep out of the main code cerra europe to cerra alps for lisibility
        # code will be provided in a separate folder @TODO
        if OPT.make_climate_locale and int(df.at[i, "local_climate"]) == 0:
            logger.info(f'{sp.site_id} | create site mask')
            site_mask = make_local_mask( workdir = sp.site_root, 
                alps_grid_file = CFG_CERRA.alps_grid,  
                buffer = PARAMS_CERRA.local_buffer,
                reset = True, 
                site_epsg = PARAMS_CERRA.site_shape_epsg,
                checkplot = False, verbose= False,
                logger = logger)

            if isinstance(site_mask,np.ndarray):
                logger.info(f'{sp.site_id} | create local cerra')
                local_files = make_local_cerra(
                    mask = site_mask,
                    site_id = sp.site_id,
                    local_dir = CFG_CERRA.local_root,
                    alps_forecast_dir = CFG_CERRA.forecast_root,
                    alps_land_dir = CFG_CERRA.land_root,
                    years = PARAMS_CERRA.date_window,
                    logger = logger,
                    reset = True,
                    variables = {
                        '2m_temperature': 'forecast',
                        'surface_solar_radiation_downwards': 'forecast',
                        'total_precipitation' : 'land',                        
                    })                
            else:
                logger.info('ERROR | fail to create mask')
                local_files = []

        if OPT.make_climate_timeserie and int(df.at[i, "local_climate"]) == 0:
                make_local_csv(
                            site_id = sp.site_id,
                            local_dir = CFG_CERRA.local_root,
                            variables = ['2m_temperature','surface_solar_radiation_downwards','total_precipitation'],
                            logger = logger,
                            checkplot = True,
                            # shape = sp.site_root / f'results_stable/geographic/box_buff.shp',
                            timeserie_dir = CFG_CERRA.timeserie_root
                            )
            
        if OPT.make_climate_pyHelp and int(df.at[i, "local_climate"]) == 0:
            logger.info(f'{sp.site_id} | make pyhelp inputs') 
            # pyHelp input grid - 2 options:
            # 1 - create new pyHelp Grid for the area.
            # 2 - load a existing pyHelp grid for the area.
            make_pyhelp_inputs(
                site_id = sp.site_id,
                grid_file = sp.results_pyhelp / 'input_grid.csv',
                local_dir = CFG_CERRA.local_root,
                pyhelp_dir = CFG.climate_root,
                params = PARAMS_CERRA,
                logger = logger,
                variables = ['2m_temperature','surface_solar_radiation_downwards', 'total_precipitation'],                
                verbose = False,
                checkplot = True,
                newGrid = False
                )
#%%
        if OPT.make_climate and int(df.at[i, "local_climate"]) == 0:
            logger.info('step1')
            climate_map = copy_climate_from_cerra(site_id, CFG.climate_root, sp.results_pyhelp, logger)
            logger.info('step1')
            preprocess_climate_inputs(climate_map, sp.results_pyhelp, 
                                    decimals=1, date_window=DATE_WINDOW, logger=logger)

            pop.plot_climate_boxplots(workdir=str(sp.results_pyhelp), save_dir=str(sp.results_pyhelp / "boxplots_climate"))
            pop.plot_climate_mean_maps(workdir=str(sp.results_pyhelp), save_dir=str(sp.results_pyhelp / "climate_mean_map"))
            pop.plot_climate_timeseries_batch(workdir=str(sp.results_pyhelp), save_dir=str(sp.results_pyhelp / "climate_timeseries"))

            df.at[i, "local_climate"] = 1


        ############PYHELP + PLOTS
        if OPT.run_pyhelp and int(df.at[i, "Pyhelp"]) == 0:
            # climate_map_backup = {
            #     'precip_input' : sp.results_pyhelp / "precip_input_data_backup.csv",
            #     'airtemp_input': sp.results_pyhelp / "airtemp_input_data_backup.csv",
            #     'solrad_input' : sp.results_pyhelp / "solrad_input_data_backup.csv"
            # }
            # from waterwise.pipelines.help_example_WW import WorkflowFiles
            # files = WorkflowFiles.from_workdir(sp.results_pyhelp)

            # print(files.climate_backup)
            # print(files.climate_input)

            (sp.results_pyhelp / "plots_pyhelp").mkdir(parents=True, exist_ok=True)
            ret, diag = run_pyhelp_simulation(run_pyhelp, sp.results_pyhelp, logger) #,climate_map = climate_map_backup)
            
            diag_line(str(CFG.out_root), "pyhelp.ok", diag)
            if ret == 0:
                df.at[i, "Pyhelp"] = 1
                if OPT.make_plots:
                    run_pyhelp_plots(pop, sp.results_pyhelp, site_id, logger)

    # df.to_excel(XLSX_OUT, index=False)
    # global_logger.info(f"[done] wrote {XLSX_OUT}")

# %%
