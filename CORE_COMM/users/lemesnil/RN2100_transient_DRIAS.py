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
import imageio.v2 as imageio
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
# Caen-la-Mer Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
dem_name = "BDALTI_norm-manch_75m.tif"
# sp_file = "C:/Users/Martin Le Mesnil/Travail/SIG/Couches_base/Administratif/region_normandie/normandie.shp" # None # specify a path if process start from a given shapefile

if DIR[0] == 'd': #server
    shp_file = 'D:\mlemesnil\Data\BV_RN2100\SGA\SGA_2_sea.shp'
    # Path to the git repositoty home page
    git_path = "D:\mlemesnil\HydroModPy\HydroModPy\CORE_COMM/"
    # Path to the data folder
    data_path = "D:\mlemesnil\Data\HydroModPy/"
    # Path where the results will be stored
    out_path = 'D:\mlemesnil\HydroModPy\Output/'
    modflow_path = 'D:\mlemesnil\HydroModPy\Modflow' # add bin/ folder with necessary .exe
    ESPERE_recharge_path = 'D:\mlemesnil\Data\estim_ET\SGA\aut_2022\rech_SGA_aut2022.csv'
    shape_calib_zones_path = 'D:\mlemesnil\Data\HydroModPy\calib_zones\SGA\shape_calib_zones_SGA.shp'
elif DIR[0] == 'c': #local
    shp_file = 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'
    # 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Caen/Caen_2_sea.shp'
    # 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Baie-du-Cotentin/watershed_clip_carentan.shp'
    # 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'
    git_path = "C:/Users/Martin Le Mesnil/Travail/HydroModPy/HydroModPy/CORE_COMM/"
    data_path = "C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/"
    out_path = 'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
    modflow_path = 'C:/Users/Martin Le Mesnil/Travail/HydroModPy/Modflow' # add bin/ folder with necessary .exe
    ESPERE_recharge_path = r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\SGA\aut_2022\rech_SGA_aut2022.csv'
    # C:\Users\Martin Le Mesnil\Travail\data\estim_ET\rech_CLM_aut2022.csv
    #r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\rech_CLM_2022.csv'
    shape_calib_zones_path = r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp'
    
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
surfex_path =  data_path # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = data_path + 'OCEAN/' # add specific sea level files
hydrology_path = data_path + 'hydro/' # add hydrographic shapefiles
# hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
# intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points
drias_path = data_path + "CLIMAT/Normandie/"
library_path = git_path + 'watershed/watershed_library.csv' # each row is a study site with outlet coordinates
dems_path = data_path # reginal DEM or conceptual DEM
dem_path = dems_path + dem_name
cell_size = None # specify new resolution from a given DEM or None

#%% Watershed generation

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=False,
                              from_shp=shp_file,
                              from_dem=False,
                              cell_size=cell_size)


BV.add_drias(drias_path)
BV.add_surfex(surfex_path) 
BV.add_hydrodynamic()
BV.add_oceanic(oceanic_path)

# BV.add_geology(geology_path)

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
                              from_dem=None,
                              cell_size=cell_size)

BV.load_object()
BV.add_hydrodynamic()
BV.add_oceanic(oceanic_path)
# BV.add_piezometry()

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
                                      first_year = 1965, last_year = 2014, 
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

# #%% Climatic tests

# BV.add_forcing()
# clim = BV.climatic.values


# #%% Calibration of K based on piezometry

# from calibration import calib_root, calib_dichotomy, calib_exploration, calib_basis

# types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
# params_file = 'calib_dicot_hom_1v_k1'

# BV.forcing.update_recharge(R_HAD_REG_RCP26, 'transient')
# # BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
# #                                   first_year = start_date.year, last_year = end_date.year, time_step = 'D',
# #                                   sim_state = 'transient')

# BV.hydrodynamic.update_thickness(30)

# params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
# params_df.loc[0] = ['k1',0.1,1e-04,1e+02,'m/j','lin']
# params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=',', index=None)

# calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
# calib.exploration(10)
# # dicot = calib.dichotomy(gap=1)

# #%% Extraction and analysis of K calibration results

# import glob
# import os
# import numpy as np
# from calibration import calib_analysis

# params_file = 'calib_dicot_hom_1v_k1'

# #get last calibration result file
# type_obs = 'piezometry'
# typ_calib = 'piezometry_calibration'
# list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
#                    key=os.path.getmtime)
# name_file = list_path[-1].split('\\')[-1]
# calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
# test = calib_analysis.CalibAnalysis(calib_file)
# test.display_objective_function(save=None) #save='C:/.../'+params_file+'.png',vmax= 1.3,log=False

# #get optimal K value
# RMSE_list = [test.calib['params_values'][0][i][1] for i in range(len(test.calib['params_values'][0]))]
# i_koptim = RMSE_list.index(min(RMSE_list))
# koptim = test.calib['params_values'][0][i_koptim][0]
# kr = koptim / np.nanmean(test.calib['recharge'])

# #%% Calibration of n based on piezometry

# from calibration import calib_root, calib_dichotomy, calib_exploration, calib_basis

# types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
# params_file = 'calib_explo_hom_n1'

# BV.forcing.update_recharge(R_HAD_REG_RCP26, 'transient')
# BV.hydrodynamic.update_thickness(30)

# params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
# params_df.loc[0] = ['n1',0.03,0.03,0.3,'-','log']
# params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=',', index=None)

# calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
# calib.exploration(10)

# #%% Extraction and analysis of n calibration results

# import glob
# import os
# from calibration import calib_analysis

# params_file = 'calib_explo_hom_n1'

# #get last calibration result file
# type_obs = 'piezometry'
# typ_calib = 'piezometry_calibration'
# list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
#                    key=os.path.getmtime)
# name_file = list_path[-1].split('\\')[-1]
# calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
# test = calib_analysis.CalibAnalysis(calib_file)
# test.display_objective_function(save=None) #save='C:/.../'+params_file+'.png',vmax= 1.3,log=False

# #get optimal n value
# RMSE_list = [test.calib['params_values'][0][i][1] for i in range(len(test.calib['params_values'][0]))]
# i_n_optim = RMSE_list.index(min(RMSE_list))
# n_optim = test.calib['params_values'][0][i_n_optim][0]

#%% ESPERE recharge
import pandas as pd

#load recharge time serie from ESPERE
with open(ESPERE_recharge_path, newline='') as csvfile:
    # rech_data = list(csv.reader(csvfile))
    rech_data = pd.read_csv(ESPERE_recharge_path, sep=';', decimal=',')

r_ESP = rech_data.copy()
try:
    r_ESP = r_ESP.drop(['P','Peff'], axis=1)
except:
    r_ESP = r_ESP.drop(['P (mm)','Pluie efficace (mm)'], axis=1)
r_ESP = r_ESP.rename(index = pd.to_datetime(r_ESP['Date'], dayfirst=True))
r_ESP = r_ESP.drop('Date', axis=1)
r_ESP['Recharge'] = r_ESP['Recharge']/1000 #mm to m

#%% Calibration of K and n based on piezometry

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_optim1_aut22_k1n1' #calib_optim1_aut22_k1n1
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
# BV.hydrodynamic.update_porosity(0.25)
#init value is not used in exploration mode
#lin or log probably not used
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',0.387,0.387,0.387,'m/j','log']
params_df.loc[1] = ['n1',0.0127,0.0127,0.0127,'-','lin']
#params_df.loc[0] = ['k1',0.001,0.001,1e+02,'m/j','lin']
#params_df.loc[0] = ['k1',0.1,1e-04,1e+02,'m/j','lin']
#params_df.loc[1] = ['n1',0.03,0.03,0.3,'-','lin']
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(1)


#%% Extraction and analysis of K-n calibration results

import glob
import os
from calibration import calib_analysis

params_file = 'calib_explo_aut22_k1n1' # calib_optim1_aut22_k1n1 calib_explo_aut22_k1n1 calib_explo_hom_K1n1 calib_explo_MF_K1n1 calib_explo_test6piezos_K1n1

#get last calibration result file
type_obs = 'piezometry'
typ_calib = 'piezometry_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)
name_file = list_path[-1].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)
obj_fc_path = os.path.join(BV.calibration_folder, params_file, typ_calib, '_figures', 'objective_function.png')
test.display_objective_function(save=obj_fc_path) #,vmax= 1.3,log=False

#get optimal K and n value
calib_dict = test.calib
K_values = calib_dict['params_values'][0]
n_values = calib_dict['params_values'][1]

min_RMSE_idx_flat = np.argmin(calib_dict['objective_function'])
i_min_RMSE = min_RMSE_idx_flat // n_values.size
j_min_RMSE = min_RMSE_idx_flat % n_values.size    
RMSE_optim = calib_dict['objective_function'][i_min_RMSE, j_min_RMSE]
K_optim = K_values[j_min_RMSE]
n_optim = n_values[i_min_RMSE]

#%% Heterogeneous calibration of K based on piezometry - steady state

shape = BV.hydrodynamic.update_calib_zones_from_shp(r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp')


from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_hetero_steady_P1P3_k1k2' #'calib_hetero_perm_k1k2' calib_hetero_steady_P4P6_k1k2
# calib_hetero_steady_P1P3_k1k2 calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'steady') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',0.001,0.001,100,'m/j','log']
params_df.loc[1] = ['k2',0.001,0.001,100,'m/j','log']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(400)


#%% Extraction and analysis of heterogeneous K calibration results - steady

import glob
import os
from calibration import calib_analysis

params_file = 'calib_hetero_steady_P1P3_k1k2' # calib_hetero_perm_k1k2 calib_explo_hom_K1n1 calib_explo_MF_K1n1 calib_explo_test6piezos_K1n1

#get last calibration result file
type_obs = 'piezometry'
typ_calib = 'piezometry_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)
name_file = list_path[-1].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)
obj_fc_path = os.path.join(BV.calibration_folder, params_file, typ_calib, '_figures', 'objective_function.png')
test.display_objective_function(save=obj_fc_path) #,vmax= 1.3,log=False

#get optimal K and n value
calib_dict = test.calib
K1_values = calib_dict['params_values'][0]
K2_values = calib_dict['params_values'][1]

min_RMSE_idx_flat = np.argmin(calib_dict['objective_function'])
i_min_RMSE = min_RMSE_idx_flat // K2_values.size
j_min_RMSE = min_RMSE_idx_flat % K2_values.size    
RMSE_optim = calib_dict['objective_function'][i_min_RMSE, j_min_RMSE]
K1_optim = K1_values[j_min_RMSE]
K2_optim = K2_values[i_min_RMSE]

shape = BV.hydrodynamic.update_calib_zones_from_shp(r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp')
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 1, hyd_cond_value = K1_optim)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 2, hyd_cond_value = K2_optim)

hyd_cond_zones = BV.hydrodynamic.hyd_cond

#%% Heterogeneous calibration of n based on piezometry - transient state

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_hetero_transient_n1n2_P1P3_halfk' #calib_hetero_transient_n1n2_P4P6_t28
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
# BV.hydrodynamic.update_hyd_cond(0.387)
shape = BV.hydrodynamic.update_calib_zones_from_shp(r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp')
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 1, hyd_cond_value = 2.64/2)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 2, hyd_cond_value = 0.428/2)

params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['n1',0.001,0.001,0.3,'-','lin']
params_df.loc[1] = ['n2',0.001,0.001,0.3,'-','lin']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(300)

#%% Heterogeneous calibration of K based on piezometry - transient state

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_hetero_transient_k1k2_nhomo'
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
# BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 1, hyd_cond_value = K1_optim)
# BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 2, hyd_cond_value = K2_optim)
# BV.hydrodynamic.update_hyd_cond(0.387)
BV.hydrodynamic.update_porosity(0.0127)
shape = BV.hydrodynamic.update_calib_zones_from_shp(r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp')

params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',0.001,0.001,10,'m/j','log']
params_df.loc[1] = ['k2',0.001,0.001,10,'m/j','log']
# params_df.loc[0] = ['k1',0.001,0.001,0.4,'-','lin']
# params_df.loc[1] = ['n2',0.001,0.001,0.4,'-','lin']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(250)

#%% Extraction and analysis of heterogeneous n calibration results - transient

import glob
import os
from calibration import calib_analysis

params_file = 'calib_hetero_transient_n1n2_P1P3_halfk' # calib_hetero_transient_n1n2_P4P6_t28 calib_hetero_transient_n1n2_P4P6 calib_hetero_transient_n1n2_Khomo calib_explo_hom_K1n1 calib_explo_MF_K1n1 calib_explo_test6piezos_K1n1
# calib_hetero_transient_n1n2_P1P3_halfk
#get last calibration result file
type_obs = 'piezometry'
typ_calib = 'piezometry_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)
name_file = list_path[-1].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)
obj_fc_path = os.path.join(BV.calibration_folder, params_file, typ_calib, '_figures', 'objective_function.png')
test.display_objective_function(save=obj_fc_path) #,vmax= 1.3,log=False

#get optimal K and n value
calib_dict = test.calib
n1_values = calib_dict['params_values'][0]
n2_values = calib_dict['params_values'][1]

min_RMSE_idx_flat = np.argmin(calib_dict['objective_function'])
i_min_RMSE = min_RMSE_idx_flat // n1_values.size
j_min_RMSE = min_RMSE_idx_flat % n2_values.size    
RMSE_optim = calib_dict['objective_function'][i_min_RMSE, j_min_RMSE]
n1_optim = n1_values[j_min_RMSE]
n2_optim = n2_values[i_min_RMSE]

# shape = BV.hydrodynamic.update_calib_zones_from_shp(r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp')
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 1, porosity_value = n1_optim)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 2, porosity_value = n2_optim)

# porosity_zones = BV.hydrodynamic.porosity

#%% Visualization of calibration - hetero

shape = BV.hydrodynamic.update_calib_zones_from_shp(r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp')


from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_test' #'calib_hetero_perm_k1k2' calib_hetero_transient_n1n2_P4P6_t28
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
shape = BV.hydrodynamic.update_calib_zones_from_shp(r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp')
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 1, hyd_cond_value = 2.01)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 2, hyd_cond_value = 0.267)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 1, porosity_value = n1_optim)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 2, porosity_value = n2_optim)
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
# params_df.loc[0] = ['k1',3.875,3.875,3.875,'m/j','log']
# params_df.loc[1] = ['k2',0.444,0.444,0.444,'m/j','log']
params_df.loc[0] = ['n1',0.138,0.138,0.138,'-','lin']
params_df.loc[1] = ['n2',0.0393,0.0393,0.0393,'-','lin']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(1)

#%% Visualization of calibration - homo

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_test' #'calib_hetero_perm_k1k2'
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
BV.hydrodynamic.update_hyd_cond(1.7)
BV.hydrodynamic.update_porosity(0.13)
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',0.02,0.02,0.02,'m/j','log']
params_df.loc[1] = ['n1',0.001,0.001,0.001,'m/j','log']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(1)

#%% Model Parameters

hetero = 1

# K_optim = 0.3
# n_optim = 0.001

# Hydraulic properties
t = 29 # m

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth

# Activation of modules
first_only = False # if True generate results only for the first time_step
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = False # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console

# Update properties
if hetero==0:
    n = n_optim # nondim
    K = K_optim # m/j
    BV.hydrodynamic.update_hyd_cond(K)
    BV.hydrodynamic.update_porosity(n)
elif hetero==1:
    K1 = 2.01
    K2 = 0.267
    n1 = 0.138
    n2 = 0.0393
    shape = BV.hydrodynamic.update_calib_zones_from_shp(shape_calib_zones_path)
    BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 1, hyd_cond_value = K1)
    BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 2, hyd_cond_value = K2)
    BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 1, porosity_value = n1)
    BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 2, porosity_value = n2)

BV.hydrodynamic.update_thickness(t)
BV.hydrodynamic.update_nlay(lay_number)
BV.hydrodynamic.update_bottom(bottom)
BV.hydrodynamic.update_thick_exp(thick_exp)
BV.hydrodynamic.update_cond_decay(cond_decay)

#%% Launch simulations and save results

import deepdish as dd
from groundwater_flow import modflow_display
import numpy as np
import pandas as pd
from datetime import datetime

BV.add_forcing()
sim_state = 'transient'
first_yr = 2020
last_yr = 2100

RMSL_85 = BV.oceanic.RMSL["RCP8.5"]
md_rmsl_85 = RMSL_85.iloc[:,0]
RMSL_26 = BV.oceanic.RMSL["RCP2.6"]
md_rmsl_26 = RMSL_26.iloc[:,0]
# md_rmsl_85_cut = ...

list_sim_name = []
list_success = []
list_flow_model = []
list_recharge = []
list_sealevel = []

DRIAS_model_list = ['MPI-R09'] #['MPI-R09', 'HAD-REG', 'CNR-ALA', 'NOR-R15', 'CNR-RAC', 'ECE-RAC', 'ECE-RCA', 'MPI-CCL']
sce_list = ['RCP2.6'] #[['RCP2.6', 'RCP8.5']

for DRIAS_model in DRIAS_model_list:
    for scenario in sce_list:
    
        gcm = DRIAS_model[:3] #'MPI'
        rcm = DRIAS_model[-3:] #'CCL'
        sce = scenario #'RCP8.5'
        BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                          first_year = first_yr, last_year = last_yr,
                                          sim_state = sim_state)
        # BV.forcing.update_recharge(R_hist, 'transient')
        if scenario == 'RCP2.6':
            BV.oceanic.update_MSL(md_rmsl_26)
        elif scenario == 'RCP8.5':
            BV.oceanic.update_MSL(md_rmsl_85)
        
        now = datetime.now()
        now_str = now.strftime("%d%m%Y%H%M%S")
        sim_name = str(first_yr)+str(last_yr) + '_' + gcm+rcm+ sce.replace('.', '') + '_' + now_str
        # sim_name = str(first_yr)+str(last_yr) + '_REA_' + now_str
        print(sim_name)
    
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
        
        list_sim_name.append(sim_name)
        list_success.append(success)
        list_flow_model.append(flow_model)
        list_recharge.append(BV.forcing.recharge)
        list_sealevel.append(BV.oceanic.MSL)

# sim_results_dict = {}
# sim_results_dict['sim_name'] = list_sim_name
# sim_results_dict['success'] = list_success
# sim_results_dict['recharge'] = list_recharge
# sim_results_dict['sealevel'] = list_sealevel

# h5file = simulations_folder+'/'+sim_name+'/sim_results.h5'
# dd.io.save(h5file, sim_results_dict)


##%% Post processing 1: raster generation and storage
# import deepdish as dd

time_step = 'D' # DMY
actual_date = True # False if date is conceptual
types_obs = ['piezometry']

# h5file = simulations_folder+'/'+sim_name+'/sim_results.h5'
# d = dd.io.load(h5file)
# list_sim_name = d['sim_name'][:]
# list_success = d['success'][:]
# list_flow_model = d['flow_model'][:]
# list_runoff = d['runoff'][:]

for sim_name, success, flow_model, recharge, sealevel in zip(list_sim_name,
                                                     list_success,
                                                     list_flow_model,
                                                     list_recharge,
                                                     list_sealevel):

    if success == True:
            print(success)
            
            BV.matrix_modflow(success,
                              flow_model,
                              first_only = True,
                              watertable_elevation = True,
                              watertable_depth = True, 
                              seepage_areas = True,
                              outflow_drain = False,
                              groundwater_flux = False,
                              specific_discharge = False,
                              accumulation_flux = False,
                              perenn_intermit_shp = False,
                              groundwater_storage = False,
                              residence_times = False,
                              verbose = True,
                              export_tif = True)
            
            # Necessary for results_modflow
            runoff = recharge # warning: runoff is set at recharge value to debug
            
            # Extract results
            BV.results_modflow(ident=sim_name,
                               recharge=recharge,
                               runoff=runoff,
                               actual_date=actual_date,
                               time_step=time_step)
            
            ## Plot maps
            # surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
            #                                       sim_name, types_obs,
            #                                       save_gif=False,
            #                                       first_only=True,
            #                                       sim_state=sim_state,
            #                                       outflow=True,
            #                                       accflux=True,
            #                                       intermittency=False,
            #                                       chronics=False)


