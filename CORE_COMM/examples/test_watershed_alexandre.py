# -*- coding: utf-8 -*-
"""
Created on Fri Nov 12 10:21:56 2021

@author: Alexandre Gauvain
"""

# Download data on my Dropbox at this link: https://www.dropbox.com/sh/eidukc992nvi6jc/AAC0cwuwCnY7bDjiN57qwODva?dl=0
import os
import sys
import numpy as np

from os.path import dirname, abspath
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)
from watershed import watershed_root
from calibration import calibration_root


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

load = True #False to build and save python object
watershed_name = 'Agon-Coutainville' #'Saint-Germain-sur-Ay'Agon-Coutainville'Barneville-Carteret'Baie-du-cotentin'

dem_path = root_path + "MNT_TOPO_BATH_75m.tif"#'BDALTI_bzh_75m.tif' 
surfex_path =  root_path + 'SURFEX/Normandie_h5'
geology_path = root_path + 'GEOLOGY'
oceanic_path = root_path + 'OCEAN'
modflow_path = root_path + 'MODFLOW'
hydrology_path = root_path + 'HYDROLOGY'
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, 
                              out_path=out_path,surfex_path=surfex_path, geology_path = geology_path, 
                              hydrology_path=hydrology_path, oceanic_path=oceanic_path, piezometry_path=True ,
                              modflow_path=modflow_path , load=load)
if load == False:
    BV.piezometry.add_data()
    BV.save_object()

#%% Calibration Model
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1960, last_year=2019, time_step = 'D', sim_state='steady')
#indicator = calibration_root.run_calibration(0.864, BV, observation='streams')

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
from groundwater_flow import vizualisation
vtk.VTK(BV, 'modflow')
visu = vizualisation.Vizualisation(BV, 'modflow')
visu.visual3D(interactive=True, object_list=['grid','watertable','pathlines', 'watertable_depth'], view='south-west')
