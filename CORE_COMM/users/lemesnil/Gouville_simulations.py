# -*- coding: utf-8 -*-
"""
Created on Thu Mar 30 11:31:05 2023

@author: Martin Le Mesnil
"""

#%% LIBRARIES

# General
import os
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
sys.path.append(os.path.join(DIR, 'users', 'lemesnil'))
import matplotlib.pyplot as plt

# Gis
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
                 
# HydroModPy + personal functions
from watershed import watershed_root, watershed_display

# %% PATHS + watershed options

watershed_name = 'Gouville'
dem_name = "MNT_fus.tif" #MNT_Gouville_large.tif

if DIR[0] == 'd': #server
    shape_path = r'D:\mlemesnil\Data\BV_RN2100\Gouville\zone_modele.shp'
    dems_path =r'D:\mlemesnil\Data\BV_RN2100\Gouville/'
    # Path to the git repositoty home page
    git_path = r"D:\mlemesnil\HydroModPy\HydroModPy\CORE_COMM/"
    # Path to the data folder
    data_path = r"D:\mlemesnil\Data\HydroModPy/"
    # Path where the results will be stored
    out_path = r'D:\mlemesnil\HydroModPy\Output/'
    modflow_path = r'D:\mlemesnil\HydroModPy\Modflow' # add bin/ folder with necessary .exe
    data_folder = r'D:\mlemesnil\Data\piezo_gouville'
elif DIR[0] == 'c': #local
    git_path = r"C:/Users/Martin Le Mesnil/Travail/HydroModPy/HydroModPy/CORE_COMM/"
    data_path = r"C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/"
    out_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
    modflow_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/Modflow' # add bin/ folder with necessary .exe
    dems_path = r'C:\Users\Martin Le Mesnil\Travail\SIG\Gouville/'
    shape_path = r'C:\Users\Martin Le Mesnil\Travail\SIG\Gouville\zone_modele_west_ext.shp'
    data_folder = r'C:\Users\Martin Le Mesnil\Travail\Articles\Analytical\data_gouville\extraction'
    shape_calib_zones_path = r"C:\Users\Martin Le Mesnil\Travail\SIG\Gouville\calib_zones_west.shp"
    
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
surfex_path =  data_path +'REA-DAYON/' # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = data_path + 'OCEAN/' # add specific sea level files
hydrology_path = data_path + 'hydro/' # add hydrographic shapefiles
# hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
# intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points
drias_path = data_path + "CLIMAT/Normandie/"
library_path = git_path + 'watershed/watershed_library.csv' # each row is a study site with outlet coordinates
dem_path = dems_path + dem_name
cell_size = None # specify new resolution from a given DEM or None


#%% Watershed generation

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=True,
                              from_shp=shape_path,
                              from_dem=False,
                              cell_size=cell_size)

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

BV.add_piezometry()
# BV.add_surfex(surfex_path)
BV.add_hydrodynamic()
BV.add_oceanic(oceanic_path)


#%% Piezometry extraction
import pandas as pd

code = '01423X0044/F4'

desc_file = os.path.join(data_folder,'ades_export','Descriptif','descriptif.txt')
df1 = pd.read_csv(desc_file, delimiter = '|',header=0, engine='python', encoding='latin1')
depth_well = df1['Profondeur investigation maximale'][0]
piezo_NGF_df_well = df1['Altitude'][0]
file = os.path.join(data_folder, 'ades_export','Quantite','chroniques.txt')
df = pd.read_csv(file, delimiter = '|',header=0, engine='python', encoding='latin1')
piezo_NGF_df = df[['Date de la mesure','Côte NGF']]
piezo_NGF_df.columns = ['Date', 'NGF']
piezo_NGF_df.index = piezo_NGF_df['Date'] #pd.to_datetime(piezo_NGF_df['Date'],format='%d/%m/%Y %H:%M:%S')
piezo_NGF_df = piezo_NGF_df.drop(['Date'], axis=1)
piezo_NGF_df.columns = [code]

filename = 'piezometry_' + str.replace(code, '/', '') + '_363782_6897114_9.2_10' + '.csv' #_363782_6897114_9.2_10  _363400_6897114_9.2_10
piezo_add_path = os.path.join(stable_folder, 'add_data',  filename)
piezo_NGF_df.to_csv(piezo_add_path, sep = ';')

BV.add_forcing()
BV.piezometry.add_data()
BV.piezometry.display_data()

#%% Surfex extraction

first_yr = 2016
last_yr = 2016
sce = 'historic'
mod = 'REA'

BV.add_forcing()
BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                  first_year = first_yr, last_year = last_yr, 
                                  time_step = 'D', sim_state = 'transient')
rech = BV.forcing.recharge
rech_cut = rech.iloc[0:10]
rech_cut_mean_int = rech_cut.values.mean()

rech_cut_mean = rech_cut.copy()
for i in range(len(rech_cut)):
    rech_cut_mean.iloc[i] = rech_cut_mean_int

plt.plot(rech)

#%% Sea level extraction

from SHOM_process import SHOM
import numpy as np

maregraph = 'St-Malo'
first_yr = 2016
last_yr = 2016

sea_lev_df = SHOM(maregraph, first_yr, last_yr)
sea_lev_df_interp = sea_lev_df.interpolate()
sea_lev_df_fill = sea_lev_df.fillna(sea_lev_df.mean())
sea_lev_df_fill = sea_lev_df_fill
sea_lev = sea_lev_df_fill['Valeur'].values.tolist()
sea_lev_mean = np.mean(sea_lev)

sea_lev_cut = sea_lev[0:10]
sea_lev_cut_mean = np.mean(sea_lev_cut)

plt.plot(sea_lev)

#%% Homogeneous calibration

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_test' #calib_optim1_aut22_k1n1

BV.forcing.update_recharge(rech_cut, 'transient')
BV.oceanic.update_MSL(sea_lev_cut)

BV.hydrodynamic.update_thickness(20)
params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['k1',75,75,75,'m/j','log']
params_df.loc[1] = ['n1',0.1,0.1,0.1,'-','lin']
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry'])
calib.exploration(1)
fig1 = plt.gcf()
fig1.savefig('C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/Gouville\\results_calibration/calib_test_fig', dpi=200)
plt.imsave('C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/Gouville\\results_calibration/calib_test_fig')

#%% Homogeneous calibration - automated scenarios

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_test' #calib_optim1_aut22_k1n1

BV.forcing.update_recharge(rech_cut, 'transient')
BV.oceanic.update_MSL(sea_lev_cut)

thick_list = [10, 20, 30]
k_list = [.1, 1, 10, 100, 1000]
n_list = [.02, .1, .3]
for T in thick_list:
    for K in k_list:
        for n in n_list:
            BV.hydrodynamic.update_thickness(T)
            params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
            params_df.loc[0] = ['k1',K,K,K,'m/j','log']
            params_df.loc[1] = ['n1',n,n,n,'-','lin']
            params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
            
            calib = calib_root.Calibration(params_file, BV, observations = ['piezometry'])
            calib.exploration(1)
            


#%% Heterogeneous calibration 

from calibration import calib_root
import pandas as pd

types_obs = ['piezometry'] # list of shapefile name layers for clip hydrology
params_file = 'calib_hetero_test' #calib_hetero_transient_n1n2_P1P3_halfkcalib_hetero_transient_n1n2_P4P6_t28

BV.forcing.update_recharge(rech, 'transient') #R_HAD_REG_RCP26
BV.hydrodynamic.update_thickness(30)

shape = BV.hydrodynamic.update_calib_zones_from_shp(shape_calib_zones_path)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone=1, hyd_cond_value=25)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(num_zone=2, hyd_cond_value=2)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone=1, porosity_value=0.1)
# BV.hydrodynamic.update_porosity_from_calib_zones(num_zone=2, porosity_value=0.05)

params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
params_df.loc[0] = ['n1',0.1,0.1,0.1,'-','lin']
params_df.loc[1] = ['n2',0.05,0.05,0.05,'-','lin']

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['piezometry']) 
calib.exploration(1)


