# -*- coding: utf-8 -*-
"""
Created on Mon Feb 28 21:10:13 2022

@author: Alexandre Gauvain
"""

#%% BV

# Download data on my Dropbox at this link: https://www.dropbox.com/sh/eidukc992nvi6jc/AAC0cwuwCnY7bDjiN57qwODva?dl=0
import os
import sys
import numpy as np
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

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2018, last_year=2019, time_step = 'D', sim_state='steady')#
BV.hydrodynamic.update_thickness(30)
BV.hydrodynamic.update_porosity(0.1)
params_file = 'calib_explo_hom_1v_k1'

#%% Calibration Model piezometry
from calibration import calib_root
#calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
#calib.exploration(resolution=100)
calib = calib_root.Calibration(params_file, BV, observations = ['piezometry'])
calib.exploration(resolution=100)
calib = calib_root.Calibration(params_file, BV, observations = ['streams','piezometry'])
calib.exploration(resolution=100)
#calib.dichotomy(gap=10)
#calib.simplex(init_multiples_n=15)

#%% Stream
from calibration import calib_analysis
import glob
typ_calib = 'streams_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
key=os.path.getmtime, reverse=True)
name_file = list_path[0].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)

test.display_objective_function(save='C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/calib_streams_K.png')
#%% 
from calibration import calib_analysis
import glob
import matplotlib.pyplot as plt
typ_calib = ['streams_calibration','piezometry_calibration']
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

#test.display_objective_function(save='C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/'+type_calib+'_K.png')

fig, ax1 = plt.subplots(figsize=(5,5))
ax2 = ax1.twinx()
ax2.spines['right'].set_color('b')
ax2.spines['left'].set_color('r')
for i in typ_calib:
    
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, i, '*.calib')),
                       key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, i, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    print(i, test.p)
    if test.observations == ['piezometry']:
        ax1.plot(test.obj_function.iloc[:, 0].values,
                         test.obj_function.iloc[:, 1].values,
                         lw=2, color='r') 
        ax1.tick_params(axis='y', labelcolor='r')
        ax1.set_yscale("log")
        ax1.set_ylabel(r'$RMSE$',c='r')
    if test.observations == ['streams']:
        ax2.plot(test.obj_function.iloc[:, 0].values,
                         test.obj_function.iloc[:, 1].values,
                         lw=2, color='b')
        ax2.tick_params(axis='y', labelcolor='b')
        ax2.set_yscale("log")
        ax2.set_ylabel(r'$log(D_{SO}/D_{OS})^{2}$',c='b')   
    if test.names[0][0] == 'k':
        ax1.set_xscale("log")
        ax1.set_xlabel(r'$K$ $[m.j^{-1}]$')
save='C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/1param_K.png'
plt.savefig(save,dpi=300, bbox_inches = "tight")
                


