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
from tools import toolbox
# from groundwater_flow import visualization, modflow_display

# LAYOUT PLOT
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

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
shp_file = 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'
# 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Caen/watershed_clip_caen_2.shp'
# 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Baie-du-Cotentin/watershed_clip_carentan.shp'

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
watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% Add piezometry and get time period
import os
from datetime import datetime

BV.add_forcing()

BV.piezometry.add_data()
BV.piezometry.display_data()

start_date_list = []
end_date_list = []
added_data_path = stable_folder + 'add_data/'
added_data_list = os.listdir(added_data_path)
for file in added_data_list:
    if file.startswith('piezometry'):
        filename = added_data_path + file
        data = pd.read_csv(filename, sep = ";")
        start_date_list.append(data.loc[0,"Date"])
        end_date_list.append(data.loc[data.index[-1],"Date"])
        
start_date_list_datetime = [datetime.strptime(d, '%d/%m/%Y %H:%M') for d in start_date_list]
end_date_list_datetime = [datetime.strptime(d, '%d/%m/%Y %H:%M') for d in end_date_list]
start_date = max(start_date_list_datetime)
end_date = min(end_date_list_datetime)

#%% Historic recharge

BV.add_forcing()
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
                                      first_year = start_date.year, last_year = end_date.year, 
                                      time_step = 'D', sim_state = 'transient')

R_hist = BV.forcing.recharge
# BV.forcing.update_recharge(values = R_hist, sim_state = sim_state)

#%% DRIAS recharges

sim_state = 'transient' # 'steady' or 'transient'
first_yr = start_date.year
last_yr = end_date.year
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
import numpy

if sim_state == 'steady' :
    R_DRIAS_26 = numpy.nanmean([R_MPI_CCL_RCP26, R_ECE_RCA_RCP26, R_ECE_RAC_RCP26, R_CNR_RAC_RCP26, R_NOR_R15_RCP26, R_CNR_ALA_RCP26, R_HAD_REG_RCP26, R_MPI_R09_RCP26])
    R_DRIAS_85 = numpy.nanmean([R_MPI_CCL_RCP85, R_ECE_RCA_RCP85, R_ECE_RAC_RCP85, R_CNR_RAC_RCP85, R_NOR_R15_RCP85, R_CNR_ALA_RCP85, R_HAD_REG_RCP85, R_MPI_R09_RCP85])
elif sim_state == 'transient' :
    R_DRIAS_26 = numpy.nanmean([numpy.nanmean(R_MPI_CCL_RCP26), numpy.nanmean(R_ECE_RCA_RCP26), numpy.nanmean(R_ECE_RAC_RCP26), numpy.nanmean(R_CNR_RAC_RCP26), numpy.nanmean(R_NOR_R15_RCP26), numpy.nanmean(R_CNR_ALA_RCP26), numpy.nanmean(R_HAD_REG_RCP26), numpy.nanmean(R_MPI_R09_RCP26)])
    R_DRIAS_85 = numpy.nanmean([numpy.nanmean(R_MPI_CCL_RCP85), numpy.nanmean(R_ECE_RCA_RCP85), numpy.nanmean(R_ECE_RAC_RCP85), numpy.nanmean(R_CNR_RAC_RCP85), numpy.nanmean(R_NOR_R15_RCP85), numpy.nanmean(R_CNR_ALA_RCP85), numpy.nanmean(R_HAD_REG_RCP85), numpy.nanmean(R_MPI_R09_RCP85)])

#%% Calibration of K based on piezometry

from calibration import calib_root, calib_dichotomy, calib_exploration, calib_basis

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_dicot_hom_1v_k1'

BV.forcing.update_recharge(R_HAD_REG_RCP26, 'transient')
# BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
#                                   first_year = start_date.year, last_year = end_date.year, time_step = 'D',
#                                   sim_state = 'transient')

BV.hydrodynamic.update_thickness(30)

params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',0.1,1e-04,1e+02,'m/j','lin']
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(10)
# dicot = calib.dichotomy(gap=1)

#%% Extraction and analysis of K calibration results

import glob
import os
import numpy as np
from calibration import calib_analysis

params_file = 'calib_dicot_hom_1v_k1'

#get last calibration result file
type_obs = 'piezometry'
typ_calib = 'piezometry_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)
name_file = list_path[-1].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)
test.display_objective_function(save=None) #save='C:/.../'+params_file+'.png',vmax= 1.3,log=False

#get optimal K value
RMSE_list = [test.calib['params_values'][0][i][1] for i in range(len(test.calib['params_values'][0]))]
i_koptim = RMSE_list.index(min(RMSE_list))
koptim = test.calib['params_values'][0][i_koptim][0]
kr = koptim / np.nanmean(test.calib['recharge'])

#%% Calibration of n based on piezometry

from calibration import calib_root, calib_dichotomy, calib_exploration, calib_basis

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_explo_hom_n1'

BV.forcing.update_recharge(R_HAD_REG_RCP26, 'transient')
BV.hydrodynamic.update_thickness(30)

params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['n1',0.03,0.03,0.3,'-','log']
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(10)

#%% Extraction and analysis of n calibration results

import glob
import os
from calibration import calib_analysis

params_file = 'calib_explo_hom_n1'

#get last calibration result file
type_obs = 'piezometry'
typ_calib = 'piezometry_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)
name_file = list_path[-1].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)
test.display_objective_function(save=None) #save='C:/.../'+params_file+'.png',vmax= 1.3,log=False

#get optimal n value
RMSE_list = [test.calib['params_values'][0][i][1] for i in range(len(test.calib['params_values'][0]))]
i_n_optim = RMSE_list.index(min(RMSE_list))
n_optim = test.calib['params_values'][0][i_n_optim][0]

#%% Model Parameters

# Hydraulic properties
t = 30 # m
n = n_optim # nondim
K = koptim # m/j

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth

# Activation of modules
first_only = False # if True generate results only for the first time_step
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = True # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console

# Update properties
BV.hydrodynamic.update_hyd_cond(K)
BV.hydrodynamic.update_thickness(t)
BV.hydrodynamic.update_porosity(n)
BV.hydrodynamic.update_nlay(lay_number)
BV.hydrodynamic.update_bottom(bottom)
BV.hydrodynamic.update_thick_exp(thick_exp)
BV.hydrodynamic.update_cond_decay(cond_decay)

#%% Launch test simulation

R = R_HAD_REG_RCP26
sea_lev = MSL
sim_name = 'hor' + horiz + '_rech' + rech + '_climod' + modclim + '_sealev' + sealev
print(sim_name)

BV.oceanic.update_MSL(sea_lev)
BV.forcing.update_recharge(R, 'steady')

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

