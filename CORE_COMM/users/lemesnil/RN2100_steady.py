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

# Path to the git repositoty home page
git_path = "C:/Users/Martin Le Mesnil/Travail/HydroModPy/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/"
# Path where the results will be stored
out_path = 'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

dems_path = data_path # reginal DEM or conceptual DEM
# shp_path = data_path + 'shp/' # if you want run a model from a shapefile
modflow_path = 'C:/Users/Martin Le Mesnil/Travail/HydroModPy/Modflow' # add bin/ folder with necessary .exe

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

sp_file = "C:/Users/Martin Le Mesnil/Travail/SIG/Couches_base/Administratif/region_normandie/normandie.shp" # None # specify a path if process start from a given shapefile

cell_size = None # specify new resolution from a given DEM or None

#%% GENERATING WATERSHED + data
# We propose 4 tests :
    # 1 - From a outlet coordinates : 'Outlet'
    # 2 - From a shpaefile : 'Shapefile'
    # 3 - From an actual DEM : 'Dem'
    # 4 - From a conceptual DEM : 'Conceptual'

shp_file = 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'
# 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Caen/watershed_clip_caen_2.shp'
# 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Baie-du-Cotentin/watershed_clip_carentan.shp'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=shp_file,
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
BV.add_drias("C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/CLIMAT/Normandie/")

BV.save_object()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)


#%% Load BV object
    
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=True,
                              from_shp=None,
                              from_dem=False,
                              cell_size=cell_size)

BV.load_object()

#%% Add piezometry

BV.add_forcing()

BV.piezometry.add_data()
BV.piezometry.display_data()


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
                                  first_year = 2015, last_year=2019, time_step = 'M',
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

#%% calib analysis

from calibration import calib_analysis
import glob
typ_calib = 'piezometry_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
key=os.path.getmtime, reverse=True)
name_file = list_path[0].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)

test.display_objective_function(save='C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/'+params_file+'.png',vmax= 1.3,log=False)

#%% Historic mean recharge

BV.add_forcing()

# Historic recharge
sim_state = 'transient' # 'steady' or 'transient'
period = [2015, 2019] # rehcarge period
time_step = 'D' # DMY
actual_date = True # False if date is conceptual
start = str(period[0])+'-01-01' # necessary to specify the first time_step date

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
                                      first_year = period[0], last_year = period[1], 
                                      time_step = time_step, sim_state = sim_state)

R_hist = BV.forcing.recharge
# BV.forcing.update_recharge(values = R_hist, sim_state = sim_state)

#%% DRIAS recharges

sim_state = 'transient' # 'steady' or 'transient'
first_yr = 2020
last_yr = 2025
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
import numpy

if sim_state == 'steady' :
    R_DRIAS_26 = numpy.nanmean([R_MPI_CCL_RCP26, R_ECE_RCA_RCP26, R_ECE_RAC_RCP26, R_CNR_RAC_RCP26, R_NOR_R15_RCP26, R_CNR_ALA_RCP26, R_HAD_REG_RCP26, R_MPI_R09_RCP26])
    R_DRIAS_85 = numpy.nanmean([R_MPI_CCL_RCP85, R_ECE_RCA_RCP85, R_ECE_RAC_RCP85, R_CNR_RAC_RCP85, R_NOR_R15_RCP85, R_CNR_ALA_RCP85, R_HAD_REG_RCP85, R_MPI_R09_RCP85])
elif sim_state == 'transient' :
    R_DRIAS_26 = numpy.nanmean([numpy.nanmean(R_MPI_CCL_RCP26), numpy.nanmean(R_ECE_RCA_RCP26), numpy.nanmean(R_ECE_RAC_RCP26), numpy.nanmean(R_CNR_RAC_RCP26), numpy.nanmean(R_NOR_R15_RCP26), numpy.nanmean(R_CNR_ALA_RCP26), numpy.nanmean(R_HAD_REG_RCP26), numpy.nanmean(R_MPI_R09_RCP26)])
    R_DRIAS_85 = numpy.nanmean([numpy.nanmean(R_MPI_CCL_RCP85), numpy.nanmean(R_ECE_RCA_RCP85), numpy.nanmean(R_ECE_RAC_RCP85), numpy.nanmean(R_CNR_RAC_RCP85), numpy.nanmean(R_NOR_R15_RCP85), numpy.nanmean(R_CNR_ALA_RCP85), numpy.nanmean(R_HAD_REG_RCP85), numpy.nanmean(R_MPI_R09_RCP85)])


#%% SEA LEVEL TESTS

# print(vars(BV.oceanic).keys())
RSL_85 = BV.oceanic.RSL["RCP8.5"]
md_rsl_85 = RSL_85.iloc[:,0]
RSL_26 = BV.oceanic.RSL["RCP2.6"]
md_rsl_26 = RSL_26.iloc[:,0]

RMSL_85 = BV.oceanic.RMSL["RCP8.5"]
md_rmsl_85 = RMSL_85.iloc[:,0]
RMSL_26 = BV.oceanic.RMSL["RCP2.6"]
md_rmsl_26 = RMSL_26.iloc[:,0]

MSL = BV.oceanic.MSL


#%% Model Parameters

# Hydraulic properties
E = 30 # m
P = 0.01 #

K_hist = kr * np.mean(R_hist)
K_RCP26 = kr * R_DRIAS_26
K_RCP85 = kr * R_DRIAS_85

K = K_hist

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth

# Active of not modules
first_only = False # if True generate results only for the first tim_step
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = True # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console

# Update properties
BV.hydrodynamic.update_hyd_cond(K)
BV.hydrodynamic.update_thickness(E)
BV.hydrodynamic.update_porosity(P)
BV.hydrodynamic.update_nlay(1)
BV.hydrodynamic.update_thickness(30)
BV.hydrodynamic.update_bottom(None)
BV.hydrodynamic.update_cond_decay(0)
BV.hydrodynamic.update_thick_exp(1)


#%% LAUNCH MODELLING

#Choice of Recharge and sea level
model_name = 'steady_RSL85' # string for simulation results storage #steady_DRIAS_85 #'steady_hist'
R = R_hist #R_DRIAS_85   R_hist
# sea_lev_rise = RSL85_df['median']

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

#%% Water table depth processing

import rioxarray
import pandas

rds = rioxarray.open_rasterio(r"C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Agon-Coutainville/WT_depth_hist_ACO.tif",)
raster_val = rds.squeeze().drop("band")
raster_values = raster_val.values

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
        
if c_tot != raster_values.shape[0] * raster_values.shape[1] :
    print('wrong total')
elif c_ndv + c_ok + c_03 + c_sub != c_tot :
    print('wrong count')
else :
    print('OK')
    
# for h in raster_values :
#     print(h)
    

#%% 2D VISUAL

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, model_name)
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


