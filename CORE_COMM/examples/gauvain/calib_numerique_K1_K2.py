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
user_path = "Jean-Raynald"

if user_path=="Alexandre":
    root_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy'
elif user_path=="Jean-Raynald":
    root_path= "D:\codes-data\HydroModPy_Data"
    out_path = "D:/results/HydroModPy"
elif user_path=="Ronan":
    root_path= "D:/Users/abherve/HYDROMODPY/_data/"
    out_path = "D:/Users/abherve/HYDROMODPY"
else:
    print("Define a well-validated name of user")

 
watershed_name = 'Agon-Coutainville' #'Saint-Germain-sur-Ay'Agon-Coutainville'Barneville-Carteret'Baie-du-cotentin'
watershed_shp = os.path.join(out_path, watershed_name, "results_stable", "geographic", 'watershed.shp')
dem_path = os.path.join(root_path,"DEM","France","BDALTI_norm-manch_75m.tif")#'BDALTI_bzh_75m.tif' 
surfex_path =  os.path.join(root_path,'CLIMATE\France\SURFEX\All')
geology_path = os.path.join(root_path,'GEOLOGY',"France","Layer")
oceanic_path = os.path.join(root_path,root_path,'OCEAN')
modflow_path = os.path.join(root_path,'MODFLOW')
hydrology_path = os.path.join(root_path,'HYDROLOGY','France', 'Hydrographic')
types_obs = ['streams']


load = True#False to build and save python object4

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, 
                              out_path=out_path, modflow_path=modflow_path, load=load, from_shp= watershed_shp)

if load == False :  
    BV.add_forcing()
    # BV.add_surfex(surfex_path) 
    BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2018, last_year=2019, time_step = 'D', sim_state='steady')#
    BV.add_hydrodynamic()
    BV.hydrodynamic.update_thickness(30)
    BV.hydrodynamic.update_porosity(0.1)
    BV.add_geology(geology_path)
    BV.add_oceanic(oceanic_path)
    BV.add_piezometry()    
    BV.add_hydrology(hydrology_path,types_obs=types_obs)

params_file = "calib_params" # 'calib_explo_hom_2v_k1-k2'

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

#%% Calibration Model piezometry (Type of calibration)
from calibration import calib_root

calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
calib.exploration(resolution=10)  #1000
calib = calib_root.Calibration(params_file, BV, observations = ['piezometry'])
calib.exploration(resolution=10)  #1000
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

test.display_objective_function(save=os.path.join(root_path,params_file+'.png'),vmax=8)

#%% 
from calibration import calib_analysis
import glob
import matplotlib.pyplot as plt
import matplotlib
typ_calib = ['streams_calibration','piezometry_calibration']
vmax = [100,10]
vmin =[0.01,2]
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

#test.display_objective_function(save='C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/'+type_calib+'_K.png')

fig, ax = plt.subplots(1,2,figsize=(12,5))
for i in range(len(typ_calib)):
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib[i], '*.calib')),
                       key=os.path.getmtime, reverse=True)
    name_file = list_path[0].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib[i], name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    print(typ_calib[i],test.p)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function
    #plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
    #plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
    ax[i].plot(test.p[0],test.p[1],'ow',markersize=10)
    levels = 1000
    #plt.contourf(X, Y, Z,levels,cmap='jet', shading='auto',vmax=vmax, vmin=vmin)
            
    for j in range(0,len(test.names)):
        
        if test.names[i][0] == 'k':
            if j == 0:
                ax[i].set_xscale("log")
                ax[i].set_xlabel(r'$K$'+str(test.names[j][1])+' $[m.j^{-1}]$')
            if j == 1:
                ax[i].set_yscale("log")
                ax[i].set_ylabel(r'$K$'+str(test.names[j][1])+' $[m.j^{-1}]$')
        if test.names[j][0] == 'n':
            if j == 0:
                if test.names[j][1]=='0':
                    ax[i].set_xlabel(r'$n$ $[-]$')
                else:
                    ax[i].set_xlabel(r'$n$'+str(test.names[j][1])+' $[-]$')
            if j== 1:
                if test.names[j][1] == '0':
                    ax[i].set_ylabel(r'$n$ $[-]$')
                else:
                    ax[i].set_ylabel(r'$n$'+str(test.names[j][1])+' $[-]$')
    
    ax[i].plot([0.01,100],[0.01,100],'k--',lw=2)
    ax[i].set_xlim((0.01,100))
    ax[i].set_ylim((0.01,100))      
    if test.observations == ['piezometry']:
        cmap=ax[i].pcolor(X, Y, Z,cmap='jet', shading='auto',vmax=vmax[i], vmin=vmin[i])
        plt.colorbar(cmap,label=r'$RMSE$',ax=ax[i])
    if test.observations == ['streams']:
        cmap=ax[i].pcolor(X, Y, Z,cmap='jet', shading='auto',vmax=vmax[i], vmin=vmin[i],norm=matplotlib.colors.LogNorm())
        plt.colorbar(cmap,label=r'$log(D_{SO}/D_{OS})^{2}$',ax=ax[i])

plt.tight_layout()
save='C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/2param_K.png'
#plt.savefig(save,dpi=300, bbox_inches = "tight")
                