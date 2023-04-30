# -*- coding: utf-8 -*-
"""
Created on Mon Jan 23 16:16:07 2023

@author: Martin Le Mesnil
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

# print(abspath(__file__))
# %% PATHS + watershed options

watershed_name = 'Saint-Germain-sur-Ay'
# Caen-la-Mer Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
dem_name = "BDALTI_norm-manch_75m.tif"
# sp_file = "C:/Users/Martin Le Mesnil/Travail/SIG/Couches_base/Administratif/region_normandie/normandie.shp" # None # specify a path if process start from a given shapefile

shp_file_dict = {'Saint-Germain-sur-Ay' : r'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp',
             'Agon-Coutainville' : r'C:\Users\Martin Le Mesnil\Travail\SIG\BV_RN2100\Agon-Coutainville\Agon_2_sea_extended.shp',
             'Barneville-Carteret' : r'C:\Users\Martin Le Mesnil\Travail\SIG\BV_RN2100\Barneville-Carteret\Barneville_2_sea_extended.shp',
             'Baie-du-Cotentin' : r'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Baie-du-cotentin/Carentan_2_sea.shp',
             'Caen-la-Mer' : 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Caen/Caen_2_sea.shp'}

esp_rech_dict = {'Saint-Germain-sur-Ay' : r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\SGA\aut_2022\rech_SGA_aut2022.csv',
             'Agon-Coutainville' : None,
             'Barneville-Carteret' : r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\LC\rech_LC_aut2022.csv',
             'Baie-du-Cotentin' : None,
             'Caen-la-Mer' : r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\CLM\rech_CLM_aut2022.csv'}

calib_zones_dict = {'Saint-Germain-sur-Ay' : r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_SGA.shp',
             'Agon-Coutainville' : r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_CMB.shp',
             'Barneville-Carteret' : r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_LC.shp',
             'Baie-du-Cotentin' : r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_BDC_3.shp',
             'Caen-la-Mer' : r'C:\Users\Martin Le Mesnil\Travail\SIG\zones_calib\shape_calib_zones_CLM.shp'}

if DIR[0] == 'd': #server
    shp_file = r'D:\mlemesnil\Data\BV_RN2100\SGA\SGA_2_sea.shp'
    # Path to the git repositoty home page
    git_path = r"D:\mlemesnil\HydroModPy\HydroModPy\CORE_COMM/"
    # Path to the data folder
    data_path = r"D:\mlemesnil\Data\HydroModPy/"
    # Path where the results will be stored
    out_path = r'D:\mlemesnil\HydroModPy\Output/'
    modflow_path = r'D:\mlemesnil\HydroModPy\Modflow' # add bin/ folder with necessary .exe
    ESPERE_recharge_path = r'D:\mlemesnil\Data\estim_ET\SGA\aut_2022\rech_SGA_aut2022.csv'
    shape_calib_zones_path = r'D:\mlemesnil\Data\HydroModPy\calib_zones\SGA\shape_calib_zones_SGA.shp'
elif DIR[0] == 'c': #local
    shp_file = shp_file_dict[watershed_name]
    git_path = r"C:/Users/Martin Le Mesnil/Travail/HydroModPy/HydroModPy/CORE_COMM/"
    data_path = r"C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/"
    out_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
    modflow_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/Modflow' # add bin/ folder with necessary .exe
    ESPERE_recharge_path = esp_rech_dict[watershed_name]
    shape_calib_zones_path = calib_zones_dict[watershed_name]
                            
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


# BV.add_drias(drias_path)
# BV.add_surfex(surfex_path) 
BV.add_hydrodynamic()
BV.add_oceanic(oceanic_path)
BV.add_forcing()
BV.add_hydrology(hydrology_path)

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
                              from_shp=shp_file,
                              from_dem=None,
                              cell_size=cell_size)

BV.load_object()
BV.add_hydrodynamic()
BV.add_oceanic(oceanic_path)
BV.add_piezometry()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% Add local piezometry and get time period
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

#%% ESPERE recharge
import pandas as pd

#load recharge time serie from ESPERE
with open(ESPERE_recharge_path, newline='') as csvfile:
    # rech_data = list(csv.reader(csvfile))
    rech_data = pd.read_csv(ESPERE_recharge_path, sep=';', decimal='.')
    if isinstance(rech_data.iloc[0,1], str):
        rech_data = pd.read_csv(ESPERE_recharge_path, sep=';', decimal=',')

r_ESP = rech_data.copy()
try:
    r_ESP = r_ESP.drop(['P','Peff'], axis=1)
except:
    r_ESP = r_ESP.drop(['P (mm)','Pluie efficace (mm)'], axis=1)
r_ESP = r_ESP.rename(index = pd.to_datetime(r_ESP['Date'], dayfirst=True))
r_ESP = r_ESP.drop('Date', axis=1)
r_ESP['Recharge'] = r_ESP['Recharge'].apply(lambda x: x/1000) #mm to m
r_ESP['Recharge'] = r_ESP['Recharge'].apply(lambda x: 3*x)

#%% Calibration of K based on streams

from calibration import calib_root
import pandas as pd

types_obs = ['streams_fr'] # list of shapefile name layers for clip hydrology
params_file = 'calib_K_streams'

R_mean_Surfex = (307/1000)/365
BV.forcing.update_recharge(R_mean_Surfex, 'steady')
BV.hydrodynamic.update_thickness(30)
# BV.hydrodynamic.update_porosity(0.25)
#init value is not used in exploration mode
#lin or log probably not used
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',0.1,0.001,10,'m/j','log']
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['streams']) 
dicot = calib.dichotomy(gap=1)

#%% Calibration of K and n based on piezometry

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_3R_k1n1' #calib_optim1_aut22_k1n1
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
# BV.hydrodynamic.update_porosity(0.25)
#init value is not used in exploration mode
#lin or log probably not used
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',0.002,0.002,2,'m/j','log']
params_df.loc[1] = ['n1',0.001,0.001,0.1,'-','lin']
#params_df.loc[0] = ['k1',0.001,0.001,1e+02,'m/j','lin']
#params_df.loc[0] = ['k1',0.1,1e-04,1e+02,'m/j','lin']
#params_df.loc[1] = ['n1',0.03,0.03,0.3,'-','lin']
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(200)


#%% Extraction and analysis of K-n calibration results

import glob
import os
from calibration import calib_analysis

params_file = 'calib_4Pzs_k1n1' # calib_optim1_aut22_k1n1 calib_explo_aut22_k1n1 calib_explo_hom_K1n1 calib_explo_MF_K1n1 calib_explo_test6piezos_K1n1

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

shape = BV.hydrodynamic.update_calib_zones_from_shp(shape_calib_zones_path)


from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_hetero_steady_P2P3_k1k2' #'calib_hetero_perm_k1k2' calib_hetero_steady_P4P6_k1k2
# calib_hetero_steady_P1P3_k1k2 calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'steady') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',0.0001,0.0001,10,'m/j','log']
params_df.loc[1] = ['k2',0.0001,0.0001,10,'m/j','log']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(00)


#%% Extraction and analysis of heterogeneous K calibration results - steady

import glob
import os
from calibration import calib_analysis

params_file = 'calib_hetero_steady_P2P3_k1k2' #calib_hetero_steady_P1P3_k1k2' # calib_hetero_perm_k1k2 calib_explo_hom_K1n1 calib_explo_MF_K1n1 calib_explo_test6piezos_K1n1

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
params_file = 'calib_hetero_transient_n1n2_P2P3' #calib_hetero_transient_n1n2_P1P3_halfkcalib_hetero_transient_n1n2_P4P6_t28
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
# BV.hydrodynamic.update_hyd_cond(0.387)
shape = BV.hydrodynamic.update_calib_zones_from_shp(shape_calib_zones_path)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 1, hyd_cond_value = K1_optim) #0.1333521432163324
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 2, hyd_cond_value = K2_optim) #0.21544346900318845

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
shape = BV.hydrodynamic.update_calib_zones_from_shp(shape_calib_zones_path)

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

params_file = 'calib_hetero_transient_n1n2_P2P3' #calib_hetero_transient_n1n2_P1P3_halfk' # calib_hetero_transient_n1n2_P4P6_t28 calib_hetero_transient_n1n2_P4P6 calib_hetero_transient_n1n2_Khomo calib_explo_hom_K1n1 calib_explo_MF_K1n1 calib_explo_test6piezos_K1n1
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

# shape = BV.hydrodynamic.update_calib_zones_from_shp(shape_calib_zones_path)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 1, porosity_value = n1_optim)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 2, porosity_value = n2_optim)

# porosity_zones = BV.hydrodynamic.porosity

#%% Visualization of calibration - hetero


from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_test' #'calib_hetero_perm_k1k2' calib_hetero_transient_n1n2_P4P6_t28
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
shape = BV.hydrodynamic.update_calib_zones_from_shp(shape_calib_zones_path)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 1, hyd_cond_value = 0.21)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone = 2, hyd_cond_value = 2.3)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 1, porosity_value = n1_optim)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone = 2, porosity_value = n2_optim)
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
# params_df.loc[0] = ['k1',3.875,3.875,3.875,'m/j','log']
# params_df.loc[1] = ['k2',0.444,0.444,0.444,'m/j','log']
n1 = 0.01
n2 = 0.015
params_df.loc[0] = ['n1',n1,n1,n1,'-','lin']
params_df.loc[1] = ['n2',n2,n2,n2,'-','lin']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(1)

#%% Visualization of calibration - homo

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_test' #'calib_hetero_perm_k1k2'
# calib_explo_synop_K1n1 calib_explo_test6piezos_K1n1 calib_explo_hom_n1
k = 0.127
n = 0.0158

BV.forcing.update_recharge(r_ESP, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(29)
BV.hydrodynamic.update_hyd_cond(k)
BV.hydrodynamic.update_porosity(n)
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',k,k,k,'m/j','log']
params_df.loc[1] = ['n1',n,n,n,'-','lin']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(1)

