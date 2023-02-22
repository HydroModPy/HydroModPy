# -*- coding: utf-8 -*-
"""
Created on Mon Sep 26 10:41:39 2022

@author: Martin Le Mesnil
"""

#%% LIBRARIES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
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
# Caen-la-Mer Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
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

cell_size = None # specify new resolution from a given DEM or None

#%% GENERATING WATERSHED + data
# We propose 4 tests :
    # 1 - From a outlet coordinates : 'Outlet'
    # 2 - From a shpaefile : 'Shapefile'
    # 3 - From an actual DEM : 'Dem'
    # 4 - From a conceptual DEM : 'Conceptual'

import os

shp_file = 'C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'
# os.path.join('C', 'Users', 'Martin Le Mesnil', 'Travail', 'SIG', 'BV_RN2100', 'SGA_2_sea_2.shp')
# shp_file = r'C:\Users\Martin Le Mesnil\Travail\SIG\BV_RN2100\Baie-du-cotentin/Carentan_2_sea.shp'
# 'C:/Users/Martin/Desktop/Travail/SIG/BV_RN2100/Caen/watershed_clip_caen_2.shp'
# 'C:/Users/Martin/Desktop/Travail/SIG/BV_RN2100/Baie-du-Cotentin/watershed_clip_carentan.shp'
# '‪C:/Users/Martin Le Mesnil/Travail/SIG/BV_RN2100/Saint-Germain-sur-Ay/SGA_2_sea.shp'
# 'C:\Users\Martin Le Mesnil\Travail\SIG\BV_RN2100\Baie-du-cotentin\Carentan_2_sea.shp'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=True,
                              from_shp=shp_file,
                              from_dem=False,
                              cell_size=None)

types_obs = ['streams_fr'] # list of shapefile name layers for clip hydrology
fields_obs = ['FID'] # list of shapefile name columns to translate as a tif

# create watershed properties
BV.add_hydrodynamic()
BV.add_forcing()
BV.add_surfex(surfex_path) 
# BV.add_geology(geology_path) 
# BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
# BV.add_oceanic(oceanic_path)
# BV.add_hydrometry(hydrometry_path)
# BV.add_intermittency(intermittency_path)
# if piezometry_path == True:
#     BV.add_piezometry()
# if subbasin_path == True:
#     BV.add_subbasin()

# DRIAS climate data extraction
# BV.add_drias(r"C:/Users/Martin Le Mesnil/Travail/data/data_test_ronan/CLIMAT/Normandie/")

# BV.save_object()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% Historic recharge & ETP (for ET estimation)

start_year = 1960 #start year for shortened time series, complete series start at 1958
minimum_yearly_rainfall = 400 # remove outliers

import matplotlib.pyplot as plt
from scipy.ndimage import uniform_filter1d
import numpy as np
from sklearn.linear_model import LinearRegression

climatic_values = BV.climatic.values
ETP_df = climatic_values['REA']['ETP']['historic']
ETP_list = ETP_df.loc[:,'MEAN'].tolist()
PPT_df = climatic_values['REA']['PPT']['historic']
PPT_list = PPT_df.loc[:,'MEAN'].tolist()
REC_df = climatic_values['REA']['REC']['historic']
REC_list = REC_df.loc[:,'MEAN'].tolist()

#compute mean Day Of Year ETP of 20 last years
ETP_df['doy'] = ETP_df.index.dayofyear
ETP_df['year'] = ETP_df.index.year
ETP_df_recent = ETP_df[ETP_df['year']>=start_year]
piv = pd.pivot_table(ETP_df_recent, index=['doy'],columns=['year'], values=['MEAN'])

doy_ETP = []
for i in range(1,len(piv)): #doy 366 ommited
    doy_ETP.append(piv.loc[i].mean())
doy_ETP = pd.Series(doy_ETP)

#compute mean Day Of Year recharge of 20 last years
REC_df['doy'] = REC_df.index.dayofyear
REC_df['year'] = REC_df.index.year
REC_df_recent = REC_df[REC_df['year']>=start_year]
piv_rec = pd.pivot_table(REC_df_recent, index=['doy'],columns=['year'], values=['MEAN'])

doy_REC = []
for i in range(1,len(piv_rec)): #doy 366 ommited
    doy_REC.append(piv_rec.loc[i].mean())
doy_REC = pd.Series(doy_REC)

#compute mean Day Of Year rainfall of 20 last years
PPT_df['doy'] = PPT_df.index.dayofyear
PPT_df['year'] = PPT_df.index.year
PPT_df_recent = PPT_df[PPT_df['year']>=start_year]
piv_ppt = pd.pivot_table(PPT_df_recent, index=['doy'],columns=['year'], values=['MEAN'])

doy_PPT = []
for i in range(1,len(piv_ppt)): #doy 366 ommited
    doy_PPT.append(piv_ppt.loc[i].mean())
doy_PPT = pd.Series(doy_PPT)


#Get relationship between surfex yearly rainfall and recharge
piv_rec_yr = piv_rec.sum(axis=0)
piv_ppt_yr = piv_ppt.sum(axis=0)
rec_yr_list = piv_rec_yr.tolist()
ppt_yr_list = piv_ppt_yr.tolist()

if minimum_yearly_rainfall != None:
    idx_to_remove = [] #remove outliers
    for i in range(len(ppt_yr_list)):
        if ppt_yr_list[i]<minimum_yearly_rainfall:
            idx_to_remove.append(i)
    for i in idx_to_remove:
        del ppt_yr_list[i]
        del rec_yr_list[i]
    
X = np.array(ppt_yr_list).reshape(-1,1)
Y = np.array(rec_yr_list)
reg = LinearRegression().fit(X, Y)
R = reg.score(X, Y)
reg_coef = reg.coef_
reg_intercept = reg.intercept_
x = [min(ppt_yr_list), max(ppt_yr_list)]
if len(reg_coef) == 1:
    y = [x[0]*reg_coef[0]+reg_intercept, x[1]*reg_coef[0]+reg_intercept]

plt.scatter(ppt_yr_list, rec_yr_list)
plt.plot(x,y)
plt.xlabel('P (mm/yr)')
plt.ylabel('Rech. (mm/yr)')
plt.title('Surfex Rech. vs. P (1960-2020)')
plt.text(x[0],y[0], 'y = ' + str("{:.2f}".format(reg_coef[0]))
         + 'x + (' + str("{:.1f}".format(reg_intercept)) + ')',
         size = 17, ha = 'left')
plt.text(x[1],y[1], 'R='+str("{:.2f}".format(R)), size = 20, ha = 'right')
plt.show()
 
          
#plot mean doy ETP against 2000-2020 daily ETP time series
plt.plot(piv)
plt.plot(doy_ETP)
plt.show()

#plot smoothed doy_ETP against mean doy_ETP
doy_ETP_smooth = uniform_filter1d(doy_ETP, size=30)
plt.plot(doy_ETP)
plt.plot(doy_ETP_smooth)
plt.show()

# save smoothed doy_ETP as csv
# doy_ETP_smooth = pd.DataFrame(doy_ETP_smooth) 
# doy_ETP_smooth.to_csv(r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\ETP_doy_' + watershed_name + '.csv',
#                       sep = ';', header = False)

#plot doy_ETP gainst recharge
plt.plot(doy_ETP_smooth)
plt.plot(doy_REC)
plt.show()


