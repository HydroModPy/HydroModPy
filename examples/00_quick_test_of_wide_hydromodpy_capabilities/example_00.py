# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% ---- LIBRAIRIES
import sys
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import rasterio
import geopandas as gpd

from os.path import dirname, abspath

try:
    root_dir = dirname(dirname(dirname(abspath(__file__))))
except NameError:
    root_dir = os.getcwd()
sys.path.append(root_dir)

from hydromodpy.display import visualization_watershed, visualization_results
from hydromodpy.modeling.modflow import Modflow
from hydromodpy.tools.io_utils import (
    setup_paths, load_raster, load_csv,
    load_simulation_results, make_timeseries_data, extract_watershed
)
from hydromodpy.tools.visualization import (
    create_watershed_plot, create_map_plot, create_crosssection_plot, create_timeseries_plot
)

#%% ---- PERSONAL PATHS

# Setup paths using generalized function
example_dir = "00_quick_test_of_wide_hydromodpy_capabilities"
paths = setup_paths(root_dir, example_dir, env_var_name="HYDROMODPY_EXAMPLE00_OUT_PATH")
data_path = paths['data']
out_path = paths['output']

# Skip plotting if environment variable is set
skip_plots = os.getenv("HYDROMODPY_EXAMPLE00_SKIP_PLOTS", "0").strip().lower() in {"1", "true", "yes"}

print('The results of the example will be saved here :', out_path)

#%% ---- EXTRACT CATCHMENT

# Name of the study site (determines results directory structure)
watershed_name = 'Example_00_Aber'
print('##### '+watershed_name.upper()+' #####')

# Regional DEM
dem_path = os.path.join(data_path, 'regional dem.tif')

# Outlet coordinates of the catchment
from_xyv = [150727.164, 6858066.520, 100, 10 , 'EPSG:2154']

# Extract watershed using generalized function
BV = extract_watershed(dem_path=dem_path,
                       out_path=out_path,
                       watershed_name=watershed_name,
                       from_xyv=from_xyv,
                       catch_def="xy",
                       bottom_path=None,
                       load=False,
                       save_object=True)

# Paths necessary for the script
# (Use watershed_name because it differs from example_dir in this case)
stable_folder = os.path.join(out_path, watershed_name, 'results_stable')
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

#%% ---- ADD DATA

# Clip specific data at the catchment scale
BV.add_hydrography(data_path, types_obs=['regional stream network'])

#%% ---- MODEL PARAMETRIZATION

# Name of the model/simulation
model_name = 'reg_0'

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()
BV.add_oceanic('None')

# Frame settings
BV.settings.update_model_name(model_name) # Name of the model/simulation
BV.settings.update_box_model(True)
BV.settings.update_sink_fill(False)
BV.settings.update_simulation_state('transient') # steady
BV.settings.update_check_model(plot_cross=True, check_grid=True)
BV.settings.update_dis_perlen(dis_perlen=True)

# Climatic settings
recharge = make_timeseries_data(start_date='2017-01-01',
                                end_date='2017-12-31',
                                freq='ME',
                                values=[10, 60, 40, 20, 10, 5, 4, 20, 10, 1, 0, 0],
                                name='recharge')
recharge = recharge / 1000 / 30  # recharge mm/month to in m/day
BV.climatic.update_recharge(recharge, sim_state=BV.settings.sim_state)
BV.climatic.update_runoff(None, sim_state=BV.settings.sim_state)
BV.climatic.update_first_clim('mean') # or 'first or value

# Well settings
well_1_coords = [1-1,9-1,29-1] # [lay, row, col]
well_2_coords = [1-1,17-1,29-1] # [lay, row, col]
well_1_fluxes = make_timeseries_data(start_date='2017-01-01',
                                     end_date='2017-12-31',
                                     freq='ME',
                                     values=[-200, 0, -100, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                                     name='well_1')
well_2_fluxes = make_timeseries_data(start_date='2017-01-01',
                                     end_date='2017-12-31',
                                     freq='ME',
                                     values=[-500, 0, 0, -500, 0, 0, -500, 0, 0, 0, 0, 0],
                                     name='well_2')
BV.settings.update_well_pumping(well_coords=[well_1_coords, well_2_coords],
                                well_fluxes=[well_1_fluxes, well_2_fluxes])

# Hydraulic settings
BV.hydraulic.update_bottom(None) # Set a value to set a flat bottom
BV.hydraulic.update_thick(50) # Not consider if bottom != of None
BV.hydraulic.update_nlay(1)
BV.hydraulic.update_lay_decay(1) # 1 if not activated
BV.hydraulic.update_hk(1e-5 * 24 * 3600) # m/d
BV.hydraulic.update_sy(1/100) # -
BV.hydraulic.update_ss(1e-5) # -
BV.hydraulic.update_hk_decay(0, None, False) # alpha, kmin, log_transf
BV.hydraulic.update_sy_decay(0, None, False)
BV.hydraulic.update_ss_decay(0, None, False)
BV.hydraulic.update_hk_vertical(None) # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
BV.hydraulic.update_sy_vertical(None) # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
BV.hydraulic.update_vka(1) # anisotropy ratio Kxy/Kz
BV.hydraulic.update_cond_drain(None)

# Boundary settings
BV.settings.update_bc_sides(None, None)

# Particle tracking settings
BV.settings.update_input_particles(zone_partic = os.path.join(simulations_folder,model_name,'_postprocess/_rasters/seepage_areas_t(0).tif'),
                                    cell_div = 1, # 1
                                    zloc_div = False,  # True or False, add cells in vertical
                                    bore_depth = None, # True or None, inject in each lay
                                    track_dir = 'backward',
                                    sel_random = None, # or int
                                    sel_slice = None, # or int
                                    )

#%% ---- GROUNDWATER FLOW MODEL RUN

# FLOW MODEL
for_calib = False
if for_calib == False:
    model_folder = BV.simulations_folder
else:
    model_folder = BV.calibration_folder

model_modflow = Modflow(BV.geographic,
                        # Workflow settings
                        model_folder=model_folder,
                        model_name=BV.settings.model_name,
                        bin_path=BV.bin_path,
                        # Model settings
                        box=BV.settings.box,
                        sink_fill=BV.settings.sink_fill,
                        sim_state=BV.settings.sim_state,
                        dis_perlen=BV.settings.dis_perlen,
                        # Well settings
                        well_coords=BV.settings.well_coords,
                        well_fluxes=BV.settings.well_fluxes,
                        # Output settings
                        plot_cross=BV.settings.plot_cross,
                        cross_ylim=BV.settings.cross_ylim,
                        check_grid=BV.settings.check_grid,
                        # Boundary settings
                        sea_level=BV.oceanic.MSL,
                        bc_left=BV.settings.bc_left,
                        bc_right=BV.settings.bc_right,
                        # Climatic settings
                        recharge=BV.climatic.recharge,
                        runoff=BV.climatic.runoff,
                        first_clim=BV.climatic.first_clim,
                        # Hydraulic settings
                        bottom=BV.hydraulic.bottom,
                        thick=BV.hydraulic.thick,
                        nlay=BV.hydraulic.nlay,
                        lay_decay=BV.hydraulic.lay_decay,
                        hk_value=BV.hydraulic.hk_value,
                        sy_value=BV.hydraulic.sy_value,
                        ss_value=BV.hydraulic.ss_value,
                        hk_decay=BV.hydraulic.hk_decay,
                        sy_decay=BV.hydraulic.sy_decay,
                        ss_decay=BV.hydraulic.ss_decay,
                        verti_hk=BV.hydraulic.verti_hk,
                        verti_sy=BV.hydraulic.verti_sy,
                        verti_ss=BV.hydraulic.verti_ss,
                        cond_drain=BV.hydraulic.cond_drain,
                        vka=BV.hydraulic.vka,
                        exdp=BV.hydraulic.exdp)

model_modflow.pre_processing()
success_modflow = model_modflow.processing(write_model=True, run_model=True, link_mt3dms=False)

if success_modflow == True:
    model_modflow.post_processing(model_modflow,
                                  watertable_elevation=True,
                                  watertable_depth=True,
                                  seepage_areas=True,
                                  outflow_drain=True,
                                  groundwater_flux=True,
                                  groundwater_storage=True,
                                  accumulation_flux=True,
                                  persistency_index=True, # only in transient
                                  intermittency_monthly=True, # only in transient
                                  intermittency_weekly=False, # only in transient
                                  intermittency_daily=False, # only in transient
                                  export_all_tif=True)

BV.postprocessing_netcdf(model_modflow,
                         datetime_format=False)

#%% ---- PARTICLE TRACKING RUN

# Pre-processing
model_modpath = BV.preprocessing_modpath(model_modflow)

# Processing
success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

# Post-processing
if success_modpath == True:
    BV.postprocessing_modpath(model_modpath,
                              ending_point=True,
                              starting_point=True,
                              pathlines_shp=True,
                              particles_shp=False,
                              random_id=None) # None

    BV.filtprocessing_modpath(model_modpath,
                              norm_flux=True, # for forward only
                              filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                              filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                              filt_inout=True, # delete particles in and out in the same cell (first layer)
                              calc_rtd=True, # compute residence time distribution
                              random_id=None, # select randomly to keep
                              ) # None

#%% ---- GENERATE TIMESERIES

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  datetime_format=False,
                                                  subbasin_results=True,
                                                  intermittency_monthly=True, # only in transient
                                                  intermittency_weekly=False, # only in transient
                                                  intermittency_daily=False, # only in transient
                                                  ) # or 'M' or None

if skip_plots:
    print("Skipping plotting sections (HYDROMODPY_EXAMPLE00_SKIP_PLOTS enabled).")
    sys.exit(0)

#%% ---- OPEN SIMULATED

# Load all simulation results at once
results = load_simulation_results(simulations_folder, model_name)

# Extract results from dictionary
sim_contour = gpd.read_file(BV.geographic.watershed_shp)
sim_dem_data = load_raster(BV.geographic.watershed_box_buff_dem)[0]
sim_wte_data = results['wte_data']
sim_wte_rio = results['wte_rio']
sim_wtd_data = results['wtd_data']
sim_wtd_rio = results['wtd_rio']
sim_seep_data = results['seep_data']
sim_seep_rio = results['seep_rio']
sim_pathlines = results['pathlines']
sim_timeseries = results['timeseries']

#%% ---- PLOT WATERSHED

create_watershed_plot(dem_path, BV, model_name, visualization_watershed, visualization_results)

#%% ---- PLOT MAPS

create_map_plot(sim_wtd_data, sim_wtd_rio, sim_seep_data, sim_seep_rio,
                sim_contour, sim_pathlines, title='SIMULATED: time 1/12')

#%% ---- PLOT CROSS-SECTION

create_crosssection_plot(sim_wte_data, sim_dem_data, title='SIMULATED: time 1/12')

#%% ---- PLOT GRAPHS

create_timeseries_plot(sim_timeseries, well_1_fluxes, well_2_fluxes,
                      title='SIMULATED: time 1/12')

#%% ---- NOTES

os.chdir(root_dir)
