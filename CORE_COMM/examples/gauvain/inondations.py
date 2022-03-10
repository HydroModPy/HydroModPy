# -*- coding: utf-8 -*-
"""
Created on Mon Mar  7 09:35:45 2022

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
watershed_name = 'Agon-Coutainville_5m' #'Saint-Germain-sur-Ay'Agon-Coutainville'Barneville-Carteret'Baie-du-cotentin'
watershed_shp = os.path.join(out_path, 'Agon-Coutainville', 'watershed.shp')
dem_path = root_path + "MNT_25m.tif"#'BDALTI_bzh_75m.tif' 
surfex_path =  root_path + 'SURFEX/Normandie_h5'
geology_path = root_path + 'GEOLOGY'
oceanic_path = root_path + 'OCEAN'
modflow_path = root_path + 'MODFLOW'
hydrology_path = root_path + 'HYDROLOGY'
types_obs = ['streams_fr']
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, 
                              out_path=out_path, modflow_path=modflow_path, load=load, from_shp= watershed_shp)
#%% Add Data
if load == False:
    BV.add_surfex(surfex_path) 
    BV.add_geology(geology_path,'GEO50K.shp','CODE_LEG') 
    BV.add_hydrology(hydrology_path,types_obs=types_obs)
    BV.add_oceanic(oceanic_path)
    #BV.add_hydrometry(hydrometry_path)
    #BV.add_intermittency(intermittency_path)
    #BV.add_subbasin()
    BV.add_piezometry()
    BV.piezometry.add_data()
    BV.save_object()

#BV.display(dtype = 'watershed_dem')
#BV.display(dtype = 'watershed_geology')

#%% zones
zones = np.ones(np.shape(BV.geology.geology_array))
zones[BV.geology.geology_array>40] = int(2) # Crystalline rocks
zones[BV.geology.geology_array<40] = int(1) # Sands
zones[BV.geology.geology_array == 175] = int(1)
zones[BV.geology.geology_array == 178] = int(1)
zones[BV.geology.geology_array == 4] = int(2)
zones[BV.geology.geology_array == 29] = int(2)
zones[BV.geology.geology_array == 35] = int(2)

BV.hydrodynamic.update_calib_zones(zones)
K1 = 4.01
K2 = 1
K = np.ones(np.shape(BV.geology.geology_array))
K[zones==1]=K1
K[zones==2]=K2
BV.display(dtype = 'watershed_zones')


#%%
from tools import vtk
from groundwater_flow import visualization

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2018, last_year=2019, time_step = 'D', sim_state='steady')#
BV.hydrodynamic.update_thickness(30)
BV.hydrodynamic.update_porosity(0.28)
BV.hydrodynamic.update_hyd_cond(K)

fact_cond = np.around(np.linspace(-5,-3,10),2)
MSL = np.around([BV.oceanic.MSL, 
       BV.oceanic.RMSL['RCP8.5']['median']['2030'].mean(),
       BV.oceanic.RMSL['RCP8.5']['median']['2050'].mean(),
       BV.oceanic.RMSL['RCP8.5']['median']['2100'].mean(),
       BV.oceanic.MSL+1,
       BV.oceanic.MSL+2],2)
Recharge = np.around([BV.forcing.recharge*0.3+BV.forcing.recharge,
            BV.forcing.recharge*0.2+BV.forcing.recharge,
            BV.forcing.recharge*0.1+BV.forcing.recharge,
            BV.forcing.recharge*0+BV.forcing.recharge,
            BV.forcing.recharge*-0.1+BV.forcing.recharge,
            BV.forcing.recharge*-0.2+BV.forcing.recharge,
            BV.forcing.recharge*-0.3+BV.forcing.recharge],5)
for c in fact_cond:
    for s in MSL:
        for r in Recharge:
            ident= 'mod_cond_'+str(c)+'_sea_'+str(s)+'_rech_'+str(r)
            BV.forcing.update_recharge(r,'steady')
            BV.oceanic.update_MSL(s)
            succes, mf = BV.run_modflow(ident=ident, modpath_sim=True, lay_number=1, multip_cond=(10**c)*24*60*60,verbose=True)
            BV.matrix_modflow(succes,
                       mf,
                       watertable_elevation = True,
                       watertable_depth=True, 
                       seepage_areas = True,
                       outflow_drain = True,
                       groundwater_flux = False,
                       specific_discharge = False,
                       accumulation_flux = True,
                       perenn_intermit=False,
                       verbose = False,
                       export_tif = True)
    
            visu = visualization.Visualization(BV, ident)
            #object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times']
            visu.visual2D(object_list = ['drain_flow'],
              color_scale = [(-1,2)], lines=300, structure='h')
