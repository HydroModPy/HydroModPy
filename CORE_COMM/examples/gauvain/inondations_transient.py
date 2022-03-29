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
#%%
for c in fact_cond:
    for i in range(len(Recharge)):
        for s in MSL:
            ident= 'mod_cond_'+str(c)+'_sea_'+str(s)+'_rech_'+str(sce[i])
            path = os.path.join(BV.simulations_folder,ident,ident+'.hds')
            if not os.path.exists(path):
                print(ident)
                BV.forcing.update_recharge(Recharge[i],'transient')
                BV.oceanic.update_MSL(s)
                #succes, mf = BV.run_modflow(ident=ident, modpath_sim=False, lay_number=1, multip_cond=(10**c)*24*60*60,verbose=False)
                #print(succes)
                
#%%
import flopy.utils.binaryfile as fpu

ztop = BV.geographic.dem_clip
ztop[ztop == -99999] = np.nan
A = np.sum(BV.geographic.dem_clip>-9999)

AsA_store = []
for c in fact_cond:
    for i in range(len(Recharge)):
        for s in MSL:
            ident= 'mod_cond_'+str(c)+'_sea_'+str(s)+'_rech_'+str(sce[i])
            head_fpu = fpu.HeadFile(os.path.join(BV.simulations_folder,ident,ident+'.hds'))
            head = head_fpu.get_alldata()
            seep = ztop-head[:,0,:,:]
            AsA = []
            for j in range(len(seep)):
                AsA.append(np.nansum(seep[j]<0)/A)
            AsA_store.append(AsA)

#%%
import pandas as pd

compt = 0
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

font = {'family' : 'normal',
        'weight' : 'bold',
        'size'   : 30}

fig, ax = plt.subplots(1,1,figsize=(10,5))
label = ['Historic', 'Scenario 1', 'Scenario 2']
colors = ['b','r','k']
for c in fact_cond:
    for i in range(len(Recharge)):
        for s in MSL:
            if c == -3:
                if s == 0.48:
                    ss = np.ones(len(AsA_store[compt]))*AsA_store[compt][0]
                    df = pd.DataFrame(data={label[i]:AsA_store[compt]},index=climatic.index)
                    df.plot(color=colors[i],ax=ax)
                    df = pd.DataFrame(data={'Steady state':ss},index=climatic.index)
                    df.plot(color=colors[i],ax=ax,linestyle = '--')
            compt += 1
            
plt.legend(prop={'size':14})
ax.set_xlabel(r'$Date$') 
ax.set_ylabel(r'$A_{S}/A$ $[-]$')

plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/chronicle_results.png',dpi=300, bbox_inches = "tight")

#%%
import geopandas as gpd
import rasterio
from rasterio.plot import show
import contextily as cx
import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable

plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

font = {'family' : 'normal',
        'weight' : 'bold',
        'size'   : 30}

ztop = BV.geographic.dem_clip
ztop[ztop == -99999] = np.nan
contour = gpd.read_file(BV.geographic.watershed_contour_shp)
dem = rasterio.open(BV.geographic.watershed_box_buff_dem)
A = np.sum(BV.geographic.dem_clip>-9999)

c = -5.0
i = 2
s = 2.48
ident= 'mod_cond_'+str(c)+'_sea_'+str(s)+'_rech_'+str(sce[i])
head_fpu = fpu.HeadFile(os.path.join(BV.simulations_folder,ident,ident+'.hds'))
head = head_fpu.get_alldata()
seep = ztop-head[:,0,:,:]

thick = seep[0].copy()
thick[thick>2]=np.nan
thick[thick<0]=np.nan

dur = seep<0
time = np.sum(dur,axis = 0)/10
time[time==0]= np.nan
fig, ax = plt.subplots(1,1,figsize=(10,5))
show(time, ax=ax,transform=dem.transform, cmap='Reds', alpha=1, zorder=2, aspect="auto")
show(thick, ax=ax,transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
contour.plot(ax=ax, lw=1, color='k', zorder=4, aspect="auto")
cx.add_basemap(ax,crs='EPSG:2154',source='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png')

plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/'+ident+'_map',dpi=300, bbox_inches = "tight")

fig, ax = plt.subplots(1,1,figsize=(5,5))
t = show(time, ax=ax,transform=dem.transform, cmap='Reds', alpha=1, zorder=2, aspect="auto")
th = show(thick, ax=ax,transform=dem.transform, cmap='Blues', alpha=1, zorder=2, aspect="auto")
x = [363000,366000]
ax.set_xlim(x[0],x[1])
ax.set_xticks(np.arange(min(x), max(x)+1, 1500))
ax.set_ylim(6890000+2000,6890000+7000)
cx.add_basemap(ax,crs='EPSG:2154',source='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png')#https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png

divider = make_axes_locatable(ax)
#cax = divider.append_axes('right', size='10%', pad=0.25)
pad = 0.8
cax = fig.add_axes([pad,0.5, 0.05, 0.4])
cmap = mpl.cm.Reds
norm = mpl.colors.Normalize(vmin=0, vmax=365)
cb1 = mpl.colorbar.ColorbarBase(cax, cmap=cmap,
                                norm=norm)
cb1.ax.tick_params(labelsize=10) 
cb1.set_label('Groundwater inundations $[d.y^{-1}]$',font_properties={'size': 10})

#cax2 = divider.append_axes('right', size='10%', pad=0.5)
cax2 = fig.add_axes([pad,0.1, 0.05, 0.4])
cmap = mpl.cm.Blues
norm = mpl.colors.Normalize(vmin=0, vmax=2)
cb2 = mpl.colorbar.ColorbarBase(cax2, cmap=cmap,
                                norm=norm)
cb2.ax.invert_yaxis()
cb2.ax.tick_params(labelsize=10) 
cb2.set_label('Watertable depth $[m]$',font_properties={'size': 10})

plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/'+ident+'_zoommap',dpi=300, bbox_inches = "tight")