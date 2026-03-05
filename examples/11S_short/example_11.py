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

# ---- LIBRAIRIES

# PYTHON PACKAGES
import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path

try:
    import hydromodpy
except:
    pass

# ROOT DIRECTORY
from os.path import dirname, abspath
try:
    root_dir = dirname(dirname(dirname(abspath(__file__))))
except NameError:
    root_dir = os.getcwd()
sys.path.append(root_dir)

# HYDROMODPY MODEULES
from hydromodpy import watershed_root
from hydromodpy.geographic import Geographic, GeographicConfig
from hydromodpy.simulation.workspace import Workspace, WorkspaceConfig
# ---- FUNCTION LAUNCH

def run_hydromodpy(watershed_name='11S_short',
                   out_dir_path=os.path.join(root_dir,'examples','results'),
                   DEM_name='regional dem 2.tif',
                   X_coord=151181.608, # m
                   Y_coord=6858078.268, # m
                   catch_def='from_outlet_coord',
                   dem_correc_type='breach',
                   snap_dist=150, # m
                   buff_area=10, # %
                   proj_coord='EPSG:2154',
                   nlay=3, # -
                   lay_decay=1.25, # -
                   thick=50, # m
                   track_dir='backward',
                   sim_state='steady',
                   R=350, # mm/y
                   first_R='mean',
                   K=1e-5, # m/s
                   Sy=1, # %
                   Ss=1e-5 # -
                   ):

    # ---- PERSONAL PATHS
    
    # The folder out_path is created in the example_path root directory:

    print('The results of the example will be saved here :', out_dir_path)

    # ---- EXTRACT CATCHMENT
    
    config_init = WorkspaceConfig(
        catch_name=watershed_name,
        out_dir_path=Path(out_dir_path),
        data_path=Path(os.path.join(root_dir, "examples", "11S_short", "data")),
    )
    initializing_object = Workspace(config=config_init)
    
    specific_path = os.path.join(root_dir, "examples", "11S_short/")
    dem_path = os.path.join(specific_path, "data", DEM_name)

    geo_config = GeographicConfig(
        catch_def=catch_def,
        dem_init_path=Path(dem_path),
        x_outlet=X_coord,
        y_outlet=Y_coord,
        snap_dist=snap_dist,
        buff_area=buff_area,
        polyg_shp_path=None,
        dem_correc_type=dem_correc_type,
    )
    geographic_object = Geographic(
        config=geo_config,
        initializing=initializing_object,
    )
    
    # Name of the study site
    watershed_name = watershed_name
    print('##### '+watershed_name.upper()+' #####')

    # Extract the catchment from a regional DEM
    BV = watershed_root.Watershed(load=False,
                                  initializing_object=initializing_object,
                                  geographic_object=geographic_object,
                                  save_object=True
                                  )
    
    # Paths necessary for the script
    stable_folder = os.path.join(out_dir_path, watershed_name, 'results_stable')
    simulations_folder = os.path.join(out_dir_path, watershed_name, 'results_simulations')

    # ---- MODEL PARAMETRIZATION

    # Name of the model/simulation
    model_name = 'Model_Modflow_Test'

    # Import modules
    BV.add_settings()
    BV.add_climatic()
    BV.add_hydraulic()

    # Frame settings
    BV.settings.update_model_name(model_name) # Name of the model/simulation
    BV.settings.update_box_model(True)
    BV.settings.update_sink_fill(False)
    BV.settings.update_simulation_state(sim_state) # Transient
    BV.settings.update_check_model(check_grid=True)
    BV.settings.update_dis_perlen(dis_perlen=False)

    # Climatic settings
    BV.climatic.update_recharge(R / 1000 / 365, sim_state=BV.settings.sim_state)
    BV.climatic.update_first_clim(first_R) # or 'first or value

    # Hydraulic settings
    BV.hydraulic.update_nlay(nlay)
    BV.hydraulic.update_lay_decay(lay_decay) # 1 if not activated
    BV.hydraulic.update_bottom(None) # Set a value to set a flat bottom
    BV.hydraulic.update_thick(thick) # Not consider if bottom != of None
    BV.hydraulic.update_hk(K * 24 * 3600) # m/d
    BV.hydraulic.update_sy(Sy/100) # -
    BV.hydraulic.update_ss(Ss) # -
    BV.hydraulic.update_hk_decay(0, min_value=None, log_transf=False) # Exponential decay with depth : 1/10 (about half decrease at 10m)
    BV.hydraulic.update_sy_decay(0, min_value=None, log_transf=False)
    BV.hydraulic.update_ss_decay(0, min_value=None, log_transf=False)
    BV.hydraulic.update_hk_vertical(None) # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
    BV.hydraulic.update_cond_drain(None)

    # Boundary settings
    BV.settings.update_bc_sides(None, None)
    BV.add_oceanic('None')

    # Particle tracking settings
    BV.settings.update_input_particles(zone_partic = os.path.join(simulations_folder,model_name,'_postprocess/_rasters/seepage_areas_t(0).tif'),
                                       track_dir = track_dir,
                                       bore_depth = False,
                                       cell_div = 1, # 1
                                       )

    # ---- FLOW MODEL

    # Pre-processing
    model_modflow = BV.preprocessing_modflow(for_calib=False)

    # Processing
    success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

    # Post-processing
    if success_modflow == True:
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation=True,
                                  watertable_depth=True,
                                  seepage_areas=True,
                                  outflow_drain=True,
                                  groundwater_flux=True,
                                  groundwater_storage=True,
                                  accumulation_flux=True,
                                  persistency_index=False, # only in transient
                                  intermittency_monthly=False, # only in transient
                                  intermittency_weekly=False, # only in transient
                                  intermittency_daily=False, # only in transient
                                  export_all_tif=False)

    # ---- PARTICLE TRACKING

    # Pre-processing
    if success_modflow == True:
        model_modpath = BV.preprocessing_modpath(model_modflow)

    # Processing
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

    # Post-processing
    if success_modpath == True:
        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=False,
                                  particles_shp=False,
                                  random_id=None) # None

    # ---- POST PROCESSING

    timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                      model_modpath=model_modpath,
                                                      subbasin_results=True,
                                                      datetime_format=False)

    netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                              datetime_format=False)

    watertable_depth_output = timeseries_results.watertable_depth

    return watertable_depth_output

    # return None

# ---- RUN THE SCRIPT

if __name__ == '__main__':
    watertable_depth_output = run_hydromodpy()

# ---- NOTES

