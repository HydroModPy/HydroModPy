# -*- coding: utf-8 -*-
"""
Created on Sun Mar 20 23:25:20 2022

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

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1996, last_year=2005, time_step = 'D', sim_state='transient')#


climatic = BV.forcing.recharge.copy()



ext_period = BV.forcing.recharge['08/2000':'08/2001']
Recharge = []
Recharge.append(climatic)
first_sce = climatic.copy()
first_sce['08/1996':'08/1997'] = ext_period
first_sce['08/2004':'08/2005'] = ext_period
Recharge.append(first_sce)
second_sce = climatic.copy()
second_sce['08/1996':'08/1997'] = ext_period
second_sce['08/2004':'08/2005'] = ext_period
second_sce['08/1998':'08/1999'] = ext_period
second_sce['08/2002':'08/2003'] = ext_period
Recharge.append(second_sce)

plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

font = {'family' : 'normal',
        'weight' : 'bold',
        'size'   : 30}

fig, ax = plt.subplots(figsize=(10,5), dpi=300)
second_sce.plot(color='k',ax=ax, label='Scenario 2')
first_sce.plot(color='r',ax=ax, label='Scenario 1')
climatic.plot(color='b',ax=ax, label='Historic')
period = 365*4
#climatic.rolling(period,1).mean().plot(ax=ax)
#second_sce.rolling(period,1).mean().plot(color='k',ax=ax)
#first_sce.rolling(period,1).mean().plot(color='r',ax=ax)
ax.text('1997',0.009,'(1)',size = 20,c='r',ha='center', va='center')
ax.text('2001',0.009,'(1)',size = 20,c='r',ha='center', va='center')
ax.text('2005',0.009,'(1)',size = 20,c='r',ha='center', va='center')

ax.text('2001',0.01,'(2)',size = 20,c='k',ha='center', va='center')
ax.text('1997',0.01,'(2)',size = 20,c='k',ha='center', va='center')
ax.text('1999',0.01,'(2)',size = 20,c='k',ha='center', va='center')
ax.text('2003',0.01,'(2)',size = 20,c='k',ha='center', va='center')
ax.text('2005',0.01,'(2)',size = 20,c='k',ha='center', va='center')

plt.legend(prop={'size':14})

ax.set_xlabel(r'$Date$') 
ax.set_ylabel(r'$Recharge$ $[m.d^{-1}]$')
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/chronicle.png',dpi=300, bbox_inches = "tight")

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
K1 = 6.01
K2 = 1
K = np.ones(np.shape(BV.geology.geology_array))
K[zones==1]=K1
K[zones==2]=K2
BV.display(dtype = 'watershed_zones')


BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1960, last_year=2019, time_step = 'D', sim_state='steady')#
BV.hydrodynamic.update_thickness(30)
BV.hydrodynamic.update_porosity(0.29)
BV.hydrodynamic.update_hyd_cond(K)

fact_cond = np.around(np.linspace(-5,-3,3),2)
MSL = np.around([BV.oceanic.MSL, 
       BV.oceanic.RMSL['RCP8.5']['median']['2030'].mean(),
       BV.oceanic.RMSL['RCP8.5']['median']['2050'].mean(),
       BV.oceanic.RMSL['RCP8.5']['median']['2100'].mean(),
       BV.oceanic.MSL+1,
       BV.oceanic.MSL+2],2)
sce = ['H','1','2']

for c in fact_cond:
    for i in range(len(Recharge)):
        for s in MSL:
            ident= 'mod_cond_'+str(c)+'_sea_'+str(s)+'_rech_'+str(sce[i])
            BV.forcing.update_recharge(Recharge[i],'transient')
            BV.oceanic.update_MSL(s)
            succes, mf = BV.run_modflow(ident=ident, modpath_sim=False, lay_number=1, multip_cond=(10**c)*24*60*60,verbose=True)

