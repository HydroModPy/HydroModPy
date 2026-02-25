# -*- coding: utf-8 -*-
"""
Created on Fri Mar 21 10:39:38 2025

@author: Ronan
"""

#%% ---- LIBRAIRIES

# Libraries installed by default
import sys
import os
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
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

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
from hydromodpy import watershed_root
from hydromodpy.watershed import Geographic, Initializing, Climatic, Driasclimat, Driaseau, \
    Geology, Hydraulic, Hydrography, Hydrometry, Intermittency, Oceanic, Piezometry, Settings, \
    SafranSurfex, Subbasin, Transport
from hydromodpy.watershed import surfaces
from hydromodpy.config.hydromodpy_config import HydroModPyConfig, InitializingConfig, GeographicConfig
from hydromodpy.display import visualization_watershed, visualization_results, export_vtuvtk
from hydromodpy.tools import toolbox
from hydromodpy.modeling.modflow import Modflow
from hydromodpy.modeling.modpath import Modpath
from hydromodpy.modeling.mt3dms import Mt3dms
from hydromodpy.modeling import timeseries, netcdf
from hydromodpy.calibration_legacy.matching_stream import MatchingStreams

from hydromodpy.process import Flow
from hydromodpy.process import Parameter, Variable, InitialCondition, BoundaryCondition, SinkSource
from hydromodpy.pyhelp.pyhelp_netcdf import preprocessing_pyhelp

fontprop = toolbox.plot_params(8,15,18,20)  # small, medium, interm, large

cfg = HydroModPyConfig.from_toml(Path(__file__).parent / "config.toml")
out_path = cfg.initializing.out_dir_path

#%% ---- EXTRACT CATCHMENT

def run_example12(out_path=out_path, display_plots=True, display_3D=False):

    cfg.initializing.out_dir_path = out_path
    watershed_name = cfg.initializing.catch_name
    print('##### '+watershed_name.upper()+' #####')

    data_path = cfg.initializing.data_path

    initializing = Initializing(config=cfg.initializing)
    geographic   = Geographic(config=cfg.geographic,
                              initializing=initializing)
    
    flow = Flow()
    
    
    setting = Settings()
    hydraulic = Hydraulic(nrow=geographic.y_pixel,
                          ncol=geographic.x_pixel,
                          box_dem=geographic.watershed_box_buff_dem)


    transport = Transport()

    #%% DATA

    area = int(round(geographic.catch_area))

    hydrography = Hydrography(out_path=initializing.catch_folder,
                                                   types_obs=['botopage2024_naizin_streams_perennial-intermittent'],
                                                   fields_obs=['FID'],
                                                   geographic=geographic,
                                                   hydro_path=data_path,
                                                   streams_file=None)

    subbasin = Subbasin(geographic=geographic,
                        hydrometry=None,
                        intermittency=None,
                        add_path=data_path,
                        out_path=initializing.catch_folder,
                        sub_snap_dist=150)

    geology = Geology(out_path=initializing.catch_folder,
                            geographic=geographic,
                            geo_path = data_path,
                            landsea=None,
                            types_obs='GEO1M.shp',
                            fields_obs= 'CODE_LEG')

    hydrometry = Hydrometry(out_path=initializing.catch_folder,
                            hydrometry_path=data_path,
                            file_name='france hydrometric stations.shp',
                            geographic=geographic)

    intermittency = Intermittency(out_path=initializing.catch_folder,
                                  intermittency_path=data_path,
                                  file_name='regional onde stations.shp',
                                  geographic=geographic)

    #%% CLIMATIC

    climatic = Climatic(out_path=initializing.catch_folder)

    oceanic = Oceanic()
    oceanic.extract_local_data(out_path=initializing.catch_folder,
                                 geographic=geographic,
                                 oceanic_path=data_path)
    oceanic.download_SHOM_data(geographic=geographic,
                                start_date='2003-01-01',
                                end_date='2003-01-30')
    oceanic.update_MSL(oceanic.SHOM_data['value'].mean())

    
    #%% WATERSHED OBJECT

    stable_folder      = cfg.initializing.stable_folder
    simulations_folder = cfg.initializing.simulations_folder
    calibration_folder = initializing.calibration_folder # necessary for plots

    #%% SURFACE

    thickness = 50
    surfaces_object = surfaces.Surfaces(aquifer_top = geographic.dem_box_buff_data,
                                        aquifer_bottom = geographic.dem_box_buff_data - thickness)
    aquifer_top = surfaces_object.aquifer_top
    aquifer_bottom = surfaces_object.aquifer_bottom

    #%% VISUALIZATION

    visualization_watershed.watershed_local(cfg.geographic.dem_init_path, initializing, geographic)
    visualization_watershed.watershed_dem(initializing=initializing, geographic=geographic, hydrography=hydrography, piezometry=None, intermittency=intermittency, hydrometry=hydrometry)

    # Add hydrological data
    
    #%% ---- ATMOSPHERE
    
    # Necessary to set model parameters

    climatic.update_sim2_reanalysis(var_list=['t', 'precip', 'dli'],
                                           nc_data_path=Path(initializing.catch_folder) / 'results_stable' / 'climatic',
                                           first_year=2003,
                                           last_year=2003,
                                           time_step='ME',
                                           sim_state='transient',
                                           spatial_mean=True,
                                           geographic=geographic,
                                           disk_clip=geographic.watershed_shp) # for clipping the netcdf files saved on disk
                                                                    # can be a shapefile path or a flag: 'watershed' or False
    
    #%% ---- PYHELP
    
    pyhelp_activated = False
    if pyhelp_activated == True:
    
        #%% INIT
    
        print("test")
    
        pyhelp_workdir = Path(cfg.initializing.out_dir_path) / watershed_name / "results_pyhelp"
        pyhelp_workdir.mkdir(parents=True, exist_ok=True)
    
        sim2_file_precip = 'x' # ton netcdf propre, mettre celui de poschqivo dqns "data"
        sim2_file_temp = 'x' # ton netcdf propre
        sim2_file_sr = 'x' # ton netcdf propre
        
        # Peut-être ajouter à config.toml 
        
        dem_path_modflow = geographic.watershed_box_buff_dem # pqth du dem modflow
        dem_path_pyhelp = os.path.join(initializing.stable_folder, "geographic", "watershed_box_buff_dem_250.tif")
    
        wbt.resample(dem_path_modflow, dem_path_pyhelp, 250)
        shapefile_path = geographic.watershed_shp
    
        # Ready climatic CSVs
        # ready_csvs = [
        #     os.path.join(era5_folder, "precip_input_data.csv"),
        #     os.path.join(era5_folder, "airtemp_input_data.csv"),
        #     os.path.join(era5_folder, "solrad_input_data.csv")
        # ]
    
        #### If already completed grid:
        grid_base_csv = Path(data_path, "_init_input_grid_base1", "input_grid_base1.csv")
        
        #%% PATH
    
        pyhelp_workdir = os.path.join(out_path, watershed_name, "results_pyhelp")
        era5_folder = os.path.join(data_path)
    
        ### If already completed grid:
        grid_base_csv = data_path+"/"+"_init_input_grid_base1/"+"input_grid_base1.csv"
    
        ready_csvs = [
            os.path.join(era5_folder, "precip_input_data.csv"),
            os.path.join(era5_folder, "airtemp_input_data.csv"),
            os.path.join(era5_folder, "solrad_input_data.csv")
        ]
    
        #%% RUN
    
        option = '3'
        
        grid_kwargs = dict(
                           growth_start=140,
                           growth_end=280,
                           wind=2.5,
                           hum1=60, hum2=65, hum3=70, hum4=70,
                           LAI=2.4,
                           EZD=44.5,
                           CN=55,
                           nlayer=1,
                           lay_type1=1,
                           thick1=100,
                           poro1=0.45,
                           fc1=0.23,
                           wp1=0.116,
                           ksat1=0.1,
                           dist_dr1=50,
                           slope1=35
                           )
    
        # cid                             Unique cell ID
        # lat_dd                          Decimal degrees Latitude of the cell centroid
        # lon_dd                          Decimal degrees Longitude of the cell centroid
    
        # wind            km/h            Average annual wind speed
        # hum1            %               Average quarterly relative humidity (Jan to Mar)
        # hum2            %               Average quarterly relative humidity (Apr to Jun)
        # hum3            %               Average quarterly relative humidity (Jul to Sep)
        # hum4            %               Average quarterly relative humidity (Oct to Dec)
        # growth_start    julian day      First day of the growing season
        # growth_end      julian day      Last day of the growing season
        # LAI             –               Maximum leaf area index
        # EZD             cm              Evaporative zone depth
        # CN              –               Curve Number
        # nlayer          –               Number of hydrostratigraphic layers at cell cid
        # lay_type{i}     –               Type of HELP layer of the ith soil layer
        # thick{i}        cm              Thickness of the ith soil layer
        # poro{i}         m3/m3           Total porosity of the ith soil layer
        # fc{i}           m3/m3           Field capacity of the ith soil layer
        # wp{i}           m3/m3           Wilting point of the ith soil layer
        # ksat            cm/s            Saturated hydraulic conductivity of the ith soil layer
        # dist_dr         m               Distance to discharge
        # slope           %               Average slope
    
        # run             –               Identify cells to be run with the HELP model
        # context         –               Identify cells by context:
        #     0 - Water cell
        #     1 - Normal cell
        #     2 - Stream edge with superficial hypodermic runoff
        #     3 - River edge with deep hypodermic runoff
        #     4 - Urban cell
        #     5 - Cell not mapped
    
        sim_name = "_sim_"
        sim_dir = pyhelp_workdir / sim_name
        sim_dir.mkdir(parents=True, exist_ok=True)
    
        # if option == '1':
    
        #     #---- Input climatic ready - Input grid updated:
        #     nc = preprocessing_pyhelp(
        #         workdir = os.path.join(pyhelp_workdir, f"_sim_{k}"),
        #         outpath = os.path.join(pyhelp_workdir, f"_sim_{k}"),
        #         ready_csvs = ready_csvs,
        #         grid_kwargs = grid_kwargs,
        #         dem = dem_path_pyhelp,
        #         shapefile = from_shp[0],
        #     )
        #     # print("NetCDF :", nc)
    
        # if option == '2':
    
        #     #---- Input climatic ready - Input grid ready:
    
        #     nc = preprocessing_pyhelp(
        #         workdir = pyhelp_workdir,
        #         outpath = simulations_folder,
        #         grid_csv = grid_base_csv,
        #         ready_csvs = ready_csvs,
        #     )
        #     # print("NetCDF :", nc)
      
        if option == '3':
    
            #---- Input climatic updated - Input grid updated:
            nc = preprocessing_pyhelp(
                workdir = pyhelp_workdir,
                outpath = simulations_folder,
                dem = dem_path_pyhelp,
                era5_folder = era5_folder,
                grid_kwargs = grid_kwargs,
                conda_env   = "pyhelp_env",
            )
            # print("NetCDF :", nc)
    
        #%% FORMATING
    
        name_sim = sim_name
    
        csv_path = pyhelp_workdir + '/' + name_sim + "/help_example_daily_mean.csv"
    
        df = pd.read_csv(csv_path)
        df = df.rename(columns={df.columns[0]: "time"})
        formatted_csv_path =  pyhelp_workdir + '/' + name_sim + "/help_example_daily_mean_formatted.csv"
        df.to_csv(formatted_csv_path, index=False)
    
        #%% SCALING
    
        nc_path  = pyhelp_workdir + '/' + name_sim + "/_pyhelp_outputs_grid.nc"
        dem_path = stable_folder + "/geographic/watershed_box_buff_dem.tif"
    
        ds  = xr.open_dataset(nc_path)
        dem = rxr.open_rasterio(dem_path)
    
        R = ds["rechg"]
        R = R.rio.write_crs(dem.rio.crs)
    
        Rt   = R.rio.reproject_match(dem, nodata=0.0)
        cube = Rt.values / 1000
    
        recharge_dict = {i: cube[i] for i in range(cube.shape[0])}
        
        rech_dict = "ton netcdf importe"
    
    #%% ---- RECHARGE

    # Necessary to set model parameters

    climatic.update_sim2_reanalysis(var_list=['runoff', 'recharge'],
                                           nc_data_path=Path(initializing.catch_folder) / 'results_stable' / 'climatic',
                                           first_year=2003,
                                           last_year=2003,
                                           time_step='ME',
                                           sim_state='transient',
                                           spatial_mean=True,
                                           geographic=geographic,
                                           disk_clip=geographic.watershed_shp) # for clipping the netcdf files saved on disk
                                                                    # can be a shapefile path or a flag: 'watershed' or False

    # # # # Units
    # climatic.t = climatic.t / 1000 # from mm to m
    # climatic.precip = climatic.precip / 1000 # from mm to m
    # climatic.etp = climatic.etp / 1000 # from mm to m
    climatic.runoff = climatic.runoff / 1000 # from mm to m
    climatic.recharge = climatic.recharge / 1000 # from mm to m

    # Use SIM2 reanalysis data directly (no synthetic data)
    R_mm_day = climatic.recharge
    r_mm_day = climatic.runoff
    
    if display_plots:
        fig, axs = plt.subplots(3,1, figsize=(8,8), sharex=True)
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

        ax = axs[2]
        ax.plot(30*R_mm_day, label='Recharge', c='dodgerblue', lw=2)
        ax.set_title('SIM2 Reanalysis', fontsize=8)
        ax.set_ylabel('R [mm/month]')

        ax.set_xlabel('Date')

        # Save plot as PNG
        fig.tight_layout()

    #%% ---- MODELING

    #%% VERSION

    vers = 'TRANS1'

    #%% IMPORT

    # iD_set_simulations = vers

    # folder = glob.glob(os.path.join(calibration_folder, iD_set_simulations+'*'))
    # pickle_file = glob.glob(folder[0]+'/'+'results_'+vers+'*.pkl')[0]
    # with open(pickle_file, 'rb') as f:
    #     d = pickle.load(f)
    # list_model_name = d['list_model_name'][:]
    # list_model_modflow = d['list_model_modflow'][:]

    # model_name = list_model_name[0]
    # model_modflow = list_model_modflow[0]

    #%% A - MODFLOW

    initializing.calibration_folder = calibration_folder

    box = True # or False
    sink_fill = False # or True
    # sim_state = 'steady' # 'steady' or 'transient'
    sim_state = 'transient' # 'steady' or 'transient'
    # first_clim = 'mean' # or 'first or value
    plot_cross = True
    cross_ylim = [0,150]
    check_grid = True
    dis_perlen = True
    nlay = 10
    lay_decay = 1.2 # 1 for no decay
    verti_hk = None # or [ [1e-5, [0, 20]],
    verti_sy = None
    verti_ss = None
    cond_drain = None # or value of conductance
    sy = 1 / 100 # -
    sy_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
    hk_decay = 0
    ss = 1e-5
    ss_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
    bc_left = None # or value
    bc_right = None # or value
    zone_partic = 'domain' # or watershed
    vka = 1
    bottom = 0
    thickness = 100
    Klog_transf = False

    # Recharge
    rec = R_mm_day
    run = r_mm_day
    first_clim = 'mean'
    climatic.update_first_clim(first_clim)
    climatic.update_recharge(rec, sim_state=sim_state)
    climatic.update_runoff(run, sim_state=sim_state)

    # Fixed
    setting.update_box_model(box)
    setting.update_sink_fill(sink_fill)
    setting.update_simulation_state(sim_state)
    hydraulic.update_nlay(nlay) # 1
    hydraulic.update_lay_decay(lay_decay) # 1
    hydraulic.update_cond_drain(cond_drain)
    hydraulic.update_sy(sy)
    hydraulic.update_sy_decay(sy_decay)
    hydraulic.update_ss(ss)
    hydraulic.update_ss_decay(ss_decay)
    hydraulic.update_vka(vka)
    hydraulic.update_hk_vertical(verti_hk) # here for lays [ [1e-5m/s, [0, 20m]]
    hydraulic.update_sy_vertical(verti_sy)
    hydraulic.update_ss_vertical(verti_ss)
    hydraulic.update_bottom(bottom)
    setting.update_dis_perlen(dis_perlen)
    setting.update_bc_sides(bc_left, bc_right)
    hydraulic.update_thick(thickness)

    # Well settings
    well_1_coords = [1-1,40-1,40-1] # [lay, row, col]
    well_2_coords = [1-1,65-1,65-1] # [lay, row, col]
    well_1_fluxes = pd.Series([-200, -1000, -100, 0, 0, 0, 0, 0, 0, 0, 0, -1000]) # [L3/T]
    well_2_fluxes = pd.Series([0, -1000, 0, -500, 0, 0, -500, 0, 0, 0, 0, -1000]) # [L3/T]
    setting.update_well_pumping(well_coords=[well_1_coords, well_2_coords],
                                    well_fluxes=[well_1_fluxes, well_2_fluxes])

    alpha = 15 # in m
    n_factor = 2

    the_K0 = 5e-5*24*3600
    hydraulic.update_hk(the_K0) # 3D
    Kmin_for_hk_decay = 1e-8*24*3600
    hydraulic.update_hk_decay(1/alpha, min_value=Kmin_for_hk_decay, log_transf=Klog_transf, grad_elev=[93,136,-20]) # 0

    # the_sy0 = 0.1/100 #
    the_sy0 = 2/100 #
    hydraulic.update_sy(the_sy0)
    Symin_for_sy_decay = 0.1/100
    hydraulic.update_sy_decay((1/alpha)/n_factor, min_value=Symin_for_sy_decay, log_transf=Klog_transf, grad_elev=[93,136,-20]) # 0
    # hydraulic.update_sy_decay(0) # 0

    the_ss0 = 1e-10
    hydraulic.update_ss(the_ss0)
    # Ssmin_for_ss_decay = 1e-10
    # hydraulic.update_ss_decay((1/alpha)/n_factor, min_value=Ssmin_for_ss_decay, log_transf=Klog_transf, grad_elev=[93,136,-20]) # 0
    hydraulic.update_ss_decay(0) # 0

    compt = 0

    # Change

    model_name = f"{vers}_{compt}_K{the_K0/24/3600:.1e}_a{alpha:.1f}_Sy{the_sy0*100:.1f}"
    print(model_name)

    setting.update_model_name(model_name)

    setting.update_check_model(plot_cross=plot_cross, check_grid=check_grid, cross_ylim=[0,200])

    for_calib = False
    if for_calib == False:
            model_folder = initializing.simulations_folder
    else:
        model_folder = initializing.calibration_folder
    model_modflow = Modflow(geographic,
                            # Workflow settings
                            model_folder=model_folder,   # self.simulations_folder
                            model_name=setting.model_name,
                            bin_path=initializing.bin_path,
                            # Model settings
                            box=setting.box,
                            sink_fill=setting.sink_fill,
                            sim_state=setting.sim_state,
                            dis_perlen=setting.dis_perlen,
                            # Well settings
                            well_coords=setting.well_coords,
                            well_fluxes=setting.well_fluxes,
                            # Output settings
                            plot_cross=setting.plot_cross,
                            cross_ylim=setting.cross_ylim,
                            check_grid=setting.check_grid,
                            # Boundary settings
                            sea_level=oceanic.MSL,
                            bc_left=setting.bc_left,
                            bc_right=setting.bc_right,
                            # Climatic settings
                            recharge=climatic.recharge,
                            runoff=climatic.runoff,
                            first_clim=climatic.first_clim,
                            # Hydraulic settings
                            bottom=hydraulic.bottom,
                            thick=hydraulic.thick,
                            nlay=hydraulic.nlay,
                            lay_decay=hydraulic.lay_decay,
                            hk_value=hydraulic.hk_value,
                            sy_value=hydraulic.sy_value,
                            ss_value=hydraulic.ss_value,
                            hk_decay=hydraulic.hk_decay,
                            sy_decay=hydraulic.sy_decay,
                            ss_decay=hydraulic.ss_decay,
                            verti_hk=hydraulic.verti_hk,
                            verti_sy=hydraulic.verti_sy,
                            verti_ss=hydraulic.verti_ss,
                            cond_drain=hydraulic.cond_drain,
                            vka=hydraulic.vka,
                            exdp=hydraulic.exdp)

    model_modflow.pre_processing() # verbose

    list_model_name = []
    list_model_name.append(model_name)
    list_model_modflow = []
    list_model_modflow.append(model_modflow)

    dictio = {}
    dictio['list_model_name'] = list_model_name
    dictio['list_model_modflow'] = list_model_modflow
    pickle_file = os.path.join(initializing.simulations_folder, model_name, 'results_'+model_name+'.pkl')
    with open(pickle_file, 'wb') as f:
        pickle.dump(dictio, f)

    success_model = model_modflow.processing(write_model=True, run_model=True, link_mt3dms=True)

    prob_cells = model_modflow.prob_cells

    if success_model == True:
        model_modflow.post_processing(model_modflow,
                            watertable_elevation = True,
                            seepage_areas = True,
                            outflow_drain = True,
                            accumulation_flux = True,
                            watertable_depth = True,
                            groundwater_flux = False,
                            groundwater_storage = False,
                            intermittency_weekly = False,
                            intermittency_monthly = True,
                            intermittency_yearly = False,
                            export_all_tif = False)

    timeseries_results = timeseries.Timeseries(geographic,
                                            model_modflow=model_modflow,
                                            model_modpath=None,
                                            model_mt3dms=None,
                                            datetime_format=True,
                                            subbasin_results=True,
                                            intermittency_weekly=False,
                                            intermittency_monthly = True,
                                            intermittency_yearly=False) # or None

    iter_results = MatchingStreams(geographic, hydrography, initializing, iteration_label=model_name, from_calib=False)

    # obs_to_sim = gpd.read_file(os.path.join(initializing.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
    # obs_to_simf = gpd.read_file(os.path.join(initializing.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
    # obsf_to_sim = gpd.read_file(os.path.join(initializing.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
    obsf_to_simf = gpd.read_file(os.path.join(initializing.simulations_folder, model_name, '_matchingstreams','obsflowf.shp'))

    # sim_to_obs = gpd.read_file(os.path.join(initializing.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
    # sim_to_obsf = gpd.read_file(os.path.join(initializing.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
    # simf_to_obs = gpd.read_file(os.path.join(initializing.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
    simf_to_obsf = gpd.read_file(os.path.join(initializing.simulations_folder, model_name, '_matchingstreams','simflowf.shp'))

    # mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
    # mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
    # mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
    mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])

    # mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
    # mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
    # mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
    mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])

    ### vf simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year) ==> isba
    obs = mean_obsf_to_simf
    sim = mean_simf_to_obsf
    indicator = sim/obs

    #%% PLOT CROSS-SECTION
    if display_plots:
        fig, ax = plt.subplots(1, 1, figsize=(6,4), dpi=300)
        print(stable_folder)

        mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
        watertable_elevation = np.load(os.path.join(simulations_folder, model_name, '_postprocess', 'watertable_elevation.npy'), allow_pickle=True).item()

        dem_data = imageio.imread(geographic.watershed_dem)
        wt_data = watertable_elevation[2]

        xvalues = np.linspace(-1,1,dem_data.shape[1])
        yvalues = np.linspace(-1,1,dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues,yvalues)

        cur_x = dem_data.shape[1] /2
        cur_x = 50

        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
        dem_v_plot = dem_prof[:,int(cur_x)]
        dem_v_plot[dem_v_plot == 0] = np.nan
        wt_v_plot = wt_prof[:,int(cur_x)]
        wt_v_plot[wt_v_plot == 0] = np.nan

        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-20, wt_v_plot, color='dodgerblue', alpha=0.5, lw=0)
        w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1.5)
        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot, color='saddlebrown', alpha=0.5, lw=0)
        d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
        ax.fill_between(np.arange(xx.shape[0])*75, 0, dem_v_plot-20, color='lightgrey', alpha=0.5, lw=0)
        ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-20, color='dimgray', lw=1.5)

        ax.set_xlim(1500, 4900)
        ax.set_ylim(90, 130)
        ax.set_yticks([90,100,110,120,130])
        ax.set_xlabel('Distance [m]')
        ax.set_ylabel('Elevation [m]')

        plt.tight_layout()

        # fig.savefig(out_path+'/'+watershed_name+'/results_simulations/'+model_name+'/_postprocess/_figures/'+'2D_cross.png', dpi=300, bbox_inches='tight')

    #%% PLOT STREAMFLOW

    area = int(round(geographic.catch_area))

    Qobs_path = data_path / 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'
    Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
    date = pd.to_datetime(Qobs[0]+' '+Qobs[1], format="%d/%m/%Y %H:%M:%S")
    Qobs.index = date
    Qobs = Qobs[2].to_frame(name="Q")
    Qobs = Qobs / 1000 # L/d to m3/d
    Qobs = (Qobs / (area*1000000)) # m3/d to m/day
    Qobs = Qobs.resample('ME').mean()
    # Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month
    # Qobs = select_period(Qobs, 2003, 2003)
    Qobs = Qobs * 30 * 1000

    simul_list = sorted(glob.glob(os.path.join(simulations_folder,vers+'*')), key=os.path.getmtime)

    if display_plots:
        for i, simul in enumerate(simul_list[:]):

            fig, (a0) = plt.subplots(1, 1, figsize=(12,3.5), dpi=300)

            model_name = os.path.split(simul)[-1]

            Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * 30 * 1000
            rmod = Smod['runoff'] * 30 * 1000

            Omod = (Smod['outflow_drain'] * 30 * 1000)
            Qmod = Omod + rmod

            ax = a0
            ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
            # ax.fill_between(Omod.index, Omod, Qmod, color='red', lw=1, label='Simualted : outflow + runoff', alpha=0.5)
            # ax.plot(Omod, color='red', lw=2, label='Simulated: outflow')
            ax.plot(Qmod, color='red', lw=2, label='Simulated: outflow')
            ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
            ax.set_xlabel('Date')
            ax.set_ylabel('Q / A [mm/month]')
            # ax.set_yscale('log')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2002'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name.upper(), fontsize=10)
            ax.set_ylim(-5,100)

    #%% PLOT PIEZOMETRY

    # Qobs_path = data_path + 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'
    # Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
    # date = pd.to_datetime(Qobs[0]+' '+Qobs[1], format="%d/%m/%Y %H:%M:%S")
    # Qobs.index = date
    # Qobs = Qobs[2].to_frame(name="Q")
    # Qobs = Qobs / 1000 # L/d to m3/d
    # Qobs = (Qobs / (area*1000000)) # m3/d to m/day
    # Qobs = Qobs.resample('W').mean()
    # # Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month
    # # Qobs = select_period(Qobs, 2003, 2003)
    # Qobs = Qobs * 7 * 1000

    simul_list = sorted(glob.glob(os.path.join(simulations_folder,vers+'*')), key=os.path.getmtime)
    if display_plots:
        for i, simul in enumerate(simul_list[:]):


            model_name = os.path.split(simul)[-1]

            Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * 30 * 1000

            WTEmod = Smod['watertable_elevation']
            WTDmod = Smod['watertable_depth']

            fig, (a0) = plt.subplots(1, 1, figsize=(12,3.5), dpi=300)

            ax = a0
            # ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
            # ax.fill_between(Omod.index, Omod, Qmod, color='red', lw=1, label='Simualted : outflow + runoff', alpha=0.5)
            ax.plot(WTDmod, marker='o', color='red', lw=2, label='Simulated: watertable')
            # ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
            ax.set_xlabel('Date')
            ax.set_ylabel('WT depth [m]')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name.upper(), fontsize=10)
            ax.set_ylim(0,None)
            ax.invert_yaxis()

            axb = ax.twinx()
            axb.bar(Rmod.index, Rmod, color='dodgerblue', width=10, edgecolor='None', lw=0, alpha=1, label='Recharge')
            axb.set_ylim(0,100)
            axb.invert_yaxis()
            axb.set_yticklabels([0,100])
            axb.legend(loc='upper right')

    #%% B - MODPATH

    list_folder = glob.glob(os.path.join(str(initializing.simulations_folder), vers+'*'))

    model_name = list_folder[0].split(os.path.sep)[-1]

    pickle_file = list_folder[0] + '/' + 'results_' + model_name + '.pkl'
    with open(pickle_file, 'rb') as f:
        d = pickle.load(f)

    list_model_name = d['list_model_name'][:]
    list_flow_model = d['list_model_modflow'][:]

    model_modflow = list_flow_model[0]

    # Prepare particle tracking from seepage inside the catchment studied
    tif_seep = os.path.join(initializing.simulations_folder, model_name, '_postprocess/_rasters','seepage_areas_t(0).tif')
    tif_seep_clip = os.path.join(initializing.simulations_folder, model_name, '_postprocess/_rasters','seepage_areas_t(0)_clip.tif')
    wbt.clip_raster_to_polygon(
        tif_seep,
        os.path.join(initializing.stable_folder, 'geographic', 'watershed.shp'),
        tif_seep_clip,
        maintain_dimensions=True)

    setting.update_input_particles(
                                    # zone_partic = tif_file_clip,
                                    # zone_partic = geographic.watershed_box_buff_dem,
                                    zone_partic = tif_seep_clip,
                                    cell_div = 1, # 1
                                    zloc_div = False,  # or False, add cells at cell bottom
                                    bore_depth = None, # '[0,5,10] for 3 particles or None
                                    track_dir = 'backward',
                                    # track_dir = 'forward', # backward
                                    sel_random = None, # or int
                                    sel_slice = None, # or int
                                    )

    if for_calib == False:
        model_folder = initializing.simulations_folder
    else:
        model_folder = initializing.calibration_folder

    model_modpath = Modpath(geographic,
                                    model_modflow,
                                    # Frame settings
                                    model_folder = model_folder,
                                    model_name = model_modflow.model_name,
                                    bin_path = initializing.bin_path,
                                    # Specific settings
                                    zone_partic = setting.zone_partic,
                                    cell_div = setting.cell_div,
                                    zloc_div = setting.zloc_div,
                                    bore_depth = setting.bore_depth,
                                    track_dir = setting.track_dir,
                                    sel_random = setting.sel_random,
                                    sel_slice = setting.sel_slice)

    # Preprocessing Modflow
    model_modpath.pre_processing() # verbose
    success_model = model_modpath.processing(write_model=True, run_model=True)
    model_modpath.post_processing(model_modpath,
                        ending_point=True,
                        starting_point=True,
                        pathlines_shp=True,
                        particles_shp=True,
                        random_id=None, # select randomly to save (for pathlines and particles)
                        ) # None

    model_modpath.filt_processing(model_modpath,
                        norm_flux=True, # for forward only
                        filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                        filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                        filt_inout=True, # delete particles in and out in the same cell (first layer)
                        calc_rtd=False, # compute residence time distribution
                        random_id=None, # select randomly to keep
                        ) # None

    #%% PLOT PATHLINES

    shp_pathlines = gpd.read_file(os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'pathlines_weighted.shp'))
    shp_endpoints = gpd.read_file(os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'starting_weighted.shp'))

    line = gpd.read_file(os.path.join(stable_folder, 'geographic', 'watershed.shp'))

    dem_rio = rasterio.open(geographic.watershed_box_buff_dem)
    dem_data = dem_rio.read(1)
    dem_data = np.ma.masked_where(dem_data < 0, dem_data)

    norm = mcolors.LogNorm(vmin=0.1, vmax=100)
    im = cm.ScalarMappable(cmap='jet', norm=norm)
    im.set_array([])

    if display_plots:
        fig, ax = plt.subplots(1,1, figsize=(8,6))

        # Base raster and layers
        rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform,
                        cmap='Greys', alpha=0.7, zorder=-10)

        shp_pathlines.plot(ax=ax, column='time_win_y', cmap='jet', lw=1,
                        norm=norm, zorder=1)

        shp_endpoints.plot(ax=ax, column='time_win_y', cmap='jet', lw=0.5, markersize=20,
                                legend=False, norm=norm, zorder=2, edgecolor='k')

        line.plot(ax=ax, facecolor='None', edgecolor='k', lw=2, zorder=-1)

        # Title
        ax.set_title('Residence times - backward from seepage [y]', fontsize=10)

        # Colorbar on the right, same height
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.1)
        cbar = fig.colorbar(im, cax=cax, orientation='vertical')

        fig.tight_layout()

        # fig.savefig(os.path.join(simulations_folder, model_name,
        #                             '_postprocess', '_figures', 'RTD_'+model_name+'.png'))

    #%% PLOT 2D

    visu = visualization_results.Visualization(initializing, geographic, hydrography, model_name)
    if display_plots:
        visu.visual2D(object_list = [
                                    'map',
                                    'grid',
                                    'watertable',
                                    'watertable_depth',
                                    'drain_flow',
                                    'surface_flow',
                                    'pathlines',
                                    'residence_times'
                                    ],
                    color_scale = [
                                    (None,None),
                                    (None,None),
                                    (None,None),
                                    (None,None),
                                    (None,None),
                                    (None,None),
                                    (0,10),
                                    (0,10),
                                    ],
                                    lines=1000
                                    )

    #%% PLOT 3D
    export_vtuvtk.VTK(initializing,geographic, hydrography, model_name)
    if display_3D==True:
        visu = visualization_results.Visualization(initializing,geographic, hydrography, model_name)
        if display_plots:
            visu.visual3D(interactive=True, object_list=[
                                                        'grid',
                                                        'watertable',
                                                        'watertable_depth',
                                                        'surface_flow',
                                                        'drain_flow',
                                                        'pathlines'
                                                        ],
                                                        view='south-west',
                                                        # view='north',
                                                        lines=None,
                                                        cloc=(0.7,0.1),
                                                        z_scale=10)

    #%% C - MT3DMS

    list_folder = glob.glob(os.path.join(str(initializing.simulations_folder), vers+'*'))

    model_name = list_folder[0].split(os.path.sep)[-1]

    pickle_file = list_folder[0] + '/' + 'results_' + model_name + '.pkl'
    with open(pickle_file, 'rb') as f:
        d = pickle.load(f)

    list_model_name = d['list_model_name'][:]
    list_flow_model = d['list_model_modflow'][:]

    model_modflow = list_flow_model[0]

    nper = model_modflow.nper
    nlay = model_modflow.mf.nlay
    nrow = model_modflow.mf.nrow
    ncol = model_modflow.mf.ncol

    sconc_init = np.ones((nlay, nrow, ncol)) * (100/1000) # 50 mg/L en kg/m3
    sconc_input = {i: np.ones((nrow, ncol)) * (50/1000) for i in range(nper)}
    sconc_input = dict(islice(sconc_input.items(), 1, None))
    rate_decay = np.ones((nlay, nrow, ncol)) * (1/(2*365))

    transport.update_mt3dms_parameters(
                    spc_name='NO3',
                    sconc_init=sconc_init,          # array of (nlay, nrow, ncol)
                    sconc_input=sconc_input,         # dictionnray [time] with array of (nlay, nrow, ncol)
                    disp_long=0,           # float, longitudinal dispersitvity in meters
                    disp_transh=0,         # float, ratio of the horizontal transverse dispersivity to disp_long, usually 0.1*disp_long
                    disp_transv=0,         # float, ratio of the vertical transverse dispersivity to disp_long, usually 0.01*disp_long
                    diffu_coeff=1e-10*3600*24,         # molecular diffusion in (L2T-1)
                    react_order=1,      # None: no-reaction, 0: zero-order, 1: first-order
                    rate_decay=rate_decay,          # array of (nlay, nrow, ncol), unit T-1
                    plot_conc=True)

    scenario = 's1'

    if for_calib == False:
        model_folder = initializing.simulations_folder
    else:
        model_folder = initializing.calibration_folder
    suffix_name = '_mt_'+scenario
    model_mt3dms = Mt3dms(geographic,
                        model_modflow,
                        # Frame settings
                        model_folder = model_folder,
                        model_name = model_modflow.model_name,
                        suffix_name = suffix_name,
                        bin_path = initializing.bin_path,
                        # Specific settings
                        spc_name = transport.spc_name,
                        sconc_init = transport.sconc_init,
                        sconc_input = transport.sconc_input,
                        disp_long = transport.disp_long,
                        disp_transh = transport.disp_transh,
                        disp_transv = transport.disp_transv,
                        diffu_coeff = transport.diffu_coeff,
                        react_order = transport.react_order,
                        rate_decay = transport.rate_decay,
                        plot_conc = transport.plot_conc,
                            )
    model_mt3dms.pre_processing()


    success_mt3dms = model_mt3dms.processing(write_model=True, run_model=True, verbose=True)

    pp_model = model_mt3dms.post_processing(model_mt3dms,
                            concentration_seepage=True,
                            mass_seepage=True,
                            mass_accumulated=True,
                            export_all_tif=True) # None

    timeseries_results = timeseries.Timeseries(geographic,
                                               model_modflow=model_modflow,
                                                model_modpath=model_modpath,
                                                model_mt3dms=model_mt3dms,
                                                suffix_name=scenario,
                                                datetime_format=True,
                                                subbasin_results=True,
                                                intermittency_weekly=False,
                                                intermittency_monthly = True,
                                                residence_times=True,
                                                concentration_seepage=True,
                                                mass_accumulated=True
                                                ) # or None

    #%% PLOT CONCENTRATION

    if display_plots:
        # Créer le GIF à la fin du processus
        vgif_name = vers
        gif_name = vgif_name+'.gif'

        plot_gif = True

        input_no3 = model_mt3dms.sconc_input[1].mean() * 1000

        ### USEFUL LINKS
        # https://www2.hawaii.edu/~jonghyun/classes/S18/CEE696/files/11_flopy_mt3dms_transport_modeling.pdf
        # https://download.feflow.com/html/help72/feflow/09_Parameters/Auxiliary_Data/peclet_number.html
        # https://flopy.readthedocs.io/en/3.4.2/Notebooks/mt3dms_examples.html#

        ucnobj  = bf.UcnFile(model_modflow.full_path + '/' + model_mt3dms.model_name_mt+'.UCN')
        concobj_1c = ucnobj.get_alldata(mflay=None) # 4D:[time, lay, row, col]

        concobj_1c_fil = concobj_1c.copy() * 1000
        concobj_1c_fil[concobj_1c_fil>=1e30] = np.nan
        concobj_1c_fil = concobj_1c_fil[:]

        concobj_1c_fil_surf = {}

        the_mins = []
        the_maxs = []

        # Boucle sur chaque pas de temps
        # for i in range(len(concobj_1c_fil)):
        for i in range((model_mt3dms.model_modflow.nper)):
            the_time = i
            # print(i)
            # try:
            seep = imageio.imread(os.path.join(model_modflow.full_path, f'_postprocess/_rasters/outflow_drain_t({int(the_time)}).tif'))
            # except:
            #     continue
            concobj_1c_fil_surf[the_time] = concobj_1c_fil[the_time+1][0]
            concobj_1c_fil_surf[the_time] = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf[the_time])
            # concobj_1c_fil[the_time][0][concobj_1c_fil[the_time][0] <= 0] = np.nan

            the_mins.append(np.nanmin(concobj_1c_fil_surf[the_time]))
            the_maxs.append(np.nanmax(concobj_1c_fil_surf[the_time]))

        the_min = np.nanmin(the_mins)
        the_max = np.nanmax(the_maxs)

        concobj_1c_fil_surf = dict(list(concobj_1c_fil_surf.items())[:])

        # Liste pour accumuler les boxplots précédents
        all_box_stats = []

        # Définir le répertoire de sauvegarde des images
        figures_dir = os.path.join(str(simulations_folder), '_figures/')
        if not os.path.exists(figures_dir):
            os.makedirs(figures_dir)

        mean_vals = []
        mean_times = []

        wbt.hillshade(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'), os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

        dem = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
        hill = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

        # Boucle sur chaque pas de temps
        for i in range(len(concobj_1c_fil_surf)):
            the_time = i

            conc_plt = concobj_1c_fil_surf[i]

            xi = conc_plt.flatten()
            xi = xi[~np.isnan(xi)]

            xpos = mdates.date2num(R_mm_day.index[i])

            if xi.size == 0:
                continue

            q10 = np.nanmin(xi)
            q90 = np.nanmax(xi)
            median = np.nanmedian(xi)
            mean = np.nanmean(xi)

            box_stats = [{
                'med': median,
                'mean': mean,
                'q1': q10,
                'q3': q90,
                'whislo': q10,
                'whishi': q90,
                'fliers': []
            }]

            mean_vals.append(mean)
            mean_times.append(xpos)

            # Ajouter les boxplots cumulés à chaque itération
            all_box_stats.append((xpos, box_stats))  # Conserver les résultats des boxplots précédents

            # Créer une nouvelle figure et des axes à chaque itération
            fig, axs = plt.subplots(2, 1, figsize=(8, 12), dpi=300, gridspec_kw={'height_ratios': [1, 3]})
            ax = axs.ravel()

            # Graphique du boxplot et de la recharge (subplot du haut)
            axb = ax[0].twinx()

            ax[0].zorder = 1
            axb.zorder = 0 # fills in back
            ax[0].patch.set_visible(False)

            # Ajouter les boxplots précédents et actuels à la figure
            for xpos, box_stat in all_box_stats:
                ax[0].bxp(box_stat, positions=[xpos], widths=5, showfliers=False,
                        showmeans=True, meanline=False,
                        boxprops=dict(color='forestgreen', alpha=1, linewidth=1),
                        medianprops=dict(color='forestgreen', linewidth=1),
                        meanprops=dict(marker='o', markerfacecolor='k', markeredgecolor='k', markersize=5),
                        whiskerprops=dict(linestyle='-', linewidth=0),
                        capprops=dict(linewidth=0),
                        zorder=1)  # low zorder → in background

            # Mettre à jour la ligne verticale du premier graphique
            ax[0].axvline(x=xpos, color='black', linestyle='--', lw=0.5, zorder=-1)

            ax[0].axhline(y=input_no3, color='darkorange', linestyle='-', lw=1, zorder=-1,
                        label='Injection: 50 mg/L \nNO3 decay : 1/2 y$^{-1}$ \nDispersivity: 5 m longi., 0.5 m trans h., 0.05 m trans v. \nDiffusion: 10$^{-10}$ m²/s',
                        )

            # if i==0:
            ax[0].legend(loc='upper center', frameon=False)

            # Réglages pour le graphique de concentration
            ax[0].set_ylabel('[NO3] mg/L', color='forestgreen')
            ax[0].set_title('Synthetic drought year - Initial: mean recharge and aquifer at 100 mg/L', fontsize=10)
            ax[0].xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1))
            ax[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax[0].tick_params(axis='x', labelrotation=90, labelsize=8)
            ax[0].set_ylim(30, 100)

            # Line connectant les moyennes
            ax[0].plot(mean_times, mean_vals, color='black', lw=2, linestyle='-', zorder=2)

            # Placer la recharge en arrière-plan du graphique
            axb.step(R_mm_day.index, R_mm_day * 30, lw=2, color='dodgerblue', zorder=0)
            axb.set_ylabel('Recharge [mm/month]', color='dodgerblue')

            ax[0].set_xlim(pd.to_datetime('01-2003'), pd.to_datetime('01-2004'))

            # New xi
            xi = conc_plt.copy()

            # Créer un graphique avec la carte
            norm = mcolors.LogNorm(vmin=30, vmax=100)
            color_camp = 'turbo'
            sm = cm.ScalarMappable(cmap=color_camp, norm=norm)
            sm.set_array([])

            rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)),
                            ax=ax[1], transform=hill.transform,
                            cmap='Greys_r', alpha=0.75, zorder=-10,
                            )

            rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, xi),
                            ax=ax[1], transform=dem.transform,
                            cmap=color_camp, alpha=1, zorder=1,
                            # norm=norm
                            )

            # Ajouter les limites du bassin versant
            shp_bv = gpd.read_file(geographic.watershed_shp)
            shp_hydro = gpd.read_file(hydrography.streams)
            shp_bv.plot(ax=ax[1], facecolor='None', lw=3, zorder=2)
            shp_hydro.plot(ax=ax[1], color='navy', lw=1, zorder=0)

            divider = make_axes_locatable(ax[1])
            cax = divider.new_vertical(size='5%', pad=0.6, pack_start=True)
            fig.add_axes(cax)
            cbar = fig.colorbar(sm, cax=cax, orientation='horizontal', label='[NO3]')
            cbar.ax.set_xticks([30, 50, 70 ,100])
            cbar.ax.set_xticklabels([30, 50, 70, 100])  # (facultatif) si tu veux formater les labels
            fig.tight_layout()

            # Sauvegarder la figure pour ce temps
            fig.tight_layout()
            fig.savefig(figures_dir+vgif_name+'_'+str(i)+'_'+model_name+'.png', dpi=300, bbox_inches='tight')

            # Fermer la figure pour économiser de la mémoire
            if i < (len(concobj_1c_fil_surf)-1):
                plt.close(fig)
            else:
                plt.show()

        if plot_gif == True:
            # Créer le GIF à partir des images enregistrées
            begin_by = figures_dir + vgif_name
            filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
            images = []
            for filename in filenames:
                images.append(imageio.imread(filename))
            ### Method 1
            # imageio.mimsave(figures_dir + '_' + gif_name, images, duration=0.5, loop=0, format='GIF-PIL')
            image_paths = filenames
            images = [Image.open(img) for img in image_paths]
            ### Method 2
            images[0].save(figures_dir + '_' + gif_name, save_all=True, append_images=images[1:], optimize=True, duration=200, loop=0)

        #%% PLOT INTERACTIVE

        # CLICK on the map to select a cross-section !
        dem_data = imageio.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif')) # dem data
        stream_data = imageio.imread(os.path.join(stable_folder,'hydrography','botopage2024_naizin_streams_perennial-intermittent.tif')) # river data
        watertable_data = imageio.imread(os.path.join(simulations_folder,model_name,'_postprocess/_rasters/','watertable_elevation_t(0).tif')) # watertable data
        interactive = True
        visu = visualization_results.Visualization(initializing, geographic, hydrography, model_name)
        visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)

        #%% WEB ANIMATION

        import plotly.graph_objects as go
        import base64
        from io import BytesIO

        # Exemple : création de la liste des fichiers
        figures_dir = os.path.join(str(simulations_folder), '_figures/')
        begin_by = figures_dir + vers
        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)

        # Charger toutes les images en base64
        def image_to_base64(path):
            with Image.open(path) as img:
                with BytesIO() as stream:
                    img.save(stream, format="png")
                    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("utf-8")

        image_sources = [image_to_base64(p) for p in filenames]

        if not image_sources:
            raise FileNotFoundError(f"No PNG files matching {begin_by}*.png were found")

        base_image = dict(
            source=image_sources[0],
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            sizex=1,
            sizey=1,
            xanchor="center",
            yanchor="middle",
            sizing="contain"
        )

        frames = [
            go.Frame(
                name=str(i),
                layout=go.Layout(images=[dict(base_image, source=src)])
            )
            for i, src in enumerate(image_sources)
        ]

        # Première image (affichée par défaut)
        fig = go.Figure(
            layout=go.Layout(
                title="Slider to navigate between images",
                images=[base_image],
                updatemenus=[dict(
                    type="buttons",
                    showactive=False,
                    y=1.05,
                    x=1.15,
                    xanchor="right",
                    yanchor="top",
                    buttons=[
                        dict(label="Play", method="animate", args=[None, {"frame": {"duration": 500, "redraw": True}, "fromcurrent": True}]),
                        dict(label="Pause", method="animate", args=[[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}])
                    ]
                )],
                sliders=[{
                    "steps": [
                        {
                            "method": "animate",
                            "args": [[str(k)], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}}],
                            "label": f"{k+1}"
                        } for k in range(len(image_sources))
                    ],
                    "transition": {"duration": 0},
                    "x": 0.5,
                    "xanchor": "center",
                    "y": -0.01,
                    "yanchor": "top",
                    "len": 0.85,
                    "pad": {"t": 40}
                }]
            ),
            frames=frames
        )

        fig.update_layout(
            width=1600,
            height=900,
            margin=dict(l=60, r=60, t=60, b=90),  # Small margins for spacing
        )

        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)

        fig.show("browser")

#%% ---- RUN THE SCRIPT

if __name__ == '__main__':
    run_example12(out_path=out_path, display_plots=True, display_3D=True)

#%% ---- NOTES
