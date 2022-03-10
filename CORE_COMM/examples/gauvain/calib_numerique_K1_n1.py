# -*- coding: utf-8 -*-
"""
Created on Mon Feb 28 23:03:54 2022

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

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2015, last_year=2019, time_step = 'M', sim_state='transient')#
BV.hydrodynamic.update_thickness(30)
BV.hydrodynamic.update_porosity(0.1)
params_file = 'calib_explo_hom_2v_k1-n1'
#%% zones
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
BV.hydrodynamic.update_calib_zones(zones)
K2 = 0.16859
#K1 = 6.01
BV.hydrodynamic.update_hyd_cond_from_calib_zones(2, K2)
#BV.hydrodynamic.update_hyd_cond_from_calib_zones(1, K1)

#%% Calibration Model piezometry
from calibration import calib_root
#◘calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
#calib.exploration(resolution=1000)
calib = calib_root.Calibration(params_file, BV, observations = ['piezometry'])
calib.exploration(resolution=25)
#calib = calib_root.Calibration(params_file, BV, observations = ['streams','piezometry'])
#calib.exploration(resolution=100)
#calib.dichotomy(gap=10)
#calib.simplex(init_multiples_n=15)

#%% Stream
from calibration import calib_analysis
import glob
typ_calib = 'piezometry_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
key=os.path.getmtime, reverse=True)
name_file = list_path[0].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)

test.display_objective_function(save='C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/'+params_file+'.png',vmax=2 ,log=False)