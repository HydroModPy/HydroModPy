# -*- coding: utf-8 -*-
"""
Created on Fri Nov 12 10:21:56 2021

@author: Alexandre Gauvain
"""
# <codecell>

# Download data on my Dropbox at this link: https://www.dropbox.com/sh/eidukc992nvi6jc/AAC0cwuwCnY7bDjiN57qwODva?dl=0
import os
import sys
import numpy as np

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

dem_path = root_path + "MNT_25m_cor.tif"#'BDALTI_bzh_75m.tif' 
surfex_path =  root_path + 'SURFEX/Normandie_h5'
geology_path = root_path + 'GEOLOGY'
oceanic_path = root_path + 'OCEAN'
modflow_path = root_path + 'MODFLOW'
hydrology_path = root_path + 'HYDROLOGY'
types_obs = ['streams_fr']
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, 
                              out_path=out_path, modflow_path=modflow_path, load=load)

if load == False:
    BV.add_hydrology(hydrology_path, types_obs)
    BV.add_surfex(surfex_path) 
    BV.add_geology(geology_path) 
    BV.add_hydrology(hydrology_path,types_obs=types_obs)
    BV.add_oceanic(oceanic_path)
    #BV.add_hydrometry(hydrometry_path)
    #BV.add_intermittency(intermittency_path)
    #BV.add_subbasin()
    BV.add_piezometry()
    BV.piezometry.add_data()
    BV.save_object()

BV.display()

#%% zones
zones = np.ones(np.shape(BV.geology.geology_array))
zones[BV.geology.geology_array>1000] = int(2) # Crystalline rocks
zones[BV.geology.geology_array<1000] = int(1) # Sands
zones[BV.geology.geology_array == 2151] = int(1)
zones[BV.geology.geology_array == 1871] = int(1)
BV.hydrodynamic.update_calib_zones(zones)


#%% Calibration Model piezometry
from calibration import calib_root
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2015, last_year=2019, time_step = 'D', sim_state='steady')#
BV.hydrodynamic.update_thickness(30)
BV.hydrodynamic.update_porosity(0.1)
BV.hydrodynamic.update_hyd_cond(4.26)
params_file = 'C:/Users/alexa/Documents/GitHub/HydroModPy/CORE_COMM/calibration/calib_params.csv'
calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
calib.exploration(resolution=1000)
#calib.simplex(init_multiples_n=15)

#%% Calib Analysis
from calibration import calib_analysis
file = 'C:/Users/alexa/Dropbox/HydroModPy/Agon-Coutainville/results_simulations/piezometry_calibration/exp_2p_21_12_2021_21h05.calib'
file = 'C:/Users/alexa/Dropbox/HydroModPy/Agon-Coutainville/results_simulations/streams_calibration/exp_2p_24_01_2022_10h22.calib'
test = calib_analysis.CalibAnalysis(file)
#ident='modflow'
#↓BV.run_modflow(ident=ident)

#%% Calibration Model stream
from calibration import calib_root
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1960, last_year=2019, time_step = 'D', sim_state='steady')
BV.hydrodynamic.update_thickness(100)
params_file = 'C:/Users/alexa/Documents/GitHub/HydroModPy/CORE_COMM/calibration/calib_params.csv'
calib = calib_root.Calibration(params_file, BV, observations = ['streams'])

#%%
#Exploration des paramètres
calib.exploration(resolution=1000)

#Simplex Method
#calib.simplex()

#%%
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1960, last_year=2019, time_step = 'D', sim_state='steady')
BV.hydrodynamic.update_hyd_cond(0.864)
BV.hydrodynamic.update_porosity(0.1)
BV.run_modflow(ident='modflow', modpath_sim=False)
#%% Run Modflow Steady state

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1960, last_year=2019, time_step = 'D', sim_state='steady')
#BV.forcing.update_recharge(values=[0.0003], sim_state = 'steady')


#indicator = calibration_root.run_calibration(0.864, BV, observation='streams')
#BV.forcing.update_synthetic_recharge(0.300,55,10, dis='normal')3
BV.hydrodynamic.update_hyd_cond(0.864)
BV.hydrodynamic.update_porosity(0.1)
model = ['sea_level_0.48','sea_level_2.48','sea_level_10.48']
for i in model:
    BV.run_modflow(ident='modflow',sea_level=float(i.split('_')[-1]), lay_number= 1, modpath_sim = False)

#%% Analysis Modflow Steady State
import matplotlib.pyplot as plt

model = ['sea_level_0.48','sea_level_2.48','sea_level_10.48']
A=[]
As=[]
As_A=[]
seep=[]
wat=[]

for i in model:
    model_folder = os.path.join(BV.simulations_folder,i)
    result_folder = os.path.join(model_folder,'_extraction')
    seep_file = os.path.join(result_folder,'seepage_areas.npy')
    water_file = os.path.join(result_folder,'watertable_elevation.npy')
    seep_area = np.load(seep_file, allow_pickle=True).item()
    water = np.load(water_file, allow_pickle=True).item()
    seep_area[0][seep_area[0]==-9999]=np.nan
    water[0][water[0]==-9999]=np.nan
    wat.append(water[0])
    seep.append(seep_area[0])
    A.append(np.nansum(seep_area[0]>=0))
    As.append(np.nansum(seep_area[0]>=1))
    As_A.append(np.nansum(seep_area[0]>=1)/np.nansum(seep_area[0]>=0))
    
plt.figure()
plt.imshow(wat[1]-wat[0])
plt.colorbar()
plt.show()
#%% Run Modflow Transient state


'''years = np.linspace(1958,2018,2018-1958+1)
x = np.linspace(1,365,365)
chroniques = []
for i in years:
    chronicle = BV.climatic.values['REA']['REC']['historic']['MEAN'][str(int(i))+'-08':str(int(i)+1)+'-07'].values
    if len(chronicle)==365:   
        chroniques.append(chronicle)
import matplotlib.pyplot as plt
plt.figure
BV.forcing.update_synthetic_recharge(0.300,150,2, freq='D', dis='uniform')
plt.plot(BV.forcing.recharge)
BV.forcing.update_synthetic_recharge(0.300,55,2, freq='D', dis='normal')
plt.plot(BV.forcing.recharge)
BV.forcing.update_synthetic_recharge(0.300,15,2, freq='D', dis='inverse-gaussian')
plt.plot(BV.forcing.recharge)
#plt.plot(x,np.mean(np.asarray(chroniques)/1000,axis=0),c='k')'''

from tools import vtk
from groundwater_flow import visualization
vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, 'modflow')
visu.visual3D(interactive=True, object_list=['grid','watertable', 'watertable_depth','pathlines', 'surface_flow', 'drain_flow'], view='south-west', lines=200, cloc=(0.7,0.1))
