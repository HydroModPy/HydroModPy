# -*- coding: utf-8 -*-
"""
 * Author: T. Babey
 * Guidel field site simulation
"""

#%% ---- LIBRAIRIES

#%% PYTHON

# Filter warnings (before imports)
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import pkg_resources # Must be placed after DeprecationWarning as it is itself deprecated
warnings.filterwarnings('ignore', message='.*pkg_resources.*')
warnings.filterwarnings('ignore', message='.*declare_namespace.*')

# Libraries installed by default
import sys
import os
import datetime
import dateutil

# Libraries need to be installed if not
import numpy as np
import pandas as pd
import math

# Libraries added from 'conda install' procedure
import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib_scalebar.scalebar import ScaleBar
from mpl_toolkits.axes_grid1 import make_axes_locatable
import rasterio
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')
import flopy
import imageio

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from src import watershed_root
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from watershed import residencetimes
from watershed import streams
from modeling import radon_groundwater, radon_stream

# from os.path import dirname, abspath
# root_dir = dirname(dirname(dirname(dirname(dirname(abspath(__file__))))))
# print("Root path directory is: {0}".format(root_dir.upper()))
from src.tools import toolbox
root_dir = toolbox.hydromodpy_root(print_option=True)
sys.path.append(root_dir)

modflow_path = os.path.join(root_dir,'bin/')

# fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% PERSONAL

from os.path import dirname, abspath
csim_path = root_dir = dirname(abspath(__file__))
# data_path = os.path.join(csim_path,'data/')
data_path = os.path.join(csim_path,'data')
out_path = os.path.join(csim_path,'results')

print('The results of the example will be saved here :', out_path)

#%% ---- WATERSHED

#%% OPTIONS

dem_path = os.path.join(data_path,'dem_guidel_25m.tif')
# dem_path = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/dem_brittany/BDALTI_bzh_75m.tif'
# load = True
load = False
watershed_name = 'Guidel_Upstream-Lannenec_v3'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = [214866, 6758551 , 200 , 100 , 'EPSG:2154'] # [x, y, snap distance, buffer size]
bottom_path = None # path
save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

# BV = watershed_root.Watershed(dem_path=dem_path,
#                               out_path=out_path,
#                               load=load,
#                               watershed_name=watershed_name,
#                               save_object=save_object)

BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=from_lib, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=from_dem, # [path, cell size]
                              from_shp=from_shp, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              # nlay=10,
                              # lay_thickness=20,
                              bottom_path=bottom_path, # path 
                              save_object=save_object)

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

#%% ---- DATA

# Clips specific data at the catchment scale
# BV.add_geology(data_path, types_obs='GEO050K_HARM_056_S_FGEOL_2154.shp', fields_obs='CODE_LEG')
# BV.add_hydrography(data_path, types_obs=['tronconhydro_guidel_bdtopage'], fields_obs=['fid'])

# Vizualization
visualization_watershed.watershed_dem(BV)
# visualization_watershed.watershed_geology(BV)

#%% CASES



# # Necessary to set model parameters
BV.add_climatic()

# # Different cases of recharge implementation
# time_series = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10])
# BV.climatic.update_recharge(time_series, sim_state='transient')
# fig, ax = plt.subplots(1,1, figsize=(6,3))
# R = BV.climatic.recharge
# r = R * 0.1
# ax.plot(R, label='recharge_manual', c='dodgerblue', lw=2)
# ax.plot(r, label='runoff_manual', c='navy', lw=2)
# ax.set_xlabel('Months')
# ax.set_ylabel('[mm/month]')
# ax.legend()


#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
model_name = 'default'
box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True
dis_perlen = False

# Climatic settings
recharge = 300 / 12 / 30 /1000 # m/day
first_clim = 'first' # or 'first or value

# Hydraulic settings
nlay = 10
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 20 # if bottom is None, aquifer thickness
hk = 1e-5 * 24 * 3600 # m/day
cond_drain = None # or value of conductance
sy = 1 / 100 # -
ss = 1e-10

# Pumping wells settings
# TB : option to auto-convert EPSG coordinates into lay / row / col coordinate?
isUsed_pumping_wells = False
if isUsed_pumping_wells:
    well_1_coords = [1-1,9-1,29-1] # [lay, row, col]]
    well_1_fluxes = pd.Series([-200, 0, -100, 0, 0, 0, 0, 0, 0, 0, 0, 0]) # [L3/T]
    BV.settings.update_well_pumping(well_coords=well_1_coords,
                                    well_fluxes=well_1_fluxes)

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name)
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross)

# Climatic settings
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_hk(hk)
BV.hydraulic.update_sy(sy)
BV.hydraulic.update_ss(ss)
BV.hydraulic.update_cond_drain(cond_drain)
# BV.hydraulic.update_hk_decay(1/50, min_value=1e-10*24*3600, log_transf=False)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_dis_perlen(dis_perlen=dis_perlen)

#%% ---- MODELING

#%% MODFLOW

# model_modflow = BV.preprocessing_modflow(for_calib=False)
# success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

# #%% MODFLOW POSTPROCESSING
# if success_modflow == True:
#     BV.postprocessing_modflow(model_modflow,
#                               watertable_elevation = True,
#                               watertable_depth = True, 
#                               seepage_areas = True,
#                               outflow_drain = True,
#                               groundwater_flux = True,
#                               groundwater_storage = True,
#                               accumulation_flux = True,
#                               persistency_index = False,
#                               intermittency_monthly = False,
#                               intermittency_daily = False,
#                               export_all_tif = False)



#%% TEST

shrenv={}

# Modflow5
from src.modeling import Modflow5
mf5 = Modflow5('modflow5')
mf5.set_iptpar(model_folder = BV.simulations_folder,  
               model_name   = BV.settings.model_name)

# spatial discretization
from src.discretization import SDis
sdis = SDis('sdis')
sdis.set_iptpar(genmtd_surf   = 'from_demtif',
                demtif_path   = BV.geographic.watershed_box_buff_dem,
                genmtd_vert   = 'homogeneous',
                crs           = 'EPSG:2154',
                lenuni        = 'm',
                nlay          = 19,
                lay_thickness = [20,15,15,15,15,15,15,25,25,25,25,25,25,35,35,35,35,35,35])
                # nlay          = 10,
                # lay_thickness = [20,30,30,30,50,50,50,70,70,70])
mf5.add_module(sdis)

# time discretization
from src.discretization import TDis
tdis = TDis('tdis')
tdis.set_iptpar(sim_state = 'steady',
                nper      = 1,
                itmuni    = 'd')
# time discretization
# from src.discretization import TDis
# tdis = TDis('tdis')
# tdis.set_iptpar(sim_state    = 'transient',
#                 genmtd       = 'from_csv',
#                 datefilepath = 'C:/Users/trist/Documents/teaching/2024-2025/M1_statistiques/TP/TP1_voilage/donnees_voilage_nettoyees.csv',
#                 dateheader   = 'date',
#                 dateformat   = '%d/%m/%Y %H:%M',
#                 itmuni       = 'd')
# tdis.set_iptpar(sim_state    = 'transient',
#                 genmtd       = 'synthetic_regular',
#                 itmuni       = 'd',
#                 nper         = 30,
#                 lenper       = 1)
mf5.add_module(tdis)

# hydraulic conductivity
from parameters import HydraulicConductivity
hhc = HydraulicConductivity('hhc')
hhc.set_iptpar(genmtd_sdis = 'homogeneous',
                # value       = 1.4e-6,
                value       = 2.8e-6,
                lenuni      = 'm',
                itmuni      = 's',
                sgrid       = 'from_shrenv',
                tgrid       = 'from_shrenv')
# hhc.set_iptpar(genmtd_sdis    = 'exp_decay_depth',
#                 surfvalue      = 1.0e-5,
#                 decay_constant = 0.01,
#                 minvalue       = 1.0e-6,
#                 lenuni         = 'm',
#                 itmuni         = 's',
#                 sgrid          = 'from_shrenv',
#                 tgrid          = 'from_shrenv')
# hhc.set_iptpar(genmtd_sdis      = 'map_csv',
#                 fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/geol_model_XYZ_epsg2154_no_1st_layer.csv',
#                 crs_map_pos      = 'EPSG:2154',
#                 idheader_map_pos = 'facies',
#                 map_param_source = 'from_shrenv',
#                 set_first_layer_as_facies = '1111.0',
#                 fpath_map_par    = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/hydro_parameters_guidel.csv',
#                 idheader_value   = 'hk_ms',
#                 lenuni           = 'm',
#                 itmuni           = 's')
mf5.add_module(hhc)

geol_map_param = pd.read_csv('C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/hydro_parameters_guidel.csv', sep = '\t', index_col=0)
for facies in geol_map_param.columns.values:
    if facies == '1111.0':
        geol_map_param.at['hk_ms',facies] = 1.3e-6
    elif facies == '2222.0' or facies == '7777.0':
        geol_map_param.at['hk_ms',facies] = 8.5e-6
    elif facies == '6666.0':
        geol_map_param.at['hk_ms',facies] = 1.3e-7
    elif facies == '4444.0':
        geol_map_param.at['hk_ms',facies] = 1e-11

shrenv.update({'geol_map_param':geol_map_param})

# Specific yield
from parameters import SpecificYield
sy = SpecificYield('sy')
sy.set_iptpar(genmtd_sdis = 'homogeneous',
              value       = 0.05)
mf5.add_module(sy)

# Specific storage
from parameters import SpecificStorage
ss = SpecificStorage('ss')
ss.set_iptpar(genmtd_sdis = 'homogeneous',
              value       = 1e-10)
mf5.add_module(ss)

# Vertical anistropy K
from parameters import VerticalAnisotropyK
vka = VerticalAnisotropyK('vka')
vka.set_iptpar(genmtd_sdis = 'homogeneous',
               value       = 10)
mf5.add_module(vka)

# recharge
from parameters import Recharge
rec = Recharge('rec')
rec.set_iptpar(genmtd_sdis = 'homogeneous',
               genmtd_tdis = 'constant',
                value = 246,
                lenuni = 'mm',
                itmuni = 'Y')
# rec.set_iptpar(genmtd_sdis = 'homogeneous',
#                 genmtd_tdis = 'chronicles_csv',
#                 fpath_chron = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/rech_chronicles.csv',
#                 dateheader_chron = 'date',
#                 dateformat_chron = '%d/%m/%Y',
#                 lenuni           = 'mm',
#                 itmuni           = 'Y',
#                 idheader_value   = 'station2',   
#                 sgrid = 'from_shrenv',
#                 tgrid = 'from_shrenv')
# rec.set_iptpar(genmtd_sdis = 'map_csv',
#                 fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/weather_stations_pos_epsg2154.csv',
#                 crs_map_pos      = 'EPSG:2154',
#                 idheader_map_pos = 'station',
#                 genmtd_tdis = 'chronicles_csv',
#                 fpath_chron = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/rech_chronicles.csv',
#                 dateheader_chron = 'date',
#                 dateformat_chron = '%d/%m/%Y',
#                 lenuni           = 'mm',
#                 itmuni           = 'Y',  
#                 first_clim       = 'mean',
#                 sgrid = 'from_shrenv',
#                 tgrid = 'from_shrenv')
mf5.add_module(rec)

# # Evapotranspiration
# from parameters import Evapotranspiration
# evtr = Evapotranspiration('evt')
# evtr.set_iptpar(genmtd_sdis = 'homogeneous',
#                 genmtd_tdis = 'constant',
#                 genmtd_surf = 'from_dem',
#                 value       = 50,
#                 lenuni      = 'mm',
#                 itmuni      = 'Y')
# mf5.add_module(evtr)

# # sea level
# from parameters import SeaLevel
# slvl = SeaLevel('sealvl')
# slvl.set_iptpar(genmtd_tdis = 'constant',
#                 value = 0,
#                 lenuni = 'm',
#                 sgrid = 'from_shrenv',
#                 tgrid = 'from_shrenv')
# # slvl.set_iptpar(genmtd_tdis = 'chronicles_csv',
# #                 fpath_chron = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/rech_chronicles.csv',
# #                 dateheader_chron = 'date',
# #                 dateformat_chron = '%d/%m/%Y',
# #                 idheader_value   = 'station2',
# #                 lenuni           = 'mm', 
# #                 sgrid = 'from_shrenv',
# #                 tgrid = 'from_shrenv')
# mf5.add_module(slvl)

# initial boundary conditions
from parameters import InitialBoundaryCondition
ibound = InitialBoundaryCondition('ibnd')
ibound.set_iptpar(genmtd_sdis = 'all_active')
mf5.add_module(ibound)

# initial heads
from parameters import InitialHead
strh = InitialHead('strh')
strh.set_iptpar(genmtd_sdis = 'vertical_hydrostatic_equilibrium',
                genmtd_ihd  = 'dem')
mf5.add_module(strh)

# # drains
# from parameters import Drain
# drn = Drain('drn')
# drn.set_iptpar(genmtd_sdis  = 'surface_no_constanthead',
#                genmtd_value = 'conductance',
#                thickness    = 1,
#                lenuni       = 'm')
# mf5.add_module(drn)

# wells 
# from parameters import Well
# wel = Well('well')
# wel.set_iptpar(genmtd_pos       = 'map_csv',
#                 fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/pumping_wells_pos_epsg2154.csv',
#                 crs_map_pos      = 'EPSG:2154',
#                 idheader_map_pos = 'wells',
#                 genmtd_total_flux = 'chronicles_csv',
#                 fpath_chron       = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/pumping_wells_chronicles_m3d.csv',
#                 dateheader_chron  = 'date',
#                 dateformat_chron  = '%d/%m/%Y',
#                 lenuni            = 'm',
#                 itmuni            = 'd',
#                 genmtd_zdstr_flux = 'proportional_transmissivity',
#                 opposite_flux_sign_option = True)
# mf5.add_module(wel)

# # plot data options (hk...)
# # TODO@TB: rewrite
# mf5.set_advpar(plot_cross = BV.settings.plot_cross, 
#                # plot_cross = False,
#                # cross_ylim = BV.settings.cross_ylim, 
#                cross_ylim = [-500,50])

# # Check grid option (flow connectivity) 
# mf5.set_advpar(check_grid = True)

# # sea level
# from parameters import SeaLevel
# slvl = SeaLevel('sealvl')
# slvl.set_iptpar(genmtd_tdis = 'constant',
#                 value = 0,
#                 lenuni = 'm',
#                 sgrid = 'from_shrenv',
#                 tgrid = 'from_shrenv')
# mf5.add_module(slvl)

# drains
from parameters import Drain
drn = Drain('drn')
drn.set_iptpar(genmtd_sdis  = 'surface_no_constanthead',
               genmtd_value = 'conductance',
               thickness    = 1,
               lenuni       = 'm')
mf5.add_module(drn)

# wells 
from parameters import Well
wel = Well('well')
wel.set_iptpar(genmtd_pos       = 'map_csv',
                fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/pumping_wells_pos_epsg2154.csv',
                crs_map_pos      = 'EPSG:2154',
                idheader_map_pos = 'wells',
                genmtd_total_flux = 'chronicles_csv',
                fpath_chron       = 'C:/Users/trist/Documents/SSH/HydroModPy/users/tbabey/guidel/calibration_mean_water_levels/data/pumping_wells_chronicles_m3d.csv',
                dateheader_chron  = 'date',
                dateformat_chron  = '%d/%m/%Y',
                lenuni            = 'm',
                itmuni            = 'd',
                genmtd_zdstr_flux = 'proportional_transmissivity',
                opposite_flux_sign_option = True)
mf5.add_module(wel)

# plot data options (hk...)
# TODO@TB: rewrite
mf5.set_advpar(plot_cross = False, 
               cross_ylim = [-500,50])

# Check grid option (flow connectivity) 
mf5.set_advpar(check_grid_flow_connectivity = False,
               pc_verbose = False)

#%% TEST PP
shrenv = mf5.processing_modules(shrenv) 
mf5.preprocessing(shrenv)
shrenv,success_modflow = mf5.processing(shrenv)
#%% TEST PP
if success_modflow is True:
    mf5.dem_watershed_path = BV.geographic.watershed_box_buff_dem  #TODO@TB
    mf5.geographic = BV.geographic  #TODO@TB
    mf5.postprocessing(shrenv)

model_modflow = mf5
#%% TEST MODULES

# res={}

# # spatial discretization
# from src.discretization import SDis
# sdis = SDis('sdis')
# sdis.set_iptpar(genmtd_surf = 'from_demtif',
#                 demtif_path = BV.geographic.watershed_box_buff_dem,
#                 genmtd_vert = 'homogeneous',
#                 crs = 'EPSG:2154',
#                 lenuni = 'm',    
#                 nlay = 10,
#                 lay_thickness = 6)
# sdis.preprocessing(res)
# res = sdis.processing(res)

# # time discretization
# from src.discretization import TDis
# tdis = TDis('tdis')
# # tdis.set_iptpar(sim_state = 'steady',
# #                 nper      = 1,
# #                 itmuni    = 'd')
# # tdis.set_iptpar(sim_state    = 'transient',
# #                 genmtd       = 'from_csv',
# #                 datefilepath = 'C:/Users/trist/Documents/teaching/2024-2025/M1_statistiques/TP/TP1_voilage/donnees_voilage_nettoyees.csv',
# #                 dateheader   = 'date',
# #                 dateformat   = '%d/%m/%Y %H:%M',
# #                 itmuni       = 'd')
# tdis.set_iptpar(sim_state    = 'transient',
#                 genmtd       = 'synthetic_regular',
#                 itmuni       = 'd',
#                 nper         = 30,
#                 lenper       = 1)
# tdis.preprocessing(res)
# res = tdis.processing(res)

# # hydraulic conductivity
# from parameters import HydraulicConductivity
# hhc = HydraulicConductivity('hhc')
# # hhc.set_iptpar(genmtd_sdis = 'homogeneous',
# #                value       = 1.0e-5*3600*24,
# #                lenuni      = 'm',
# #                itmuni      = 'd',
# #                sgrid       = 'from_shrenv',
# #                tgrid       = 'from_shrenv')
# # hhc.set_iptpar(genmtd_sdis    = 'exp_decay_depth',
# #                surfvalue      = 1.0e-5*3600*24,
# #                decay_constant = 0.01,
# #                minvalue       = 1.0e-6*3600*24,
# #                lenuni         = 'm',
# #                itmuni         = 'd',
# #                sgrid          = 'from_shrenv',
# #                tgrid          = 'from_shrenv')
# hhc.set_iptpar(genmtd_sdis      = 'map_csv',
#                 fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/geol_model_XYZ_epsg2154.csv',
#                 crs_map_pos      = 'EPSG:2154',
#                 idheader_map_pos = 'facies',
#                 # fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/geol_model_XYZ_epsg27572.csv',
#                 # crs_map_pos      = 'EPSG:27572',
#                 fpath_map_par    = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/hydro_parameters_guidel.csv',
#                 idheader_value   = 'hk_ms',
#                 lenuni           = 'm',
#                 itmuni           = 's',
#                 sgrid            = 'from_shrenv',
#                 tgrid            = 'from_shrenv')

# hhc.preprocessing(res)
# res = hhc.processing(res)

# # recharge
# from parameters import Recharge
# rec = Recharge('rec')
# # rec.set_iptpar(genmtd_sdis = 'homogeneous',
# #                 genmtd_tdis = 'constant',
# #                 value = 300,
# #                 lenuni           = 'mm',
# #                 itmuni           = 'Y',
# #                 sgrid = 'from_shrenv',
# #                 tgrid = 'from_shrenv')
# # rec.set_iptpar(genmtd_sdis = 'homogeneous',
# #                 genmtd_tdis = 'chronicles_csv',
# #                 fpath_chron = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/rech_chronicles.csv',
# #                 dateheader_chron = 'date',
# #                 dateformat_chron = '%d/%m/%Y',
# #                 lenuni           = 'mm',
# #                 itmuni           = 'Y',
# #                 idheader_value   = 'station2',   
# #                 sgrid = 'from_shrenv',
# #                 tgrid = 'from_shrenv')
# rec.set_iptpar(genmtd_sdis = 'map_csv',
#                 fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/weather_stations_pos_epsg2154.csv',
#                 crs_map_pos      = 'EPSG:2154',
#                 idheader_map_pos = 'station',
#                 genmtd_tdis = 'chronicles_csv',
#                 fpath_chron = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/rech_chronicles.csv',
#                 dateheader_chron = 'date',
#                 dateformat_chron = '%d/%m/%Y',
#                 lenuni           = 'mm',
#                 itmuni           = 'Y',  
#                 first_clim       = 'mean',
#                 sgrid = 'from_shrenv',
#                 tgrid = 'from_shrenv')

# rec.preprocessing(res)
# res = rec.processing(res)

# # sea level
# from parameters import SeaLevel
# slvl = SeaLevel('sealvl')
# slvl.set_iptpar(genmtd_tdis = 'constant',
#                 value = 0,
#                 lenuni = 'm',
#                 sgrid = 'from_shrenv',
#                 tgrid = 'from_shrenv')
# # slvl.set_iptpar(genmtd_tdis = 'chronicles_csv',
# #                 fpath_chron = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/rech_chronicles.csv',
# #                 dateheader_chron = 'date',
# #                 dateformat_chron = '%d/%m/%Y',
# #                 idheader_value   = 'station2',
# #                 lenuni           = 'mm', 
# #                 sgrid = 'from_shrenv',
# #                 tgrid = 'from_shrenv')

# slvl.preprocessing(res)
# res = slvl.processing(res)

# # initial boundary conditions
# from parameters import InitialBoundaryCondition
# ibound = InitialBoundaryCondition('ibnd')
# ibound.set_iptpar(genmtd_sdis = 'all_active')

# ibound.preprocessing(res)
# res = ibound.processing(res)

# # initial heads
# from parameters import InitialHead
# strh = InitialHead('strh')
# strh.set_iptpar(genmtd_sdis = 'vertical_hydrostatic_equilibrium',
#                 genmtd_ihd  = 'dem')

# strh.preprocessing(res)
# res = strh.processing(res)

# # Specific yield
# from parameters import SpecificYield
# sy = SpecificYield('sy')
# sy.set_iptpar(genmtd_sdis = 'homogeneous',
#               value       = 0.02)

# sy.preprocessing(res)
# res = sy.processing(res)

# # Specific storage
# from parameters import SpecificStorage
# ss = SpecificStorage('ss')
# ss.set_iptpar(genmtd_sdis = 'homogeneous',
#               value       = 2e-10)

# ss.preprocessing(res)
# res = ss.processing(res)

# # Vertical anistropy K
# from parameters import VerticalAnisotropyK
# vka = VerticalAnisotropyK('vka')
# vka.set_iptpar(genmtd_sdis = 'homogeneous',
#                 value       = 10)

# vka.preprocessing(res)
# res = vka.processing(res)

# # Evapotranspiration
# from parameters import Evapotranspiration
# evtr = Evapotranspiration('evapo')
# evtr.set_iptpar(genmtd_sdis = 'homogeneous',
#                 genmtd_tdis = 'constant',
#                 value       = 1e-3)

# evtr.preprocessing(res)
# res = evtr.processing(res)

# # drains
# from parameters import Drain
# drn = Drain('drn')
# drn.set_iptpar(genmtd_sdis  = 'surface_no_constanthead',
#                 genmtd_value = 'conductance',
#                 thickness    = 50,
#                 lenuni       = 'cm')

# drn.preprocessing(res)
# res = drn.processing(res)

# from parameters import Well
# wel = Well('well')

# wel.set_iptpar(genmtd_pos       = 'map_csv',
#                fpath_map_pos    = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/pumping_wells_pos_epsg2154.csv',
#                crs_map_pos      = 'EPSG:2154',
#                idheader_map_pos = 'wells',
#                genmtd_total_flux = 'chronicles_csv',
#                fpath_chron       = 'C:/Users/trist/Documents/SSH/HydroModPy/src/geomodeller/data/geol_model/pumping_wells_chronicles_m3d.csv',
#                dateheader_chron  = 'date',
#                dateformat_chron  = '%d/%m/%Y',
#                lenuni            = 'm',
#                itmuni            = 'd',
#                genmtd_zdstr_flux = 'proportional_transmissivity',
#                opposite_flux_sign_option = True)
# wel.preprocessing(res)
# res = wel.processing(res)

#%% MODPATH

# # case = 'bw_seepage'
# # case = 'bw_wells'
# case = 'fw_recharge'

# if case == 'bw_seepage':
#     # Prepare backward particle tracking from seepage inside the catchment studied
#     tif_seep = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0).tif'
#     tif_seep_clip = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0)_clip.tif'
#     wbt.clip_raster_to_polygon(
#         tif_seep, 
#         BV.stable_folder + '/geographic/watershed.shp', 
#         tif_seep_clip, 
#         maintain_dimensions=True)
    
#     BV.settings.update_input_particles(zone_partic = tif_seep,
#                                        cell_div = 1, # 1
#                                        zloc_div = True,  # or True, add cells at cell bottom
#                                        bore_depth = True, # '[0,5,10] for 3 particles or None
#                                        track_dir = 'backward',
#                                        sel_random = None, # or int
#                                        sel_slice = None, # or int
#                                        )
        
# if case == 'bw_wells':
#     # Prepare backward particle tracking from synthetic boreoles across the catchment
#     bore = imageio.imread(BV.geographic.watershed_box_buff_dem)
#     bore = bore*0
#     xbore,ybore = BV.geographic.crs_to_iloc(x_crs = 214594.2, 
#                                             y_crs = 6758954.1, 
#                                             crs_proj = 'EPSG:2154')
#     bore[ybore,xbore] = 1
#     # bore[20,20] = 1
#     # bore[40,48] = 1
#     # bore[38,22] = 1
#     # bore[28,21] = 1
#     particles_folder = os.path.join(BV.simulations_folder + '/' + model_name, '_postprocess', '_particles')
#     toolbox.create_folder(particles_folder)
#     toolbox.export_tif(BV.geographic.watershed_box_buff_dem,
#                    bore,
#                    BV.geographic.simulations_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'synthetic_boreholes.tif',
#                    0)
#     tif_bore = BV.geographic.simulations_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'synthetic_boreholes.tif'
    
#     BV.settings.update_input_particles(zone_partic = tif_bore,
#                                        cell_div = 1, # 1
#                                        zloc_div = True,  # or True, add cells at cell bottom
#                                        bore_depth = True, # '[0,5,10] for 3 particles or None
#                                        track_dir = 'backward',
#                                        sel_random = None, # or int
#                                        sel_slice = None, # or int
#                                        )

# if case == 'fw_recharge':     
#     tif_recharge = BV.geographic.watershed_box_buff_dem
#     tif_recharge_clip = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/recharge_area.tif'
#     wbt.clip_raster_to_polygon(
#         tif_recharge, 
#         BV.stable_folder + '/geographic/watershed.shp', 
#         tif_recharge_clip, 
#         maintain_dimensions=True)
    
#     BV.settings.update_input_particles(zone_partic = tif_recharge,
#                                        cell_div = 1, # 1
#                                        zloc_div = False,  # or True, add cells at cell bottom
#                                        bore_depth = None, # '[0,5,10] for 3 particles or None
#                                        track_dir = 'forward',
#                                        sel_random = None, # or int
#                                        sel_slice = None, # or int
#                                        )

# if sim_state == 'steady':
#     if success_modflow == True:
#         model_modpath = BV.preprocessing_modpath(model_modflow)
#         success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
#     # if success_modpath == True:
#     #     BV.postprocessing_modpath(model_modpath,
#     #                               ending_point=True,
#     #                               starting_point=True,
#     #                               pathlines_shp=True,
#     #                               particles_shp=False,
#     #                               random_id=None, # select randomly to save (for pathlines and particles)
#     #                               ) # None
        
#         # BV.filtprocessing_modpath(model_modpath,
#         #                           norm_flux=True, # for forward only
#         #                           filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
#         #                           filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
#         #                           filt_inout=True, # delete particles in and out in the same cell (first layer)
#         #                           calc_rtd=True, # compute residence time distribution
#         #                           random_id=None, # select randomly to keep
#         #                           ) # None


#%% MODULE: RESIDENCE TIMES DISTRIBUTIONS


# # BV.rtd_modpath(model_modpath,
# #                norm_flux=True, # for forward only
# #                filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
# #                filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
# #                filt_inout=True, # delete particles in and out in the same cell (first layer)
# #                calc_rtd=True, # compute residence time distribution
# #                random_id=None, # select randomly to keep
# #                ) # None

# residence_times = residencetimes.Residencetimes()
# residence_times.load_modpath_results(BV.geographic,
#                                      model_modflow,
#                                      model_modpath
#                                      )

#%% MODULE: GROUNDWATER SURFACE OUTFLOW
# Stream formation and delimitation from GW surface outflow
stream = streams.Streams()
stream.from_gw_discharge(BV.geographic,
                         simulations_folder+'default/'+'_postprocess/'+'_rasters/'+'outflow_drain_t(0).tif',
                          # extraction_method='from_cumulated_discharge',
                          # threshold=75,
                         extraction_method='from_upstream_cells_count',
                         threshold=15,
                         clip_watershed_option=True
                         )

stream.split_network(clip_watershed_option=True)

#%% MODULE: RADON GROUNDWATER REACTIVE TRANSPORT

# radongw = radon_groundwater.Radon_groundwater()
# radongw.preprocessing(rtd=residence_times,
#                       ceq=57000, # Equilibrium concentration with rock matrix
#                       c0=0)  # Injection concentration at the surface
# radongw.processing()

#%% MODULE: RADON SURFACE WATER REACTIVE TRANSPORT

# radonst = radon_stream.Radon_stream()
# radonst.preprocessing(streams=stream,
#                       rn_gw=radongw,
#                       geographic=BV.geographic,
#                       gerate=150,   # 37, 93, 419 air-water exchange rate in d-1
#                       vstream=17280) # Stream flow rate in m/d-1: 12m/min
# radonst.processing()

#%% RADON GROUNDWATER REACTIVE TRANSPORT PLOT

# try:
#     line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
# except:
#     pass

# dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
# dem_data = dem_rio.read(1)

# dem_clip = BV.geographic.dem_clip

# # gets outflow concentrations
# zmap_min = np.full(np.shape(dem_rio),-9999)
# zmap_max = np.full(np.shape(dem_rio),9999)

# conc_df = radongw.get_concentrations_from_zlayers(conc_pos='ending',zmap_min=zmap_min,zmap_max=zmap_max)

# res = np.zeros(np.shape(dem_rio))
# res = np.ma.masked_where(dem_data < 0, res)

# res[conc_df['i'].to_numpy(),conc_df['j'].to_numpy()] = conc_df['mean'].to_numpy()
# res = np.ma.masked_where(res <= 0, res)

# res = np.ma.masked_where(dem_clip <= 0, res)

# npart = np.zeros(np.shape(dem_rio))
# npart = np.ma.masked_where(dem_data < 0, npart)

# npart[conc_df['i'].to_numpy(),conc_df['j'].to_numpy()] = conc_df['npart'].to_numpy()
# npart = np.ma.masked_where(npart <= 0, npart)
# res = np.ma.masked_where(npart <= 5, res)


# fig, ax = plt.subplots(1,1, figsize=(7,5))

# retted = rasterio.plot.show(res, ax=ax, transform=dem_rio.transform, 
#                             cmap='jet')

# im = retted.get_images()[0]
# fig.colorbar(im, ax=ax)
# ax.set_title('GW outflow Rn concentration [Bq/m$^3$]')
# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax, color='k', lw=2, zorder=4)

#%% RADON SURFACE WATER REACTIVE TRANSPORT PLOT

# try:
#     line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
# except:
#     pass

# dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
# dem_data = dem_rio.read(1)

# dem_clip = BV.geographic.dem_clip

# res = radonst.conc_rast

# res = np.ma.masked_where(dem_data < 0, res)


# res = np.ma.masked_where(res <= 0, res)
# res = np.ma.masked_where(dem_clip <= 0, res)

# fig, ax = plt.subplots(1,1, figsize=(7,5))

# retted = rasterio.plot.show(res, ax=ax, transform=dem_rio.transform, 
#                             cmap='jet')

# im = retted.get_images()[0]
# fig.colorbar(im, ax=ax)
# ax.set_title('Stream Rn concentration [Bq/m$^3$]')
# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax, color='k', lw=2, zorder=4)


# # Long profiles

# long_profiles = stream.long_profiles(stream.cumulated_discharge(BV.geographic,
#                                                                 simulations_folder+'default/'+'_postprocess/'+'_rasters/'+'outflow_drain_t(0).tif',
#                                                                 clip_watershed_option=True))

# try:
#     line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
# except:
#     pass

# dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
# dem_data = dem_rio.read(1)

# dem_clip = BV.geographic.dem_clip

# ####
# long_profiles = stream.long_profiles(radonst.conc_rast)
# fig, ax = plt.subplots(1,1, figsize=(7,5))
# for i in list(range(len(long_profiles))):
#     data = long_profiles[i]
#     plt.plot(data[:,0], data[:,1])

# plt.xlabel('Distance from stream outlet [m]')
# plt.ylabel('Stream Rn concentration [Bq/m$^3$]')
# plt.show
###
# Stream location map
try:
    line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
except:
    pass

dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
dem_data = dem_rio.read(1)

dem_clip = BV.geographic.dem_clip

res = stream.all_streams_rast[2]

res = np.ma.masked_where(dem_data < 0, res)


res = np.ma.masked_where(res <= 0, res)
res = np.ma.masked_where(dem_clip <= 0, res)

fig, ax = plt.subplots(1,1, figsize=(7,5))

retted = rasterio.plot.show(res, ax=ax, transform=dem_rio.transform, 
                            cmap='jet')

im = retted.get_images()[0]
fig.colorbar(im, ax=ax)
ax.set_title('Stream location')
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
fig.tight_layout()

line.plot(ax=ax, color='k', lw=2, zorder=4)

# # 'Calibration' of air-water exchange rate
# radonst1 = radon_stream.Radon_stream()
# radonst1.preprocessing(streams=stream,
#                       rn_gw=radongw,
#                       geographic=BV.geographic,
#                       gerate=37,   # 37, 93, 419 air-water exchange rate in d-1
#                       vstream=17280) # Stream flow rate in m/d-1: 12m/min
# radonst1.processing()

# radonst2 = radon_stream.Radon_stream()
# radonst2.preprocessing(streams=stream,
#                       rn_gw=radongw,
#                       geographic=BV.geographic,
#                       gerate=419,   # 37, 93, 419 air-water exchange rate in d-1
#                       vstream=17280) # Stream flow rate in m/d-1: 12m/min
# radonst2.processing()

# radonst3 = radon_stream.Radon_stream()
# radonst3.preprocessing(streams=stream,
#                       rn_gw=radongw,
#                       geographic=BV.geographic,
#                       gerate=150,   # 37, 93, 419 air-water exchange rate in d-1
#                       vstream=17280) # Stream flow rate in m/d-1: 12m/min
# radonst3.processing()



# long_profiles1 = stream.long_profiles(radonst1.conc_rast)
# long_profiles2 = stream.long_profiles(radonst2.conc_rast)
# long_profiles3 = stream.long_profiles(radonst3.conc_rast)

# fig, ax = plt.subplots(1,1, figsize=(7,5))

# plt.plot(long_profiles1[2][:,0], long_profiles1[2][:,1],'b')
# plt.plot(long_profiles2[2][:,0], long_profiles2[2][:,1],'b')

# plt.plot(long_profiles3[2][:,0], long_profiles3[2][:,1],'r')

# # Data points
# x  = (500,1300,2250,2550)
# y  = (1600,1100,15500,25000)
# sd = (1400,800,9500,15000)

# # for i in list(range(len(x))):
# plt.errorbar(x, y, yerr=sd,fmt='.g')  


# plt.xlabel('Distance from stream outlet [m]')
# plt.ylabel('Stream Rn concentration [Bq/m$^3$]')
# plt.show

#%% RESIDENCE TIMES DISTRIBUTIONS
# rtd_df = residence_times.get_pathlines()
# particles = residence_times.get_particles(particle_pos='center',zero_based=True)

# residence_times.particles_to_csv()

# rtd = residence_times.get_rtd_all_cells()

# #%% RESIDENCE TIMES MAP
# shp_pathlines = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/pathlines_weighted.shp')
# # shp_endpoints = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/starting_weighted.shp')

# #TB: Note: there is no indication of transit times along each pathline in the
# #shp file; only end point, for one color for each line
# shp_pathlines2 = gpd.GeoDataFrame(residence_times.get_pathlines(), geometry="coordinates")
# shp_pathlines2['timemax'] = shp_pathlines2['timemax'] / 365

# # shp_pathlines2 = shp_pathlines2[shp_pathlines2['timemax'] > 1]

# try:
#     line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
# except:
#     pass

# dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
# dem_data = dem_rio.read(1)
# dem_data = np.ma.masked_where(dem_data < 0, dem_data)

# fig, ax = plt.subplots(1,1, figsize=(7,5))

# rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform, 
#                     cmap='Greys', alpha=0.7, zorder=-10)

# # shp_pathlines2.plot(ax=ax, column='timemax', cmap='jet', lw=0.5,
# #                     vmax=5*np.mean(shp_pathlines2['timemax']),
# #                     legend=True,
# #                     zorder=1)

# shp_pathlines2.plot(ax=ax, column='timemax', cmap='jet', lw=0.5,
#                     vmax=5,
#                     legend=True,
#                     zorder=1)

# # shp_pathlines.plot(ax=ax, column='time_win_y', cmap='jet', lw=0.5,
# #                     norm=mpl.colors.LogNorm(vmin=1, vmax=1000),
# #                     # legend=True,
# #                     zorder=1)

# # shp_endpoints.plot(ax=ax, column='time_win_y', cmap='jet', lw=0, markersize=10,
# #                     # norm=mpl.colors.LogNorm(vmin=0.1, vmax=1000),
# #                     legend=True,
# #                     zorder=2)

# try:
#     line.plot(ax=ax, color='k', lw=2, zorder=-1)
# except:
#     pass

# ax.set_title('Particle transit times [y]')

# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)  

# fig.tight_layout()

# fig, ax = plt.subplots(1,1, figsize=(7,5))
# shp_pathlines2['timemax'][shp_pathlines2['timemax']>5*np.mean(shp_pathlines2['timemax'])]=np.nan
# plt.hist(shp_pathlines2['timemax'],bins=40)
# plt.xlabel('Transit time [years]')
# plt.ylabel('Number of particles')
# plt.show()

# # fig.savefig(os.path.join(simulations_folder, model_name,
# #                             '_postprocess', '_figures', 'RTD_'+model_name+'.png'))


#%% GROUNDWATER SURFACE OUTFLOW PLOT

long_profiles = stream.long_profiles(stream.cumulated_discharge(BV.geographic,
                                                                simulations_folder+'default/'+'_postprocess/'+'_rasters/'+'outflow_drain_t(0).tif',
                                                                clip_watershed_option=True))
try:
    line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
except:
    pass

dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
dem_data = dem_rio.read(1)

dem_clip = BV.geographic.dem_clip

river_data = stream.stream_rast
# river_data = stream.tributaries
# river_data = stream.cumulated_discharge(BV.geographic,
#                                         simulations_folder+'default/'+'_postprocess/'+'_rasters/'+'outflow_drain_t(0).tif',
#                                         clip_watershed_option=True)

river_data = np.ma.masked_where(river_data < 0, river_data)
river_data = np.ma.masked_where(dem_clip <= 0, river_data)

fig, ax = plt.subplots(1,1, figsize=(7,5))

retted = rasterio.plot.show(river_data, ax=ax, transform=dem_rio.transform, 
                            cmap='jet')

im = retted.get_images()[0]
fig.colorbar(im, ax=ax)
ax.set_title('Stream position')
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
fig.tight_layout()


fig, ax = plt.subplots(1,1, figsize=(7,5))
for i in list(range(len(long_profiles))):
    data = long_profiles[i]
    plt.plot(data[:,0], data[:,1])
# data = long_profiles[3]
# plt.plot(data[:,0], data[:,1])
plt.xlabel('Distance from stream outlet [m]')
plt.ylabel('Stream flow rate [m$^3$/d]')
plt.show

# stream.export_as_raster(simulations_folder+'default/'+'_postprocess/'+'_rasters/'+'river_test.tif')
# stream.export_as_vector(simulations_folder+'default/'+'_postprocess/'+'_rasters/'+'river_test_vec.shp')

# try:
#     line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
# except:
#     pass

# dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
# dem_data = dem_rio.read(1)

# dem_clip = BV.geographic.dem_clip

# # gets vertical average of RTDs
# zmap_min = np.full(np.shape(dem_rio),-9999)
# zmap_max = np.full(np.shape(dem_rio),9999)

# # Out particles
# rtd_df = residence_times.get_particles_from_zlayers(particle_pos='ending',zmap_min=zmap_min,zmap_max=zmap_max)

# res_time = np.zeros(np.shape(dem_rio))
# res_time = np.ma.masked_where(dem_data < 0, res_time)

# res_time[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['mean'].to_numpy() / 365
# res_time = np.ma.masked_where(res_time <= 0, res_time)

# res_time = np.ma.masked_where(dem_clip <= 0, res_time)

# npart = np.zeros(np.shape(dem_rio))
# npart = np.ma.masked_where(dem_data < 0, npart)

# npart[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['npart'].to_numpy()
# npart = np.ma.masked_where(npart <= 0, npart)
# res_time = np.ma.masked_where(npart <= 5, res_time)

# long_profiles = stream.long_profiles(res_time)

# fig, ax = plt.subplots(1,1, figsize=(7,5))
# for i in list(range(len(long_profiles))):
#     data = long_profiles[i]
#     plt.plot(data[:,0], data[:,1])
# # data = long_profiles[3]
# # plt.plot(data[:,0], data[:,1])
# plt.xlabel('Distance from stream outlet [m]')
# plt.ylabel('Mean outflow residence time [y]')
# plt.show



#%% RESIDENCE TIMES DISTRIBUTIONS PLOT

# try:
#     line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
# except:
#     pass

# dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
# dem_data = dem_rio.read(1)

# dem_clip = BV.geographic.dem_clip

# ismap=[]
# N=6

# C = int(np.sqrt(N))
# R = int(N/C)+1
# fig, ax = plt.subplots(3,2, figsize=(5*C,R*(5*dem_rio.height/dem_rio.width)),dpi=300)

# ax = ax.flat
# for axi in ax[N:]:
#     axi.remove()
# ax = ax[:N]


# # gets vertical average of RTDs
# zmap_min = np.full(np.shape(dem_rio),-9999)
# zmap_max = np.full(np.shape(dem_rio),9999)

# rtd_df = residence_times.get_particles_from_zlayers(zmap_min=zmap_min,zmap_max=zmap_max)
# # rtd_df = residence_times.get_particles_from_zlayers(zmap_min=zmap_min,zmap_max=dem_data-10)

# res_time = np.zeros(np.shape(dem_rio))
# res_time = np.ma.masked_where(dem_data < 0, res_time)

# res_time[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['mean'].to_numpy() / 365
# res_time = np.ma.masked_where(res_time <= 0, res_time)

# res_time = np.ma.masked_where(dem_clip <= 0, res_time)

# npart = np.zeros(np.shape(dem_rio))
# npart = np.ma.masked_where(dem_data < 0, npart)

# npart[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['npart'].to_numpy()
# npart = np.ma.masked_where(npart <= 0, npart)
# npart = np.ma.masked_where(dem_clip <= 0, npart)

# res_time = np.ma.masked_where(npart <= 0, res_time)

# ismap.append(True)
# ii=0

# retted = rasterio.plot.show(res_time, ax=ax[ii], transform=dem_rio.transform, 
#                             cmap='jet')
# image=[]
# im = retted.get_images()[0]
# image.append(im)

# ax[ii].set_title('Vertical mean residence time [y]')
# ax[ii].get_xaxis().set_visible(False)
# ax[ii].get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax[ii], color='k', lw=2, zorder=4)

# # Histogram vertcal mean RT
# ii=ii+1
# ismap.append(False)
# npart = np.full(np.shape(dem_rio),1)
# npart = np.sum(npart)
# res_time = np.reshape(res_time,(npart,1))
# ax[ii].hist(res_time)
# ax[ii].set_xlabel('Vertical mean residence time [y]')
# ax[ii].set_ylabel('Number of cells')
# fig.tight_layout()

# # Out particles
# rtd_df = residence_times.get_particles_from_zlayers(particle_pos='ending',zmap_min=zmap_min,zmap_max=zmap_max)

# res_time = np.zeros(np.shape(dem_rio))
# res_time = np.ma.masked_where(dem_data < 0, res_time)

# res_time[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['mean'].to_numpy() / 365
# res_time = np.ma.masked_where(res_time <= 0, res_time)

# res_time = np.ma.masked_where(dem_clip <= 0, res_time)

# npart = np.zeros(np.shape(dem_rio))
# npart = np.ma.masked_where(dem_data < 0, npart)

# npart[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['npart'].to_numpy()
# npart = np.ma.masked_where(npart <= 0, npart)
# res_time = np.ma.masked_where(npart <= 5, res_time)

# ii=ii+1
# ismap.append(True)

# retted = rasterio.plot.show(res_time, ax=ax[ii], transform=dem_rio.transform, 
#                             cmap='jet')

# im = retted.get_images()[0]
# image.append(im)

# ax[ii].set_title('Outflow mean residence times [y]')
# ax[ii].get_xaxis().set_visible(False)
# ax[ii].get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax[ii], color='k', lw=2, zorder=4)

# # Histogram out particles
# ii=ii+1
# ismap.append(False)

# npart = np.full(np.shape(dem_rio),1)
# npart = np.sum(npart)
# res_time = np.reshape(res_time,(npart,1))
# ax[ii].hist(res_time)
# ax[ii].set_xlabel('Outflow mean residence time [y]')
# ax[ii].set_ylabel('Number of cells')

# # Drain seepage
# drain_file = os.path.join(BV.simulations_folder, model_name,'_postprocess','outflow_drain.npy')
# drain_area = np.load(drain_file, allow_pickle=True).item()
# drain_area = drain_area[0]

# drain = np.ma.masked_where(dem_data<= 0, drain_area)
# drain = np.ma.masked_where(drain<= 0, drain)

# drain = np.ma.masked_where(dem_clip <= 0, drain)

# ii=ii+1
# ismap.append(True)

# retted = rasterio.plot.show(drain, ax=ax[ii], transform=dem_rio.transform, 
#                             cmap='jet')
# im = retted.get_images()[0]
# image.append(im)

# ax[ii].set_title('Seepage outflow [m$^3$/d]')
# ax[ii].get_xaxis().set_visible(False)
# ax[ii].get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax[ii], color='k', lw=2, zorder=4)


# # Age vs seepage flow rate
# ii=ii+1
# ismap.append(False)
# drain = np.reshape(drain,(npart,1))
# res_time = np.reshape(res_time,(npart,1))

# ax[ii].plot(drain, res_time,'.')
# ax[ii].set_xlabel('Seepage outflow [m$^3$/d]')
# ax[ii].set_ylabel('Mean residence time [y]')


# fig.set_figheight(15)
# fig.set_figwidth(12)
# fig.tight_layout(pad=2.0)


# compt=0
# k=0
# for axi in ax:
#     if ismap[k]:
#         bounds = dem_rio.bounds
#         xlim = ([bounds[0], bounds[2]])
#         ylim = ([bounds[1], bounds[3]])
#         axi.set_xlim(xlim)
#         axi.set_ylim(ylim)
#         scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower right')
#         axi.add_artist(scalebar)
#         axi.get_xaxis().set_visible(False)
#         axi.get_yaxis().set_visible(False)
    
#         divider = make_axes_locatable(axi)
#         cax = divider.append_axes(size="4%",position='right', pad=0.05)
#         fig.add_axes(cax)
#         cbar = fig.colorbar(image[compt], cax=cax, orientation="vertical")
#         cbar.ax.get_ymajorticklabels()
#         list(cbar.get_ticks())
#         cbar.ax.tick_params(labelsize=10)
#         cbar.ax.yaxis.set_ticks_position('right')
#         cbar.ax.tick_params(size=2)
    
#         axi.legend(loc='best',framealpha=0.8)
#         compt +=1
#     k=k+1


# modelfolder = os.path.join(BV.simulations_folder, model_name)
# fig.savefig(os.path.join(modelfolder,'_postprocess','_figures', '2D_' + 'residence_times'+'.png'), dpi=300, 
#             bbox_inches='tight', transparent=False)



#%% RESIDENCE TIMES DISTRIBUTIONS PLOT

# try:
#     line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
# except:
#     pass

# dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
# dem_data = dem_rio.read(1)

# dem_clip = BV.geographic.dem_clip


# # gets vertical average of RTDs
# zmap_min = np.full(np.shape(dem_rio),-9999)
# zmap_max = np.full(np.shape(dem_rio),9999)

# # rtd_df = residence_times.get_particles_from_zlayers(zmap_min=zmap_min,zmap_max=zmap_max)
# rtd_df = residence_times.get_particles_from_zlayers(zmap_min=zmap_min,zmap_max=dem_data-10)

# res_time = np.zeros(np.shape(dem_rio))
# res_time = np.ma.masked_where(dem_data < 0, res_time)

# res_time[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['mean'].to_numpy() / 365
# res_time = np.ma.masked_where(res_time <= 0, res_time)

# res_time = np.ma.masked_where(dem_clip <= 0, res_time)

# npart = np.zeros(np.shape(dem_rio))
# npart = np.ma.masked_where(dem_data < 0, npart)

# npart[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['npart'].to_numpy()
# npart = np.ma.masked_where(npart <= 0, npart)
# npart = np.ma.masked_where(dem_clip <= 0, npart)

# res_time = np.ma.masked_where(npart <= 5, res_time)

# # Plot
# fig, ax = plt.subplots(1,1, figsize=(7,5))
# retted = rasterio.plot.show(res_time, ax=ax, transform=dem_rio.transform, 
#                             cmap='jet')
# im = retted.get_images()[0]
# fig.colorbar(im, ax=ax)
# ax.set_title('Vertical mean residence time [y]')
# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax, color='k', lw=2, zorder=4)



# # Fraction of old water > 21d

# rtd_df = residence_times.get_particles_from_zlayers(particle_pos='ending',zmap_min=zmap_min,zmap_max=zmap_max)

# def myfunc(vec):
#   return sum(num >= 13 for num in vec) / len(vec)

# rtd_df['fraction_old'] = list(map(myfunc, rtd_df['all_times']))

# res_time = np.zeros(np.shape(dem_rio))
# res_time = np.ma.masked_where(dem_data < 0, res_time)

# res_time[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['fraction_old'].to_numpy()
# res_time = np.ma.masked_where(res_time <= 0, res_time)

# res_time = np.ma.masked_where(dem_clip <= 0, res_time)

# npart = np.zeros(np.shape(dem_rio))
# npart = np.ma.masked_where(dem_data < 0, npart)

# npart[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['npart'].to_numpy()
# npart = np.ma.masked_where(npart <= 0, npart)
# npart = np.ma.masked_where(dem_clip <= 0, npart)

# res_time = np.ma.masked_where(npart <= 5, res_time)

# # Plot
# fig, ax = plt.subplots(1,1, figsize=(7,5))
# retted = rasterio.plot.show(res_time, ax=ax, transform=dem_rio.transform, 
#                             cmap='jet')
# im = retted.get_images()[0]
# fig.colorbar(im, ax=ax)
# ax.set_title('Fraction of water older than 13 days')
# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax, color='k', lw=2, zorder=4)



# # # Histogram
# # ii=ii+1
# # ismap.append(False)
# # npart = np.full(np.shape(dem_rio),1)
# # npart = np.sum(npart)
# # res_time = np.reshape(res_time,(npart,1))
# # ax[ii].hist(res_time)
# # ax[ii].set_xlabel('Vertical mean residence time [y]')
# # ax[ii].set_ylabel('Number of cells')
# # fig.tight_layout()

# # # fig, ax = plt.subplots(1, 1, figsize=(8,8))
# # # plt.plot(drain, res_time*12,'.')
# # # plt.xlabel('Seepage outflow [m$^3$/d]')
# # # plt.ylabel('Mean residence time [months]')
# # # plt.show()

# # # fig, ax = plt.subplots(1,1, figsize=(7,5))


# # # ax[ii].show()

# # # ii=ii+1

# # # retted = rasterio.plot.show(npart, ax=ax[ii], transform=dem_rio.transform, 
# # #                             cmap='jet')

# # # im = retted.get_images()[0]
# # # fig.colorbar(im, ax=ax[ii])
# # # ax[ii].set_title('nparticles (vertical mean RT)')
# # # ax[ii].get_xaxis().set_visible(False)
# # # ax[ii].get_yaxis().set_visible(False)
# # # fig.tight_layout()

# # # line.plot(ax=ax[ii], color='k', lw=2, zorder=4) 

# # Out particles
# rtd_df = residence_times.get_particles_from_zlayers(particle_pos='ending',zmap_min=zmap_min,zmap_max=zmap_max)

# res_time = np.zeros(np.shape(dem_rio))
# res_time = np.ma.masked_where(dem_data < 0, res_time)

# res_time[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['mean'].to_numpy() / 365
# res_time = np.ma.masked_where(res_time <= 0, res_time)

# res_time = np.ma.masked_where(dem_clip <= 0, res_time)

# npart = np.zeros(np.shape(dem_rio))
# npart = np.ma.masked_where(dem_data < 0, npart)

# npart[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['npart'].to_numpy()
# npart = np.ma.masked_where(npart <= 0, npart)
# res_time = np.ma.masked_where(npart <= 5, res_time)

# drain_file = os.path.join(BV.simulations_folder, model_name,'_postprocess','outflow_drain.npy')
# drain_area = np.load(drain_file, allow_pickle=True).item()
# drain_area = drain_area[0]

# drain = np.ma.masked_where(dem_data<= 0, drain_area)
# drain = np.ma.masked_where(drain<= 0, drain)

# drain = np.ma.masked_where(dem_clip <= 0, drain)

# cutoff=0.6/30

# res_time_ma = np.ma.masked_where(res_time > cutoff*drain, res_time)
# drain_ma = np.ma.masked_where(res_time > cutoff*drain, drain)


# fig, ax = plt.subplots(1,1, figsize=(7,5))

# retted = rasterio.plot.show(res_time_ma, ax=ax, transform=dem_rio.transform, 
#                             cmap='jet')

# im = retted.get_images()[0]
# fig.colorbar(im, ax=ax)
# ax.set_title('Outflow residence time [y]')
# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax, color='k', lw=2, zorder=4)



# fig, ax = plt.subplots(1,1, figsize=(7,5))

# retted = rasterio.plot.show(drain_ma, ax=ax, transform=dem_rio.transform, 
#                             cmap='jet')

# im = retted.get_images()[0]
# fig.colorbar(im, ax=ax)
# ax.set_title('Seepage outflow [m$^3$/d]')
# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)
# fig.tight_layout()

# line.plot(ax=ax, color='k', lw=2, zorder=4)






# # Age vs seepage flow rate

# # res_time = np.ma.masked_where(BV.geographic.dem_clip <= 0, res_time)
# # drain = np.ma.masked_where(res_time<= 0, drain)

# N = np.full(np.shape(dem_rio),1)
# N = np.sum(N)
# drain = np.reshape(drain,(N,1))
# res_time = np.reshape(res_time,(N,1))

# drain_ma = np.reshape(drain,(N,1))
# res_time_ma = np.reshape(res_time,(N,1))

# fig, ax = plt.subplots(1, 1, figsize=(8,8))
# ax.plot(drain_ma, res_time_ma,'.')
# ax.set_xlabel('Seepage outflow [m$^3$/d]')
# ax.set_ylabel('Mean residence time [y]')


# # fig.set_figheight(15)
# # fig.set_figwidth(12)
# # fig.tight_layout(pad=2.0)


# # compt=0
# # k=0
# # for axi in ax:
# #     if ismap[k]:
# #         bounds = dem_rio.bounds
# #         xlim = ([bounds[0], bounds[2]])
# #         ylim = ([bounds[1], bounds[3]])
# #         axi.set_xlim(xlim)
# #         axi.set_ylim(ylim)
# #         scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower right')
# #         axi.add_artist(scalebar)
# #         axi.get_xaxis().set_visible(False)
# #         axi.get_yaxis().set_visible(False)
    
# #         divider = make_axes_locatable(axi)
# #         cax = divider.append_axes(size="4%",position='right', pad=0.05)
# #         fig.add_axes(cax)
# #         cbar = fig.colorbar(image[compt], cax=cax, orientation="vertical")
# #         cbar.ax.get_ymajorticklabels()
# #         list(cbar.get_ticks())
# #         cbar.ax.tick_params(labelsize=10)
# #         cbar.ax.yaxis.set_ticks_position('right')
# #         cbar.ax.tick_params(size=2)
    
# #         axi.legend(loc='best',framealpha=0.8)
# #         compt +=1
# #     k=k+1


# # modelfolder = os.path.join(BV.simulations_folder, model_name)
# # fig.savefig(os.path.join(modelfolder,'_postprocess','_figures', '2D_' + 'residence_times'+'.png'), dpi=300, 
# #             bbox_inches='tight', transparent=False)


# # # Age vs seepage flow rate

# # res_time = np.ma.masked_where(BV.geographic.dem_clip <= 0, res_time)
# # drain = np.ma.masked_where(res_time<= 0, drain)

# # N = np.full(np.shape(dem_rio),1)
# # N = np.sum(N)
# # drain = np.reshape(drain,(N,1))
# # res_time = np.reshape(res_time,(N,1))

# # drain_ma = np.reshape(drain_ma,(N,1))
# # res_time_ma = np.reshape(res_time_ma,(N,1))

# # fig, ax = plt.subplots(1, 1, figsize=(8,8))
# # plt.plot(drain, res_time*12,'.')
# # plt.xlabel('Seepage outflow [m$^3$/d]')
# # plt.ylabel('Mean residence time [months]')
# # plt.show()

# # fig, ax = plt.subplots(1,1, figsize=(7,5))

# # plt.hist(res_time)
# # plt.show()


# # rtd_df = residence_times.get_rtd_from_zlayers(zmap_min=zmap_min,zmap_max=zmap_max)

# # res_time = np.zeros(np.shape(dem_rio))
# # res_time = np.ma.masked_where(dem_data < 0, res_time)

# # res_time[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['mean'].to_numpy() / 365
# # res_time = np.ma.masked_where(res_time <= 0, res_time)

# # res_time = np.ma.masked_where(dem_clip <= 0, res_time)

# # npart = np.zeros(np.shape(dem_rio))
# # npart = np.ma.masked_where(dem_data < 0, npart)

# # npart[rtd_df['i'].to_numpy(),rtd_df['j'].to_numpy()] = rtd_df['npart'].to_numpy()
# # npart = np.ma.masked_where(npart <= 0, npart)
# # npart = np.ma.masked_where(dem_clip <= 0, npart)

# # res_time = np.ma.masked_where(npart <= 5, res_time)

# # res_time = np.reshape(res_time,(N,1))

# # fig, ax = plt.subplots(1,1, figsize=(7,5))

# # plt.hist(res_time)
# # plt.show()


#%% TIMESERIES

# timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
#                                                   model_modpath=model_modpath,
#                                                   datetime_format=False, 
                                                  # subbasin_results=True) # or None

#%% ---- PLOT

#%% 2D

# # if sim_state == 'steady':
# visu = visualization_results.Visualization(BV, model_name)
# visu.visual2D(object_list = ['map','grid',
#                               'watertable', 'watertable_depth',
#                               'drain_flow','surface_flow',
#                               'pathlines', 'residence_times'
#                               ],
#               color_scale = [(None,None),(None,None),
#                               (None,None),(0,10),
#                               (None,None),(None,None),
#                               (0,100),(None,None),
#                               ], 
#               lines=500)

# if sim_state == 'steady':
visu = visualization_results.Visualization(BV, model_name)
visu.visual2D(object_list = ['map','grid',
                              'watertable', 'watertable_depth',
                              'drain_flow','surface_flow'
                              ],
              color_scale = [(None,None),(None,None),
                              (None,None),(0,10),
                              (None,None),(None,None),
                              ], 
              lines=500)

#%% SEEPAGE MAP

# lead_numb = '0'
# outflow = imageio.imread(simulations_folder+model_name+'/_postprocess/_rasters/accumulation_flux_t(0).tif')
# demData = imageio.imread(BV.geographic.watershed_dem)
# demData = np.ma.masked_array(demData, mask=demData<0)
# res = BV.geographic.resolution

# msk_outflow = (outflow<0)
# outflow = np.ma.masked_array(outflow, mask=msk_outflow)
# outflow = ( np.ma.masked_where(outflow==0, outflow) / (res**2) )
# outflow = outflow * 1000 * 365 # mm/year
# outflow = np.log10(outflow)

# from matplotlib.colors import LightSource
# ls = LightSource(azdeg=45, altdeg=45)
# cmap = plt.cm.Greys
# rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=res, dy=res)

# fig, ax = plt.subplots(1, 1, figsize=(8,8))
# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)
# im = ax.imshow(demData, alpha=0.8, cmap=cmap)
# im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
# cf=ax.imshow(outflow, cmap='YlGnBu', alpha=1, vmin=outflow.min(), vmax=outflow.max())
# ax.set_title('Seepage outflow (quick view)')

# name_fig = 'map_discharge_' + str(lead_numb) + '.png'
# plt.tight_layout()

# # fig.savefig(os.path.join(simulations_folder, model_name,
# #                             '_postprocess', '_figures', 'RAW_'+model_name+'.png'))



#%% ---- NOTES

os.chdir(root_dir)

# wbt.geomorphons(
#     'xxx/watershed_box_buff_dem.tif', 
#     'xxx/watershed_box_geomorphons.tif', 
#     search=5, # in cell
#     threshold=0, # angle in degree
#     fdist=0, # in cell  
#     skip=0, # in cell
#     forms=True, 
#     residuals=False, 
# )


