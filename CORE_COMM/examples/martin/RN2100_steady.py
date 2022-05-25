# -*- coding: utf-8 -*-
"""
Created on Fri May 20 10:55:31 2022

@author: Martin
"""

#%% LIBRARIES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
# from osgeo import gdal, osr
# import matplotlib.pyplot as plt

# Gis
# import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                 
# HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display
from tools import toolbox, vtk
# from groundwater_flow import visualization, modflow_display
from calibration import calib_root

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

import os
dir(os.getcwd())

# %% PATHS + watershed options

watershed_name = 'Caen'
# Caen Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
load = False # loads previously generated basin if true

# # Path to the git repositoty home page
git_path = "C:/Users/Martin/Desktop/Travail/HydroModPy/HydroModPy/CORE_COMM/"
# # Path to the data folder
data_path = "C:/Users/Martin/Desktop/Travail/data/data_test_ronan/"
# # Path where the results will be stored
out_path = 'C:/Users/Martin/Desktop/Travail/HydroModPy/output2/'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

dems_path = data_path # reginal DEM or conceptual DEM
# shp_path = data_path + 'shp/' # if you want run a model from a shapefile
modflow_path = 'C:/Users/Martin/Desktop/Travail/HydroModPy/TEST/modflow/' # add bin/ folder with necessary .exe

surfex_path =  data_path # add surfex models in .h5 format (France scale, else, specify None)
# geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = data_path + 'OCEAN/' # add specific sea level files
hydrology_path = data_path + 'hydro/' # add hydrographic shapefiles
# hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
# intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

library_path = git_path + 'watershed/watershed_library.csv' # each row is a study site with outlet coordinates

dem_name = "BDALTI_norm-manch_75m.tif"
dem_path = dems_path + dem_name

shp_file = "C:/Users/Martin/Desktop/Travail/SIG/Couches_base/Administratif/region_normandie/normandie.shp" # None # specify a path if process start from a given shapefile

sp_file = 'C:/Users/Martin/Desktop/Travail/SIG/BV_RN2100/Caen/watershed_clip_caen_2.shp'
cell_size = None # specify new resolution from a given DEM or None

#%% GENERATING WATERSHED + data
# We propose 4 tests :
    # 1 - From a outlet coordinates : 'Outlet'
    # 2 - From a shpaefile : 'Shapefile'
    # 3 - From an actual DEM : 'Dem'
    # 4 - From a conceptual DEM : 'Conceptual'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=sp_file,
                              from_dem=False,
                              cell_size=cell_size)

#%%
types_obs = ['streams_fr'] # list of shapefile name layers for clip hydrology
fields_obs = ['FID'] # list of shapefile name columns to translate as a tif

# create watershed properties
BV.add_hydrodynamic()

BV.add_surfex(surfex_path) 
# BV.add_geology(geology_path) 
BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
BV.add_oceanic(oceanic_path)
# BV.add_hydrometry(hydrometry_path)
# BV.add_intermittency(intermittency_path)
if piezometry_path == True:
    BV.add_piezometry()
# if subbasin_path == True:
#     BV.add_subbasin()

# DRIAS climate data extraction
BV.add_drias("C:/Users/Martin/Desktop/Travail/data/data_test_ronan/CLIMAT/Normandie/")

# BV.save_object()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% Calibration based on streams

import glob
import os

type_obs = 'streams_fr'

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

# Init
df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
area = BV.geographic.area
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
                                  first_year = 1960, last_year=2019, time_step = 'M',
                                  sim_state = 'steady') #
BV.hydrodynamic.update_thickness(30)
# BV.hydrodynamic.update_porosity(0.1)
# BV.hydrodynamic.update_hyd_cond(2)
params_df = pd.DataFrame(columns=['params',
                                  'init_values','lower_bounds','higher_bounds',
                                  'units','scale'])
params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+01,'m/j','lin']
params_file = 'calib_dicot_hom_1v_k1'
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
calib = calib_root.Calibration(params_file, BV, observations = ['streams'])

# Launch dichotomy
dicot = calib.dichotomy(gap=1)

# Extract
typ_calib = 'streams_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)
name_file = list_path[-1].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)
test.display_objective_function(save=None)

koptim = test.calib['params_values'][-1]
kr = koptim / test.calib['recharge']
obj_func = test.calib['objective_function'][-1]

df.loc[0,type_obs] = koptim / 24 / 3600
df.loc[1,type_obs] = kr
df.loc[2,type_obs] = obj_func
    
df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

BV.piezometry.add_data()
# BV.save_object()


#%% Load BV object
    
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=True,
                              from_shp=False,
                              from_dem=False,
                              cell_size=cell_size)

BV.load_object()
print(vars(BV).keys())


#%% Historic mean recharge

# Historic recharge
sim_state = 'steady' # 'steady' or 'transient'
period = [1960, 2019] # rehcarge period
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
start = str(period[0])+'-01-01' # necessary to specify the first time_step date

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
                                      first_year = period[0], last_year = period[1], 
                                      time_step = time_step, sim_state = sim_state)

R_hist = BV.forcing.recharge
BV.forcing.update_recharge(values = R_hist, sim_state = sim_state)

#%% DRIAS recharges

first_yr = 2020
last_yr = 2050
BV.add_forcing()

#MPI-CCL
gcm = 'MPI'
rcm = 'CCL'
sce = 'RCP2.6'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_MPI_CCL_RCP26 = BV.forcing.recharge

sce = 'RCP8.5'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_MPI_CCL_RCP85 = BV.forcing.recharge


#ECE-RCA
gcm = 'ECE'
rcm = 'RCA'
sce = 'RCP2.6'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_ECE_RCA_RCP26 = BV.forcing.recharge

sce = 'RCP8.5'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_ECE_RCA_RCP85 = BV.forcing.recharge


#ECE-RAC
gcm = 'ECE'
rcm = 'RAC'
sce = 'RCP2.6'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_ECE_RAC_RCP26 = BV.forcing.recharge

sce = 'RCP8.5'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_ECE_RAC_RCP85 = BV.forcing.recharge


#CNR-RAC
gcm = 'CNR'
rcm = 'RAC'
sce = 'RCP2.6'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_CNR_RAC_RCP26 = BV.forcing.recharge

sce = 'RCP8.5'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_CNR_RAC_RCP85 = BV.forcing.recharge


#NOR-R15
gcm = 'NOR'
rcm = 'R15'
sce = 'RCP2.6'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_NOR_R15_RCP26 = BV.forcing.recharge

sce = 'RCP8.5'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_NOR_R15_RCP85 = BV.forcing.recharge


#CNR-ALA
gcm = 'CNR'
rcm = 'ALA'
sce = 'RCP2.6'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_CNR_ALA_RCP26 = BV.forcing.recharge

sce = 'RCP8.5'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_CNR_ALA_RCP85 = BV.forcing.recharge


#HAD-REG
gcm = 'HAD'
rcm = 'REG'
sce = 'RCP2.6'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_HAD_REG_RCP26 = BV.forcing.recharge

sce = 'RCP8.5'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_HAD_REG_RCP85 = BV.forcing.recharge


#MPI-R09
gcm = 'MPI'
rcm = 'R09'
sce = 'RCP2.6'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_MPI_R09_RCP26 = BV.forcing.recharge

sce = 'RCP8.5'
BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                  first_year = first_yr, last_year = last_yr,
                                  sim_state = sim_state)
R_MPI_R09_RCP85 = BV.forcing.recharge


#Mean values
import statistics
R_DRIAS_26 = statistics.mean([R_MPI_CCL_RCP26, R_ECE_RCA_RCP26, R_ECE_RAC_RCP26, R_CNR_RAC_RCP26, R_NOR_R15_RCP26, R_CNR_ALA_RCP26, R_HAD_REG_RCP26, R_MPI_R09_RCP26])
R_DRIAS_85 = statistics.mean([R_MPI_CCL_RCP85, R_ECE_RCA_RCP85, R_ECE_RAC_RCP85, R_CNR_RAC_RCP85, R_NOR_R15_RCP85, R_CNR_ALA_RCP85, R_HAD_REG_RCP85, R_MPI_R09_RCP85])

#%% Model Parameters

model_name = sim_state # just a string

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth

# Hydraulic properties
K_hist = kr * R_hist
K_RCP26 = kr * R_DRIAS_26
K_RCP85 = kr * R_DRIAS_85

E = 30 # m
P = 0.01 #

# Active of not modules
first_only = False # if True generate results only for the first tim_step
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = True # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console

# Update properties
BV.hydrodynamic.update_hyd_cond(K_hist)
BV.hydrodynamic.update_thickness(E)
BV.hydrodynamic.update_porosity(P)
BV.hydrodynamic.update_nlay(1)
BV.hydrodynamic.update_thickness(30)
BV.hydrodynamic.update_bottom(None)
BV.hydrodynamic.update_cond_decay(0)
BV.hydrodynamic.update_thick_exp(1)


#%% LAUNCH MODELLING

#Choice of Recharge
R = R_DRIAS_85
BV.forcing.update_recharge(R, 'steady')

# Run model
success, flow_model = BV.run_modflow(ident=model_name,
                modpath_sim=modpath_sim,
                first_only=first_only,
                sink_fill=sink_fill,
                box=box,
                lay_number=lay_number,
                bottom=bottom,
                thick_exp=thick_exp,
                cond_decay=cond_decay,
                verbose=verbose)

BV.matrix_modflow(success, flow_model)

# Extract results
BV.results_modflow(ident=model_name,
                   actual_date=actual_date,
                   start=start,
                   time_step=time_step)

# x = imageio.imread('D:/Users/abherve/TEST/Conceptual/results_stable/geographic/watershed_dem.tif')
# plt.imshow(x)


#%% 2D VISUAL

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, 'steady')
visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow',
                             'surface_flow','pathlines', 'residence_times'],
              color_scale = [(None,None),(None,None),(0,35),(0,10),
                             (None,None),(None,None),(None,None),(None,None)], 
              lines=300)

