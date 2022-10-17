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

# import os
# dir(os.getcwd())


# %% PATHS + watershed options

watershed_name = 'Saint-Germain-sur-Ay'
# Caen Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
load = False # loads previously generated basin if true

# # Path to the git repositoty home page
git_path = r"C:/Users/Martin Le Mesnil/Travail/HydroModPy/HydroModPy/CORE_COMM/"
# # Path to the data folder
data_path = r"C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/"
# # Path where the results will be stored
out_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

dems_path = data_path # reginal DEM or conceptual DEM
# shp_path = data_path + 'shp/' # if you want run a model from a shapefile
modflow_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/Modflow/' # add bin/ folder with necessary .exe

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

sp_file = r"C:/Users/Martin Le Mesnil/Travail/SIG/Couches_base/Administratif/region_normandie/normandie.shp" # None # specify a path if process start from a given shapefile

cell_size = None # specify new resolution from a given DEM or None

#%% GENERATING WATERSHED + data
# We propose 4 tests :
    # 1 - From a outlet coordinates : 'Outlet'
    # 2 - From a shpaefile : 'Shapefile'
    # 3 - From an actual DEM : 'Dem'
    # 4 - From a conceptual DEM : 'Conceptual'

shp_file = 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'
# 'C:/Users/Martin/Desktop/Travail/SIG/BV_RN2100/Caen/watershed_clip_caen_2.shp'
# 'C:/Users/Martin/Desktop/Travail/SIG/BV_RN2100/Baie-du-Cotentin/watershed_clip_carentan.shp'
# '‪C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=None,
                              from_dem=False,
                              cell_size=cell_size)

types_obs = ['streams_fr'] # list of shapefile name layers for clip hydrology
fields_obs = ['FID'] # list of shapefile name columns to translate as a tif

# create watershed properties
BV.add_hydrodynamic()
BV.add_forcing()
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
BV.add_drias(r"C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/CLIMAT/Normandie/")

BV.save_object()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)


#%% Calibration based on streams

import glob
import os

type_obs = 'streams_fr'
types_obs = ['streams_fr'] # list of shapefile name layers for clip hydrology

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

# Init
df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
area = BV.geographic.area
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
                                  first_year = 1960, last_year=2019, time_step = 'M',
                                  sim_state = 'steady') #
# BV.forcing.update_recharge(R_HAD_REG_RCP26, 'transient')
BV.hydrodynamic.update_thickness(30)
# BV.hydrodynamic.update_porosity(0.1)
# BV.hydrodynamic.update_hyd_cond(2)
params_df = pd.DataFrame(columns=['params',
                                  'init_values','lower_bounds','higher_bounds',
                                  'units','scale'])
# params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+01,'m/j','lin']
params_df.loc[0] = ['k1',10,1e-04,1e+02,'m/j','lin']
# params_df.loc[1] = ['k2',10,1e-04,1e+02,'m/j','lin']

params_file = 'calib_dicot_hom_1v_k1'
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
calib = calib_root.Calibration(params_file, BV, observations = ['streams']) #streams piezometry

# Launch dichotomy
dicot = calib.dichotomy(gap=1)
# calib.exploration(10)

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

# BV.piezometry.add_data()
# BV.save_object()

#%% Historic and DRIAS forecast recharges

BV.add_forcing()

# Historic recharge
sim_state = 'transient' # 'steady' or 'transient'
period = [1960, 2019] # rehcarge period
time_step = 'D' # DMY
actual_date = True # False if date is conceptual
start = str(period[0])+'-01-01' # necessary to specify the first time_step date

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
                                      first_year = period[0], last_year = period[1], 
                                      time_step = time_step, sim_state = sim_state)

R_hist = BV.forcing.recharge
# BV.forcing.update_recharge(values = R_hist, sim_state = sim_state)


sim_state = 'transient' # 'steady' or 'transient'
first_yr = 2020
last_yr = 2100

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


#Mean values (m/d)

import statistics
import numpy

R_hist_mean = statistics.mean(R_hist)

if sim_state == 'steady' :
    R_DRIAS_26 = numpy.nanmean([R_MPI_CCL_RCP26, R_ECE_RCA_RCP26, R_ECE_RAC_RCP26, R_CNR_RAC_RCP26, R_NOR_R15_RCP26, R_CNR_ALA_RCP26, R_HAD_REG_RCP26, R_MPI_R09_RCP26])
    R_DRIAS_85 = numpy.nanmean([R_MPI_CCL_RCP85, R_ECE_RCA_RCP85, R_ECE_RAC_RCP85, R_CNR_RAC_RCP85, R_NOR_R15_RCP85, R_CNR_ALA_RCP85, R_HAD_REG_RCP85, R_MPI_R09_RCP85])
elif sim_state == 'transient' :
    R_DRIAS_26 = numpy.nanmean([numpy.nanmean(R_MPI_CCL_RCP26), numpy.nanmean(R_ECE_RCA_RCP26), numpy.nanmean(R_ECE_RAC_RCP26), numpy.nanmean(R_CNR_RAC_RCP26), numpy.nanmean(R_NOR_R15_RCP26), numpy.nanmean(R_CNR_ALA_RCP26), numpy.nanmean(R_HAD_REG_RCP26), numpy.nanmean(R_MPI_R09_RCP26)])
    R_DRIAS_85 = numpy.nanmean([numpy.nanmean(R_MPI_CCL_RCP85), numpy.nanmean(R_ECE_RCA_RCP85), numpy.nanmean(R_ECE_RAC_RCP85), numpy.nanmean(R_CNR_RAC_RCP85), numpy.nanmean(R_NOR_R15_RCP85), numpy.nanmean(R_CNR_ALA_RCP85), numpy.nanmean(R_HAD_REG_RCP85), numpy.nanmean(R_MPI_R09_RCP85)])


#%% Recharge analysis: Group by month and year

import statistics

R_MPI_CCL_RCP26_month = R_MPI_CCL_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_ECE_RCA_RCP26_month = R_ECE_RCA_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_ECE_RAC_RCP26_month = R_ECE_RAC_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_CNR_RAC_RCP26_month = R_CNR_RAC_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_NOR_R15_RCP26_month = R_NOR_R15_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_CNR_ALA_RCP26_month = R_CNR_ALA_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_HAD_REG_RCP26_month = R_HAD_REG_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_HAD_REG_RCP26_month[R_HAD_REG_RCP26_month==0] = float("NaN")
R_MPI_R09_RCP26_month = R_MPI_R09_RCP26.groupby(pd.Grouper(freq="M")).sum()

DRIAS_models_list = ['MPI_CCL', 'ECE_RCA', 'ECE_RAC', 'CNR_RAC',
                     'NOR_R15', 'CNR_ALA', 'HAD_REG', 'MPI_R09']

R_DRIAS_26_month_dict = {
    0 : R_MPI_CCL_RCP26_month,
    1 : R_ECE_RCA_RCP26_month,
    2 : R_ECE_RAC_RCP26_month,
    3 : R_CNR_RAC_RCP26_month,
    4 : R_NOR_R15_RCP26_month,
    5 : R_CNR_ALA_RCP26_month,
    6 : R_HAD_REG_RCP26_month,
    7 : R_MPI_R09_RCP26_month}

R_DRIAS_26_month_med = []
for i in range(0,len(R_MPI_CCL_RCP26_month)) :
    R_DRIAS_26_month_med.append(statistics.median([R_MPI_CCL_RCP26_month[i],
                                                  R_ECE_RCA_RCP26_month[i],
                                                  R_ECE_RAC_RCP26_month[i],
                                                  R_CNR_RAC_RCP26_month[i],
                                                  R_NOR_R15_RCP26_month[i],
                                                  R_CNR_ALA_RCP26_month[i],
                                                  R_HAD_REG_RCP26_month[i],
                                                  R_MPI_R09_RCP26_month[i]]))

R_MPI_CCL_RCP85_month = R_MPI_CCL_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_ECE_RCA_RCP85_month = R_ECE_RCA_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_ECE_RAC_RCP85_month = R_ECE_RAC_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_CNR_RAC_RCP85_month = R_CNR_RAC_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_NOR_R15_RCP85_month = R_NOR_R15_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_CNR_ALA_RCP85_month = R_CNR_ALA_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_HAD_REG_RCP85_month = R_HAD_REG_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_HAD_REG_RCP85_month[R_HAD_REG_RCP85_month==0] = float("NaN")
R_MPI_R09_RCP85_month = R_MPI_R09_RCP85.groupby(pd.Grouper(freq="M")).sum()

R_DRIAS_85_month_dict = {
    0 : R_MPI_CCL_RCP85_month,
    1 : R_ECE_RCA_RCP85_month,
    2 : R_ECE_RAC_RCP85_month,
    3 : R_CNR_RAC_RCP85_month,
    4 : R_NOR_R15_RCP85_month,
    5 : R_CNR_ALA_RCP85_month,
    6 : R_HAD_REG_RCP85_month,
    7 : R_MPI_R09_RCP85_month}

R_DRIAS_85_month_med = []
for i in range(0,len(R_MPI_CCL_RCP85_month)) :
    R_DRIAS_85_month_med.append(statistics.median([R_MPI_CCL_RCP85_month[i],
                                                  R_ECE_RCA_RCP85_month[i],
                                                  R_ECE_RAC_RCP85_month[i],
                                                  R_CNR_RAC_RCP85_month[i],
                                                  R_NOR_R15_RCP85_month[i],
                                                  R_CNR_ALA_RCP85_month[i],
                                                  R_HAD_REG_RCP85_month[i],
                                                  R_MPI_R09_RCP85_month[i]]))


R_MPI_CCL_RCP26_year = R_MPI_CCL_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_ECE_RCA_RCP26_year = R_ECE_RCA_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_ECE_RAC_RCP26_year = R_ECE_RAC_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_CNR_RAC_RCP26_year = R_CNR_RAC_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_NOR_R15_RCP26_year = R_NOR_R15_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_CNR_ALA_RCP26_year = R_CNR_ALA_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_HAD_REG_RCP26_year = R_HAD_REG_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_MPI_R09_RCP26_year = R_MPI_R09_RCP26.groupby(pd.Grouper(freq="Y")).sum()

R_MPI_CCL_RCP85_year = R_MPI_CCL_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_ECE_RCA_RCP85_year = R_ECE_RCA_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_ECE_RAC_RCP85_year = R_ECE_RAC_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_CNR_RAC_RCP85_year = R_CNR_RAC_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_NOR_R15_RCP85_year = R_NOR_R15_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_CNR_ALA_RCP85_year = R_CNR_ALA_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_HAD_REG_RCP85_year = R_HAD_REG_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_MPI_R09_RCP85_year = R_MPI_R09_RCP85.groupby(pd.Grouper(freq="Y")).sum()


#%%  Recharge analysis: 2030 horizon
import statistics
import numpy

# 2030 annual recharge (m/yr to m/d): mean of 2028-2032  years
R_MPI_CCL_RCP26_2030 = R_MPI_CCL_RCP26.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_MPI_CCL_RCP85_2030 = R_MPI_CCL_RCP85.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_ECE_RCA_RCP26_2030 = R_ECE_RCA_RCP26.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_ECE_RCA_RCP85_2030 = R_ECE_RCA_RCP85.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_ECE_RAC_RCP26_2030 = R_ECE_RAC_RCP26.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_ECE_RAC_RCP85_2030 = R_ECE_RAC_RCP85.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_CNR_RAC_RCP26_2030 = R_CNR_RAC_RCP26.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_CNR_RAC_RCP85_2030 = R_CNR_RAC_RCP85.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_NOR_R15_RCP26_2030 = R_NOR_R15_RCP26.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_NOR_R15_RCP85_2030 = R_NOR_R15_RCP85.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_CNR_ALA_RCP26_2030 = R_CNR_ALA_RCP26.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_CNR_ALA_RCP85_2030 = R_CNR_ALA_RCP85.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_HAD_REG_RCP26_2030 = R_HAD_REG_RCP26.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_HAD_REG_RCP85_2030 = R_HAD_REG_RCP85.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_MPI_R09_RCP26_2030 = R_MPI_R09_RCP26.loc['2028-09-01':'2032-08-31'].sum()/(4*365)
R_MPI_R09_RCP85_2030 = R_MPI_R09_RCP85.loc['2028-09-01':'2032-08-31'].sum()/(4*365)

month_2030_4y_idx_list = [i for i in range(8*12, 12*12, 12)]

R_DRIAS_26_2030_mean_list = [R_MPI_CCL_RCP26_2030, R_ECE_RCA_RCP26_2030, R_ECE_RAC_RCP26_2030,
                          R_CNR_RAC_RCP26_2030, R_NOR_R15_RCP26_2030, R_CNR_ALA_RCP26_2030,
                          R_HAD_REG_RCP26_2030, R_MPI_R09_RCP26_2030]

R_DRIAS_26_2030_min = min(R_DRIAS_26_2030_mean_list)
index_min_R_26_2030 = min(range(len(R_DRIAS_26_2030_mean_list)), key=R_DRIAS_26_2030_mean_list.__getitem__)
R_DRIAS_26_month_min = R_DRIAS_26_month_dict[index_min_R_26_2030]
R_DRIAS_26_2030_max = max(R_DRIAS_26_2030_mean_list)
index_max_R_26_2030 = max(range(len(R_DRIAS_26_2030_mean_list)), key=R_DRIAS_26_2030_mean_list.__getitem__)
R_DRIAS_26_month_max = R_DRIAS_26_month_dict[index_max_R_26_2030]
R_DRIAS_26_2030_med = statistics.median(R_DRIAS_26_2030_mean_list)

R_DRIAS_26_month_mean_min_2030 = [
    numpy.nanmean(R_DRIAS_26_month_min[month_2030_4y_idx_list]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+1 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+2 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+3 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+4 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+5 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+6 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+7 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+8 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+9 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+10 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+11 for i in month_2030_4y_idx_list]])]
R_DRIAS_26_month_mean_max_2030 = [
    numpy.nanmean(R_DRIAS_26_month_max[month_2030_4y_idx_list]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+1 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+2 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+3 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+4 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+5 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+6 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+7 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+8 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+9 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+10 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+11 for i in month_2030_4y_idx_list]])]
R_DRIAS_26_month_mean_med_2030 = [
    numpy.nanmean([R_DRIAS_26_month_med[x] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+1] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+2] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+3] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+4] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+5] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+6] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+7] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+8] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+9] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+10] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+11] for x in month_2030_4y_idx_list])]


R_DRIAS_85_2030_mean_list = [R_MPI_CCL_RCP85_2030, R_ECE_RCA_RCP85_2030, R_ECE_RAC_RCP85_2030,
                          R_CNR_RAC_RCP85_2030, R_NOR_R15_RCP85_2030, R_CNR_ALA_RCP85_2030,
                          R_HAD_REG_RCP85_2030, R_MPI_R09_RCP85_2030]

R_DRIAS_85_2030_min = min(R_DRIAS_85_2030_mean_list)
index_min_R_85_2030 = min(range(len(R_DRIAS_85_2030_mean_list)), key=R_DRIAS_85_2030_mean_list.__getitem__)
R_DRIAS_85_month_min = R_DRIAS_85_month_dict[index_min_R_85_2030]
R_DRIAS_85_2030_max = max(R_DRIAS_85_2030_mean_list)
index_max_R_85_2030 = max(range(len(R_DRIAS_85_2030_mean_list)), key=R_DRIAS_85_2030_mean_list.__getitem__)
R_DRIAS_85_month_max = R_DRIAS_85_month_dict[index_max_R_85_2030]
R_DRIAS_85_2030_med = statistics.median(R_DRIAS_85_2030_mean_list)

R_DRIAS_85_month_mean_min_2030 = [
    numpy.nanmean(R_DRIAS_85_month_min[month_2030_4y_idx_list]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+1 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+2 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+3 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+4 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+5 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+6 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+7 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+8 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+9 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+10 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+11 for i in month_2030_4y_idx_list]])]
R_DRIAS_85_month_mean_max_2030 = [
    numpy.nanmean(R_DRIAS_85_month_max[month_2030_4y_idx_list]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+1 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+2 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+3 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+4 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+5 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+6 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+7 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+8 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+9 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+10 for i in month_2030_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+11 for i in month_2030_4y_idx_list]])]
R_DRIAS_85_month_mean_med_2030 = [
    numpy.nanmean([R_DRIAS_85_month_med[x] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+1] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+2] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+3] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+4] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+5] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+6] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+7] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+8] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+9] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+10] for x in month_2030_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+11] for x in month_2030_4y_idx_list])]


#%%  Recharge analysis: 2050 horizon

# 2050 annual recharge (m/yr to m/d): mean of 2048-2052 years
R_MPI_CCL_RCP26_2050 = R_MPI_CCL_RCP26.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_MPI_CCL_RCP85_2050 = R_MPI_CCL_RCP85.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_ECE_RCA_RCP26_2050 = R_ECE_RCA_RCP26.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_ECE_RCA_RCP85_2050 = R_ECE_RCA_RCP85.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_ECE_RAC_RCP26_2050 = R_ECE_RAC_RCP26.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_ECE_RAC_RCP85_2050 = R_ECE_RAC_RCP85.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_CNR_RAC_RCP26_2050 = R_CNR_RAC_RCP26.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_CNR_RAC_RCP85_2050 = R_CNR_RAC_RCP85.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_NOR_R15_RCP26_2050 = R_NOR_R15_RCP26.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_NOR_R15_RCP85_2050 = R_NOR_R15_RCP85.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_CNR_ALA_RCP26_2050 = R_CNR_ALA_RCP26.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_CNR_ALA_RCP85_2050 = R_CNR_ALA_RCP85.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_HAD_REG_RCP26_2050 = R_HAD_REG_RCP26.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_HAD_REG_RCP85_2050 = R_HAD_REG_RCP85.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_MPI_R09_RCP26_2050 = R_MPI_R09_RCP26.loc['2048-09-01':'2052-08-31'].sum()/(4*365)
R_MPI_R09_RCP85_2050 = R_MPI_R09_RCP85.loc['2048-09-01':'2052-08-31'].sum()/(4*365)

month_2050_4y_idx_list = [i for i in range(28*12, 32*12, 12)]

R_DRIAS_26_2050_mean_list = [R_MPI_CCL_RCP26_2050, R_ECE_RCA_RCP26_2050, R_ECE_RAC_RCP26_2050,
                          R_CNR_RAC_RCP26_2050, R_NOR_R15_RCP26_2050, R_CNR_ALA_RCP26_2050,
                          R_HAD_REG_RCP26_2050, R_MPI_R09_RCP26_2050]

R_DRIAS_26_2050_min = min(R_DRIAS_26_2050_mean_list)
index_min_R_26_2050 = min(range(len(R_DRIAS_26_2050_mean_list)), key=R_DRIAS_26_2050_mean_list.__getitem__)
R_DRIAS_26_month_min = R_DRIAS_26_month_dict[index_min_R_26_2050]
R_DRIAS_26_2050_max = max(R_DRIAS_26_2050_mean_list)
index_max_R_26_2050 = max(range(len(R_DRIAS_26_2050_mean_list)), key=R_DRIAS_26_2050_mean_list.__getitem__)
R_DRIAS_26_month_max = R_DRIAS_26_month_dict[index_max_R_26_2050]
R_DRIAS_26_2050_med = statistics.median(R_DRIAS_26_2050_mean_list)

R_DRIAS_26_month_mean_min_2050 = [
    numpy.nanmean(R_DRIAS_26_month_min[month_2050_4y_idx_list]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+1 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+2 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+3 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+4 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+5 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+6 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+7 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+8 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+9 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+10 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+11 for i in month_2050_4y_idx_list]])]
R_DRIAS_26_month_mean_max_2050 = [
    numpy.nanmean(R_DRIAS_26_month_max[month_2050_4y_idx_list]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+1 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+2 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+3 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+4 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+5 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+6 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+7 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+8 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+9 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+10 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+11 for i in month_2050_4y_idx_list]])]
R_DRIAS_26_month_mean_med_2050 = [
    numpy.nanmean([R_DRIAS_26_month_med[x] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+1] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+2] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+3] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+4] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+5] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+6] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+7] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+8] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+9] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+10] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+11] for x in month_2050_4y_idx_list])]


R_DRIAS_85_2050_mean_list = [R_MPI_CCL_RCP85_2050, R_ECE_RCA_RCP85_2050, R_ECE_RAC_RCP85_2050,
                          R_CNR_RAC_RCP85_2050, R_NOR_R15_RCP85_2050, R_CNR_ALA_RCP85_2050,
                          R_HAD_REG_RCP85_2050, R_MPI_R09_RCP85_2050]

R_DRIAS_85_2050_min = min(R_DRIAS_85_2050_mean_list)
index_min_R_85_2050 = min(range(len(R_DRIAS_85_2050_mean_list)), key=R_DRIAS_85_2050_mean_list.__getitem__)
R_DRIAS_85_month_min = R_DRIAS_85_month_dict[index_min_R_85_2050]
R_DRIAS_85_2050_max = max(R_DRIAS_85_2050_mean_list)
index_max_R_85_2050 = max(range(len(R_DRIAS_85_2050_mean_list)), key=R_DRIAS_85_2050_mean_list.__getitem__)
R_DRIAS_85_month_max = R_DRIAS_85_month_dict[index_max_R_85_2050]
R_DRIAS_85_2050_med = statistics.median(R_DRIAS_85_2050_mean_list)

R_DRIAS_85_month_mean_min_2050 = [
    numpy.nanmean(R_DRIAS_85_month_min[month_2050_4y_idx_list]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+1 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+2 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+3 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+4 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+5 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+6 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+7 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+8 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+9 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+10 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+11 for i in month_2050_4y_idx_list]])]
R_DRIAS_85_month_mean_max_2050 = [
    numpy.nanmean(R_DRIAS_85_month_max[month_2050_4y_idx_list]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+1 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+2 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+3 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+4 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+5 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+6 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+7 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+8 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+9 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+10 for i in month_2050_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+11 for i in month_2050_4y_idx_list]])]
R_DRIAS_85_month_mean_med_2050 = [
    numpy.nanmean([R_DRIAS_85_month_med[x] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+1] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+2] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+3] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+4] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+5] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+6] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+7] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+8] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+9] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+10] for x in month_2050_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+11] for x in month_2050_4y_idx_list])]


#%%  Recharge analysis: 2100 horizon

# 2100 annual recharge (m/yr to m/d): mean of 2096-2099 years
R_MPI_CCL_RCP26_2100 = R_MPI_CCL_RCP26.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_MPI_CCL_RCP85_2100 = R_MPI_CCL_RCP85.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_ECE_RCA_RCP26_2100 = R_ECE_RCA_RCP26.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_ECE_RCA_RCP85_2100 = R_ECE_RCA_RCP85.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_ECE_RAC_RCP26_2100 = R_ECE_RAC_RCP26.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_ECE_RAC_RCP85_2100 = R_ECE_RAC_RCP85.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_CNR_RAC_RCP26_2100 = R_CNR_RAC_RCP26.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_CNR_RAC_RCP85_2100 = R_CNR_RAC_RCP85.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_NOR_R15_RCP26_2100 = R_NOR_R15_RCP26.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_NOR_R15_RCP85_2100 = R_NOR_R15_RCP85.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_CNR_ALA_RCP26_2100 = R_CNR_ALA_RCP26.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_CNR_ALA_RCP85_2100 = R_CNR_ALA_RCP85.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_HAD_REG_RCP26_2100 = R_HAD_REG_RCP26.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_HAD_REG_RCP85_2100 = R_HAD_REG_RCP85.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_MPI_R09_RCP26_2100 = R_MPI_R09_RCP26.loc['2095-09-01':'2099-08-31'].sum()/(4*365)
R_MPI_R09_RCP85_2100 = R_MPI_R09_RCP85.loc['2095-09-01':'2099-08-31'].sum()/(4*365)

month_2100_4y_idx_list = [i for i in range(76*12, 80*12, 12)]

R_DRIAS_26_2100_mean_list = [R_MPI_CCL_RCP26_2100, R_ECE_RCA_RCP26_2100, R_ECE_RAC_RCP26_2100,
                          R_CNR_RAC_RCP26_2100, R_NOR_R15_RCP26_2100, R_CNR_ALA_RCP26_2100,
                          R_HAD_REG_RCP26_2100, R_MPI_R09_RCP26_2100]

R_DRIAS_26_2100_min = min(R_DRIAS_26_2100_mean_list)
index_min_R_26_2100 = min(range(len(R_DRIAS_26_2100_mean_list)), key=R_DRIAS_26_2100_mean_list.__getitem__)
R_DRIAS_26_month_min = R_DRIAS_26_month_dict[index_min_R_26_2100]
R_DRIAS_26_2100_max = max(R_DRIAS_26_2100_mean_list)
index_max_R_26_2100 = max(range(len(R_DRIAS_26_2100_mean_list)), key=R_DRIAS_26_2100_mean_list.__getitem__)
R_DRIAS_26_month_max = R_DRIAS_26_month_dict[index_max_R_26_2100]
R_DRIAS_26_2100_med = statistics.median(R_DRIAS_26_2100_mean_list)

R_DRIAS_26_month_mean_min_2100 = [
    numpy.nanmean(R_DRIAS_26_month_min[month_2100_4y_idx_list]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+1 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+2 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+3 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+4 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+5 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+6 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+7 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+8 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+9 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+10 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_min[[i+11 for i in month_2100_4y_idx_list]])]
R_DRIAS_26_month_mean_max_2100 = [
    numpy.nanmean(R_DRIAS_26_month_max[month_2100_4y_idx_list]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+1 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+2 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+3 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+4 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+5 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+6 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+7 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+8 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+9 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+10 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_26_month_max[[i+11 for i in month_2100_4y_idx_list]])]
R_DRIAS_26_month_mean_med_2100 = [
    numpy.nanmean([R_DRIAS_26_month_med[x] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+1] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+2] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+3] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+4] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+5] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+6] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+7] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+8] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+9] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+10] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_26_month_med[x+11] for x in month_2100_4y_idx_list])]


R_DRIAS_85_2100_mean_list = [R_MPI_CCL_RCP85_2100, R_ECE_RCA_RCP85_2100, R_ECE_RAC_RCP85_2100,
                          R_CNR_RAC_RCP85_2100, R_NOR_R15_RCP85_2100, R_CNR_ALA_RCP85_2100,
                          R_HAD_REG_RCP85_2100, R_MPI_R09_RCP85_2100]

R_DRIAS_85_2100_min = min(R_DRIAS_85_2100_mean_list)
index_min_R_85_2100 = min(range(len(R_DRIAS_85_2100_mean_list)), key=R_DRIAS_85_2100_mean_list.__getitem__)
R_DRIAS_85_month_min = R_DRIAS_85_month_dict[index_min_R_85_2100]
R_DRIAS_85_2100_max = max(R_DRIAS_85_2100_mean_list)
index_max_R_85_2100 = max(range(len(R_DRIAS_85_2100_mean_list)), key=R_DRIAS_85_2100_mean_list.__getitem__)
R_DRIAS_85_month_max = R_DRIAS_85_month_dict[index_max_R_85_2100]
R_DRIAS_85_2100_med = statistics.median(R_DRIAS_85_2100_mean_list)

R_DRIAS_85_month_mean_min_2100 = [
    numpy.nanmean(R_DRIAS_85_month_min[month_2100_4y_idx_list]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+1 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+2 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+3 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+4 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+5 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+6 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+7 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+8 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+9 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+10 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_min[[i+11 for i in month_2100_4y_idx_list]])]
R_DRIAS_85_month_mean_max_2100 = [
    numpy.nanmean(R_DRIAS_85_month_max[month_2100_4y_idx_list]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+1 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+2 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+3 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+4 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+5 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+6 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+7 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+8 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+9 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+10 for i in month_2100_4y_idx_list]]),
    numpy.nanmean(R_DRIAS_85_month_max[[i+11 for i in month_2100_4y_idx_list]])]
R_DRIAS_85_month_mean_med_2100 = [
    numpy.nanmean([R_DRIAS_85_month_med[x] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+1] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+2] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+3] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+4] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+5] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+6] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+7] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+8] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+9] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+10] for x in month_2100_4y_idx_list]),
    numpy.nanmean([R_DRIAS_85_month_med[x+11] for x in month_2100_4y_idx_list])]


#%% Plots and synthesis

#2030
import matplotlib.pyplot as plt

fig, axs = plt.subplots(2, 1)
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_min_2030, label = 'Min: ' + DRIAS_models_list[index_min_R_26_2030])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_max_2030, label = 'Max: ' + DRIAS_models_list[index_max_R_26_2030])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_med_2030, label = 'Median')
axs[0].set_title('RCP 2.6', fontsize=14)
axs[0].legend(loc = 'upper center')
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_min_2030, label = 'Min: ' + DRIAS_models_list[index_min_R_85_2030])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_max_2030, label = 'Max: ' + DRIAS_models_list[index_max_R_85_2030])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_med_2030, label = 'Median')
axs[1].set_title('RCP 8.5', fontsize=14)
axs[1].legend(loc = 'upper center')

fig.suptitle('2030 forecast recharges (m/month)', fontsize=18)
plt.setp(axs[-1], xlabel='Month')

# 2050
import matplotlib.pyplot as plt

fig, axs = plt.subplots(2, 1)
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_min_2050, label = 'Min: ' + DRIAS_models_list[index_min_R_26_2050])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_max_2050, label = 'Max: ' + DRIAS_models_list[index_max_R_26_2050])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_med_2050, label = 'Median')
axs[0].set_title('RCP 2.6', fontsize=14)
axs[0].legend(loc = 'upper center')
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_min_2050, label = 'Min: ' + DRIAS_models_list[index_min_R_85_2050])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_max_2050, label = 'Max: ' + DRIAS_models_list[index_max_R_85_2050])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_med_2050, label = 'Median')
axs[1].set_title('RCP 8.5', fontsize=14)
axs[1].legend(loc = 'upper center')

fig.suptitle('2050 forecast recharges (m/month)', fontsize=18)
plt.setp(axs[-1], xlabel='Month')

#2100
import matplotlib.pyplot as plt

fig, axs = plt.subplots(2, 1)
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_max_2100, label = 'Max: ' + DRIAS_models_list[index_max_R_26_2100], color = 'b')
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_med_2100, label = 'Median', color = 'g')
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_min_2100, label = 'Min: ' + DRIAS_models_list[index_min_R_26_2100], color = 'r')
axs[0].set_title('RCP 2.6', fontsize=14)
axs[0].legend(loc = 'upper center')
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_max_2100, label = 'Max: ' + DRIAS_models_list[index_max_R_85_2100], color = 'b')
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_med_2100, label = 'Median', color = 'g')
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_min_2100, label = 'Min: ' + DRIAS_models_list[index_min_R_85_2100], color = 'r')
axs[1].set_title('RCP 8.5', fontsize=14)
axs[1].legend(loc = 'upper center')

fig.suptitle('2100 forecast recharges (m/month)', fontsize=18)
plt.setp(axs[-1], xlabel='Month')

# Value storage (m/d)
# R_DRIAS_26_2030_min


#%% SEA LEVEL

MSL = BV.oceanic.MSL

# print(vars(BV.oceanic).keys())
# RSL_26 = BV.oceanic.RSL["RCP2.6"]
# md_rsl_26 = RSL_26.iloc[:,0]
# RSL_85 = BV.oceanic.RSL["RCP8.5"]
# md_rsl_85 = RSL_85.iloc[:,0]

RMSL_26 = BV.oceanic.RMSL["RCP2.6"]
md_rmsl_26 = RMSL_26.iloc[:,0]
RMSL_85 = BV.oceanic.RMSL["RCP8.5"]
md_rmsl_85 = RMSL_85.iloc[:,0]

# Delta_sea = md_rmsl_85 - md_rsl_85

RMSL_26_yr = md_rmsl_26.groupby(pd.Grouper(freq="Y")).mean()
RMSL_26_2030 = RMSL_26_yr[2030-2007]
RMSL_26_2050 = RMSL_26_yr[2050-2007]
RMSL_26_2100 = RMSL_26_yr[2100-2007]
RMSL_85_yr = md_rmsl_85.groupby(pd.Grouper(freq="Y")).mean()
RMSL_85_2030 = RMSL_85_yr[2030-2007]
RMSL_85_2050 = RMSL_85_yr[2050-2007]
RMSL_85_2100 = RMSL_85_yr[2100-2007]+10


import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.plot(md_rmsl_26, label = 'RMSL_RCP2.6  (mNGF)')
ax.plot(md_rmsl_85, label = 'RMSL_RCP8.5  (mNGF)')
plt.ylabel('Sea level')
ax.legend(loc = 'upper center')
plt.show()


#%% Model Parameters

# Hydraulic properties
E = 30 # m
P = 0.01 #
K = kr * R_hist_mean

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth

# Active of not modules
first_only = False # if True generate results only for the first time_step
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = True # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console

# Update properties
BV.hydrodynamic.update_hyd_cond(K)
BV.hydrodynamic.update_thickness(E)
BV.hydrodynamic.update_porosity(P)
BV.hydrodynamic.update_nlay(lay_number)
BV.hydrodynamic.update_bottom(bottom)
BV.hydrodynamic.update_cond_decay(cond_decay)
BV.hydrodynamic.update_thick_exp(thick_exp)


#%% Launch simulations

horiz_list = ['2030', '2050', '2100']
rech_list = ['26', '85', 'HI']
modclim_list = ['MIN', 'MED', 'MAX']
sealev_list = ['MSL', 'RSL']

R_dict = {
    'hor2030_rech26_climodMIN' : R_DRIAS_26_2030_min,
    'hor2030_rech26_climodMED' : R_DRIAS_26_2030_med,
    'hor2030_rech26_climodMAX' : R_DRIAS_26_2030_max,
    'hor2030_rech85_climodMIN' : R_DRIAS_85_2030_min,
    'hor2030_rech85_climodMED' : R_DRIAS_85_2030_med,
    'hor2030_rech85_climodMAX' : R_DRIAS_85_2030_max,
    
    'hor2050_rech26_climodMIN' : R_DRIAS_26_2050_min,
    'hor2050_rech26_climodMED' : R_DRIAS_26_2050_med,
    'hor2050_rech26_climodMAX' : R_DRIAS_26_2050_max,
    'hor2050_rech85_climodMIN' : R_DRIAS_85_2050_min,
    'hor2050_rech85_climodMED' : R_DRIAS_85_2050_med,
    'hor2050_rech85_climodMAX' : R_DRIAS_85_2050_max,
    
    'hor2100_rech26_climodMIN' : R_DRIAS_26_2100_min,
    'hor2100_rech26_climodMED' : R_DRIAS_26_2100_med,
    'hor2100_rech26_climodMAX' : R_DRIAS_26_2100_max,
    'hor2100_rech85_climodMIN' : R_DRIAS_85_2100_min,
    'hor2100_rech85_climodMED' : R_DRIAS_85_2100_med,
    'hor2100_rech85_climodMAX' : R_DRIAS_85_2100_max}

SL_dict = {
    ('2030', '26') : RMSL_26_2030,
    ('2030', '85') : RMSL_85_2030,
    
    ('2050', '26') : RMSL_26_2050,
    ('2050', '85') : RMSL_85_2050,
    
    ('2100', '26') : RMSL_26_2100,
    ('2100', '85') : RMSL_85_2100}

start_year_dict = {
    '2030' : '2028',
    '2050' : '2048',
    '2100' : '2095'}

forcing_dict = {}

# Loop through forcings

for horiz in horiz_list :
    rech_hist = 0
    # print(horiz)
    for rech in rech_list :
        # print(rech)
        for modclim in modclim_list :
            # print(modclim)
            if rech_hist == 1 : continue
            for sealev in sealev_list :
                # print(sealev)
                


                if rech == 'HI' :
                    R = R_hist_mean
                    rech_hist = 1
                    modclim = 'REA'
                    
                    if  horiz == '2030' :
                        sea_lev = MSL
                        sim_name = 'hor' + horiz + '_rech' + rech + '_climod' + modclim + '_sealev' + sealev
                        print(sim_name)
                        BV.oceanic.update_MSL(sea_lev)
                        BV.forcing.update_recharge(R, 'steady')
                        forcing_dict[(sim_name, 'R')] = BV.forcing.recharge
                        forcing_dict[(sim_name, 'SL')] = BV.oceanic.MSL
                        success, flow_model = BV.run_modflow(ident=sim_name,
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
                        time_step = 'D' # DMY
                        actual_date = True # False if date is conceptual
                        start = start_year_dict[horiz] + '-01-01' # necessary to specify the first time_step date
                        BV.results_modflow(ident=sim_name,
                                            actual_date=actual_date,
                                            start=start,
                                            time_step=time_step)

                    sea_lev = float(SL_dict[(horiz, '26')])
                    sealev = 'RS2'
                    sim_name = 'hor' + horiz + '_rech' + rech + '_climod' + modclim + '_sealev' + sealev
                    print(sim_name)
                    BV.oceanic.update_MSL(sea_lev)
                    BV.forcing.update_recharge(R, 'steady')
                    forcing_dict[(sim_name, 'R')] = BV.forcing.recharge
                    forcing_dict[(sim_name, 'SL')] = BV.oceanic.MSL
                    success, flow_model = BV.run_modflow(ident=sim_name,
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
                    time_step = 'D' # DMY
                    actual_date = True # False if date is conceptual
                    start = start_year_dict[horiz] + '-01-01' # necessary to specify the first time_step date
                    BV.results_modflow(ident=sim_name,
                                        actual_date=actual_date,
                                        start=start,
                                        time_step=time_step)

                    sea_lev = float(SL_dict[(horiz, '85')])
                    sealev = 'RS8'
                    sim_name = 'hor' + horiz + '_rech' + rech + '_climod' + modclim + '_sealev' + sealev
                    print(sim_name)
                    BV.oceanic.update_MSL(sea_lev)
                    BV.forcing.update_recharge(R, 'steady')
                    forcing_dict[(sim_name, 'R')] = BV.forcing.recharge
                    forcing_dict[(sim_name, 'SL')] = BV.oceanic.MSL
                    success, flow_model = BV.run_modflow(ident=sim_name,
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
                    time_step = 'D' # DMY
                    actual_date = True # False if date is conceptual
                    start = start_year_dict[horiz] + '-01-01' # necessary to specify the first time_step date
                    BV.results_modflow(ident=sim_name,
                                        actual_date=actual_date,
                                        start=start,
                                        time_step=time_step)

                    break

                else :
                    sim_name = 'hor' + horiz + '_rech' + rech + '_climod' + modclim + '_sealev' + sealev
                    print(sim_name)

                    R = R_dict[sim_name[0:24]]
                    
                    if 'MSL' in sim_name :
                        sea_lev = MSL
                    else :
                        sea_lev = float(SL_dict[(sim_name[3:7], sim_name[12:14])])
    
                    BV.oceanic.update_MSL(sea_lev)
                    BV.forcing.update_recharge(R, 'steady')
                    forcing_dict[(sim_name, 'R')] = BV.forcing.recharge
                    forcing_dict[(sim_name, 'SL')] = BV.oceanic.MSL
                    success, flow_model = BV.run_modflow(ident=sim_name,
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
                    time_step = 'D' # DMY
                    actual_date = True # False if date is conceptual
                    start = start_year_dict[horiz] + '-01-01' # necessary to specify the first time_step date
                    BV.results_modflow(ident=sim_name,
                                        actual_date=actual_date,
                                        start=start,
                                        time_step=time_step)


#%% Water table depth processing

raster_def = 75 #water table depth raster definition (m)
seep_area_dict = {}

import os
simulation_dir = out_path + BV.watershed_name + '/results_simulations/'
list_sim_tmp = os.listdir(simulation_dir)
# /steady/_watershed/_tifs

list_sim = []
for fold in list_sim_tmp:
    if fold[0:3] == 'hor':
        print(fold)
        list_sim.append(fold)
        
import rioxarray

for sim in list_sim :
    rds = rioxarray.open_rasterio(simulation_dir + sim + '/_watershed/_tifs/watertable_depth_t(0).tif')
    raster_val = rds.squeeze().drop("band")
    raster_values = raster_val.values
    rds.close()
    
    c_tot = c_ndv = c_sub = c_03 = c_ok = 0
    for x in range(raster_values.shape[0]) :
        for y in range(raster_values.shape[1]) :
            c_tot +=1
            h = raster_values[x,y]
            if h == -9999 :
                c_ndv += 1
            elif h <= 0 :
                c_sub += 1
            elif h <= 0.3 :
                c_03 += 1
            else :
                c_ok += 1
            
    if c_tot != raster_values.shape[0] * raster_values.shape[1] or c_ndv + c_ok + c_03 + c_sub != c_tot :
        a_03 = a_sub = float('nan')
    else :
        a_sub = c_sub * (raster_def**2)
        a_03 = (c_sub+c_03) * (raster_def**2)
        
    seep_area_dict[(sim, '03')] = a_03
    seep_area_dict[(sim, 'sub')] = a_sub
        
    if sim == 'hor2030_rechHI_climodREA_sealevMSL' :
        a_sub_hist = a_sub
        a_03_hist = a_03
       
seep_d_area_dict = seep_dp_area_dict = {}
for k in seep_area_dict.keys():
    if k[1] == '03':
        seep_d_area_dict[k] = seep_area_dict[k] - a_03_hist
        seep_dp_area_dict[k] = (seep_area_dict[k] - a_03_hist) / a_03_hist * 100
    elif k[1] == 'sub':
        seep_d_area_dict[k] = seep_area_dict[k] - a_sub_hist
        seep_dp_area_dict[k] = (seep_area_dict[k] - a_sub_hist) / a_sub_hist * 100
    

#%% 2D VISUAL

sim_name = 'hor2100_rech85_climodMED_sealevRSL'

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, sim_name)
visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow',
                             'surface_flow','pathlines', 'residence_times'],
              color_scale = [(None,None),(None,None),(0,35),(0,10),
                             (None,None),(None,None),(None,None),(None,None)], 
              lines=300)

#%% 2D VISUAL (modified for large basins)

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, 'steady_2')

visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow',
                              'surface_flow','pathlines', 'residence_times'],
              color_scale = [(None,None),(None,None),(0,35),(0,10),
                              (None,None),(None,None),(None,None),(None,None)], 
              lines=300)

# visu.visual2D(object_list = ['pathlines', 'residence_times'],
#               color_scale = [(None,None),(None,None)], 
#               lines=1000)


visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow',
                             'pathlines', 'residence_times'],
              color_scale = [(None,None),(None,None),(0,35),
                             (0,10),(None,None), (None,None), (None,None)], 
              lines=100) # IF LINES = NONE === ALL LINES GENERATED


