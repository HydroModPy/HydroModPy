# -*- coding: utf-8 -*-
"""
Created on Fri Mar  4 11:25:15 2022

@author: Alexandre Gauvain
"""

#%% BV

# Download data on my Dropbox at this link: https://www.dropbox.com/sh/eidukc992nvi6jc/AAC0cwuwCnY7bDjiN57qwODva?dl=0
import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
from watershed import watershed_root
#from calibration import calib_root


# Users
user_path = "Alexandre"

if user_path=="Alexandre":
    root_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy'
elif user_path=="Jean-Raynald":
    root_path= "C:/DATA/codes-gitlab-public/HydroModPy_data/"
    out_path = "C:/DATA/results/HydroModPy"
elif user_path=="Ronan":
    root_path= "D:/Users/abherve/HYDROMODPY/_data/"
    out_path = "D:/Users/abherve/HYDROMODPY"
else:
    print("Define a well-validated name of user")

load = True#False to build and save python object
watershed_name = 'Agon-Coutainville' #'Saint-Germain-sur-Ay'Agon-Coutainville'Barneville-Carteret'Baie-du-cotentin'
watershed_shp = os.path.join(out_path, watershed_name, 'watershed.shp')
dem_path = root_path + "MNT_75m.tif"#'BDALTI_bzh_75m.tif' 
surfex_path =  root_path + 'SURFEX/Normandie_h5'
geology_path = root_path + 'GEOLOGY'
oceanic_path = root_path + 'OCEAN'
modflow_path = root_path + 'MODFLOW'
hydrology_path = root_path + 'HYDROLOGY'
types_obs = ['streams_fr']
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, 
                              out_path=out_path, modflow_path=modflow_path, load=load, from_shp= watershed_shp)

params_file = 'calib_explo_hom_2v_k1-n1'

zones = np.ones(np.shape(BV.geology.geology_array))
if watershed_name == 'Agon-Coutainville':
    zones[BV.geology.geology_array>40] = int(2) # Crystalline rocks
    zones[BV.geology.geology_array<40] = int(1) # Sands
    zones[BV.geology.geology_array == 175] = int(1)
    zones[BV.geology.geology_array == 178] = int(1)
    zones[BV.geology.geology_array == 4] = int(2)
    zones[BV.geology.geology_array == 29] = int(2)
    zones[BV.geology.geology_array == 35] = int(2)
plt.imshow(zones)
plt.plot(BV.piezometry.x_iloc,BV.piezometry.y_iloc,'ok')
BV.hydrodynamic.update_calib_zones(zones)

from calibration import calib_analysis
import glob
typ_calib = 'piezometry_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
key=os.path.getmtime, reverse=True)
name_file = list_path[0].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2015, last_year=2019, time_step = 'M', sim_state='transient')#
BV.hydrodynamic.update_thickness(30)

K2 = 0.16859
K1 = 6.01 #test.p[0]
n = 0.025 #test.p[0]
bot = 0.48-30

BV.hydrodynamic.update_hyd_cond_from_calib_zones(2, K2)
BV.hydrodynamic.update_hyd_cond_from_calib_zones(1, K1)
BV.hydrodynamic.update_porosity(n)

model = 'test_calib_ana'
#%%

BV.run_modflow(ident=model,run=True, modpath_sim=False, bottom=bot, lay_number=1 , post_process = True, verbose=True)

#%% test
param_folder = os.path.join(BV.simulations_folder)
watertable_elevation = np.load(os.path.join(param_folder, model ,'_watershed', 'watertable_elevation.npy'), allow_pickle=True).item()
        
store_indicator = []
if isinstance(BV.forcing.recharge, float) == False:
    try:
        # df = BV.piezometry.elevation.resample(BV.forcing.freq).mean()
        df = BV.piezometry.elevation.resample(pd.infer_freq(BV.forcing.recharge.index)).mean()
        #df.index = df.index.to_period(BV.forcing.freq)
    except:
        sys.exit('watershed.forcing.recharge must be a chronicle Dataframe with date as index.')
            
    # Continue Data
    for j in range(0,len(BV.piezometry.codes_bss)):
        sim=[]
        for i in range(0,len(watertable_elevation)):
            sim.append(watertable_elevation[i][BV.piezometry.y_iloc[j],BV.piezometry.x_iloc[j]])
        df_sim = pd.Series(sim, index=BV.forcing.recharge.index, name='sim_' + BV.piezometry.codes_bss[j])
        df = df.merge(df_sim, left_index=True, right_index=True)
                    
        y0 = df[BV.piezometry.codes_bss[j]].values
        y1 = df['sim_' + BV.piezometry.codes_bss[j]].values
                
        fig, ax = plt.subplots()
        df[BV.piezometry.codes_bss[j]].plot(c='b',ax=ax)
        BV.piezometry.elevation[BV.piezometry.codes_bss[j]].plot(c='k',ax=ax)
        df['sim_' + BV.piezometry.codes_bss[j]].plot(c='r',ax=ax)
        plt.title(BV.piezometry.codes_bss[j])
        plt.plot(y0,y0-y1)

        ER = np.nansum(y0-y1)  # error 
        ABSER = np.nansum(np.abs(y0-y1))  # absolute error 
        RELER = np.nansum(np.abs(y0-y1)/y0) # relative error 
        PERER = np.nansum(np.abs(y0-y1)/y0*100) # percentage error 
        MAE = np.nanmean(np.abs(y0-y1)) # mean absolute error 
        BAL = (np.sum(y1)/np.sum(y0))*100 # balance
        MSE = np.nanmean((y0-y1)**2) # mean square error 
        RMSE = np.sqrt(np.nanmean((y0-y1)**2)) # root mean square error 
        NSE = 1-( np.sum((y1-y0)**2) / np.sum((y0-np.mean(y0))**2) ) # nash–sutcliffe efficiency                               

        store_indicator.append(RMSE)