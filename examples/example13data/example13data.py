# -*- coding: utf-8 -*-
"""
Created on Fri Mar 21 10:39:38 2025

@author: Ronan
"""

#%% ---- LIBRAIRIES

# Libraries installed by default
import sys
import os
import tomllib
from pathlib import Path

from flopy import run_model
import numpy as np
import pandas as pd
import geopandas as gpd
import glob
import pickle
import matplotlib.dates as mdates
import rasterio
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from itertools import islice
from mpl_toolkits.axes_grid1 import make_axes_locatable
import xarray as xr
import rioxarray as rxr
import pickle

import imageio.v2 as imageio
import whitebox

# Add
import flopy.utils.binaryfile as bf
from PIL import Image

# ROOT DIRECTORY
from os.path import dirname, abspath
# try:
root_dir = dirname(dirname(dirname(abspath(__file__))))
# except NameError:
#     root_dir = os.getcwd()
sys.path.append(root_dir)

# HYDROMODPY MODULES
import hydromodpy as hmp
from hydromodpy import watershed_root
from hydromodpy.watershed import Geographic, Initializing, Climatic, \
    Driasclimat, Driaseau, Hydrometry, \
    Hydraulic, Hydrography, Intermittency, Piezometry, Settings, \
    SafranSurfex, Subbasin, Transport
from hydromodpy.data_managers.hydrometry.station_set import StationSet
from hydromodpy.data_managers.oceanic import Oceanic
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.display import visualization_watershed, visualization_results, export_vtuvtk
from hydromodpy.tools import toolbox
from hydromodpy.domain import Domain, Surfaces
from hydromodpy.process import Flow
from hydromodpy.solver.modflow_nwt import Modflow, Modpath, Mt3dms
from hydromodpy.modeling import timeseries, netcdf
from hydromodpy.calibration.calibration_legacy.matching_stream import MatchingStreams
from hydromodpy.pyhelp.pyhelp_netcdf import preprocessing_pyhelp
fontprop = toolbox.plot_params(8,15,18,20)  # small, medium, interm, large

config_path = Path(__file__).parent / "config.toml"
cfg = HydroModPyConfig.from_toml(config_path)
out_path = cfg.initializing.out_dir_path

with config_path.open('rb') as f:
    raw_toml = tomllib.load(f)

#%% ---- CATCHMENT

#%% INITIALIZING

# Test overrides via env vars
if os.environ.get("HYDROMODPY_OUT_PATH"):
    out_path = Path(os.environ["HYDROMODPY_OUT_PATH"])
display_plots = os.environ.get("HYDROMODPY_NO_DISPLAY") != "1"
display_3D = display_plots

wbt = whitebox.WhiteboxTools()
wbt.verbose = False

cfg.initializing.out_dir_path = out_path
watershed_name = cfg.initializing.catch_name
print('##### '+watershed_name.upper()+' #####')

data_path = cfg.initializing.data_path

initializing = hmp.Initializing(config=cfg.initializing)

stable_folder      = cfg.initializing.stable_folder
simulations_folder = cfg.initializing.simulations_folder
calibration_folder = initializing.calibration_folder # necessary for plots

#%% GEOGRAPHIC

geographic   = hmp.Geographic(config=cfg.geographic,
                          initializing=initializing)

#%% DOMAIN SURFACE

domain = Domain(config=cfg.domain,geographic=geographic)

thickness = 50
surfaces_object = Surfaces(aquifer_top = geographic.dem_box_buff_data,
                           aquifer_bottom = geographic.dem_box_buff_data - thickness)
aquifer_top = surfaces_object.aquifer_top
aquifer_bottom = surfaces_object.aquifer_bottom

#%% ---- DATA

#%% CLIMATIC 

climatic = Climatic(out_path=initializing.catch_folder)

#%% CLIMATIC : SIM2 ATMOSPHERE (SAFRAN)

# Necessary to set model parameters

# climatic.update_sim2_reanalysis(var_list=['t', 'precip', 'dli'],
#                                        nc_data_path=Path(initializing.catch_folder) / 'results_stable' / 'climatic',
#                                        first_year=2003,
#                                        last_year=2003,
#                                        time_step='ME',
#                                        sim_state='transient',
#                                        spatial_mean=True,
#                                        geographic=geographic,
#                                        disk_clip=geographic.watershed_shp) # for clipping the netcdf files saved on disk
#                                                                 # can be a shapefile path or a flag: 'watershed' or False

#%% CLIMATIC : SIM2 LAND SURFACE (ISBA)

# climatic.update_sim2_reanalysis(var_list=['runoff', 'recharge'],
#                                        nc_data_path=Path(initializing.catch_folder) / 'results_stable' / 'climatic',
#                                        first_year=2003,
#                                        last_year=2003,
#                                        time_step='ME',
#                                        sim_state='transient',
#                                        spatial_mean=True,
#                                        geographic=geographic,
#                                        disk_clip=geographic.watershed_shp) # for clipping the netcdf files saved on disk
#                                                                 # can be a shapefile path or a flag: 'watershed' or False

# # # # Units
# climatic.t = climatic.t / 1000 # from mm to m
# climatic.precip = climatic.precip / 1000 # from mm to m
# climatic.etp = climatic.etp / 1000 # from mm to m
# climatic.runoff = climatic.runoff / 1000 # from mm to m
# climatic.recharge = climatic.recharge / 1000 # from mm to m

# R_mm_day = climatic.recharge
# r_mm_day = climatic.runoff

#%% CLIMATIC : IMPORT LAND SURFACE (ISBA)

climatic.update_recharge_reanalysis(path_file=data_path / '_climate_REANALYSIS.csv',
                                    clim_mod='REA',
                                    clim_sce='historic',
                                    first_year=2003,
                                    last_year=2003,
                                    time_step='ME',
                                    sim_state='transient')

climatic.update_runoff_reanalysis(path_file=data_path / '_climate_REANALYSIS.csv',
                                    clim_mod='REA',
                                    clim_sce='historic',
                                    first_year=2003,
                                    last_year=2003,
                                    time_step='ME',
                                    sim_state='transient')

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

R_mm_day = climatic.recharge
r_mm_day = climatic.runoff

if display_plots:
    fig, axs = plt.subplots(2,1, figsize=(8,8), sharex=True)
    axs = axs.ravel()

    ax = axs[0]
    ax.plot(30*R_mm_day, label='Recharge', c='navy', lw=1)
    ax.fill_between(R_mm_day.index, 30*R_mm_day, (30*R_mm_day)+(30*r_mm_day), label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
    ax.set_ylabel('R [mm/month]')
    ax.legend(loc='upper right')
    ax.set_title('No log', fontsize=8)

    ax = axs[1]
    ax.plot(30*R_mm_day, label='Recharge', c='navy', lw=1)
    ax.fill_between(R_mm_day.index, 30*R_mm_day, (30*R_mm_day)+(30*r_mm_day), label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
    ax.set_yscale('log')
    ax.set_title('Log', fontsize=8)
    ax.set_ylabel('R [mm/month]')

    ax.set_xlabel('Date')

    # Save plot as PNG
    fig.tight_layout()

#%% GEOLOGY


#%% HYDROGRAPHY

area = int(round(geographic.catch_area))

hydrography = Hydrography(out_path=initializing.catch_folder,
                                               types_obs=['regional stream network'],
                                               fields_obs=['FID'],
                                               geographic=geographic,
                                               hydro_path=data_path,
                                               streams_file=None)

#%% SUBBASIN

subbasin = Subbasin(geographic=geographic,
                    hydrometry=None,
                    intermittency=None,
                    add_path=data_path,
                    out_path=initializing.catch_folder,
                    sub_snap_dist=1000)

#%% HYDROMETRY

hydrometry_old = Hydrometry(out_path=initializing.catch_folder,
                        hydrometry_path=data_path,
                        file_name='france hydrometric stations.shp',
                        geographic=geographic)

# Extract hydrometry configuration from raw_toml
hydro_section = raw_toml.get("hydrometry_stations", {})

hydro_cfg = {
    "hydrometry": {k: v for k, v in hydro_section.items() 
                if k not in ["source", "selection", "output"]},
    "source": hydro_section.get("source", {}),
    "selection": hydro_section.get("selection", {}),
    "output": hydro_section.get("output", {}),
}

# Inject watershed shapefile created by Geographic as mask for station selection
selection_mode = hydro_cfg["selection"].get("mode", "mask")
if selection_mode == "mask":
    hydro_cfg["selection"]["mask_path"] = geographic.watershed_shp
    print(f"Hydrometry: Loading stations from watershed mask: {geographic.watershed_shp}")

# Load stations with error handling
try:
    hydrometry = StationSet.from_config(hydro_cfg)
except ValueError as e:
    print(f"Warning: Hydrometry loading failed - {e}")
    print("Continuing without hydrometric stations...")
    hydrometry = None

#%% INTERMITTENCY

intermittency = Intermittency(out_path=initializing.catch_folder,
                              intermittency_path=data_path,
                              file_name='regional onde stations.shp',
                              geographic=geographic)

#%% OCEANIC

oceanic = Oceanic()
oceanic.extract_local_data(out_path=initializing.catch_folder,
                             geographic=geographic,
                             oceanic_path=data_path)
try:
    oceanic.download_SHOM_data(geographic=geographic,
                                start_date='2003-01-01',
                                end_date='2003-01-30')
    oceanic.update_MSL(oceanic.SHOM_data['value'].mean())
except Exception as _shom_exc:
    print(f"SHOM download failed ({_shom_exc}), using default MSL=0.0")
    oceanic.update_MSL(0.0)

#%% PIEZOMETRY

#%% LAND COVER

#%% WATER USE

#%% GEOCHEMISTRY



#%% ---- PLOTS

#%% VISUALIZATION

visualization_watershed.watershed_local(cfg.geographic.dem_init_path, initializing, geographic)
visualization_watershed.watershed_dem(initializing=initializing, geographic=geographic, hydrography=hydrography, piezometry=None,
                                      intermittency=intermittency,
                                      hydrometry=hydrometry)

#%% PLOT INTERACTIVE

# CLICK on the map to select a cross-section !
dem_data = imageio.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif')) # dem data
stream_data = imageio.imread(os.path.join(stable_folder,'hydrography','regional stream network.tif')) # river data
interactive = True
visu = visualization_results.Visualization(initializing,
                                           geographic,
                                           hydrography,
                                           )
visu.interactive_cross_section(dem_data,
                               interactive)

#%% ---- NOTES
