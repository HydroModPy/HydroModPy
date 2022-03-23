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
watershed_name = 'Agon-Coutainville_5m' #'Saint-Germain-sur-Ay'Agon-Coutainville'Barneville-Carteret'Baie-du-cotentin'
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
zones[BV.geology.geology_array>40] = int(2) # Crystalline rocks
zones[BV.geology.geology_array<40] = int(1) # Sands
zones[BV.geology.geology_array == 175] = int(1)
zones[BV.geology.geology_array == 178] = int(1)
zones[BV.geology.geology_array == 4] = int(2)
zones[BV.geology.geology_array == 29] = int(2)
zones[BV.geology.geology_array == 35] = int(2)
#plt.imshow(zones)
#plt.plot(BV.piezometry.x_iloc,BV.piezometry.y_iloc,'ok')
BV.hydrodynamic.update_calib_zones(zones)

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2015, last_year=2019, time_step = 'D', sim_state='steady')#
BV.hydrodynamic.update_thickness(30)

K2 = 1
K1 = 6 #test.p[0]
n = 0.01 #test.p[0]
bot = None #0.48-30

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

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, model)
#object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times']
visu.visual2D(object_list = ['grid','surface_flow'],
              color_scale = [(None,None),(None,None)], lines=300, structure='h')

#%%
from groundwater_flow import modflow_display as plots
import imageio
# Dem data
dem_data = BV.geographic.dem_data
# Wt data
wt_data = imageio.imread(os.path.join(BV.simulations_folder, model ,'_watershed', '_tifs','watertable_elevation_t(0).tif')) # buffer size no masked

# River data
river_data = imageio.imread(os.path.join(BV.stable_folder,'hydrology','streams_fr.tif'))

# Function
plots.interactive_cross_section(dem_data, wt_data, river_data, interactive=True,)

#%%


plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

watertable_elevation = np.load(os.path.join(BV.simulations_folder, model ,'_watershed', 'watertable_elevation.npy'), allow_pickle=True).item()
yc = BV.piezometry.elevation.mean().values.tolist()
ycs = []
yd = []
yds = []
for j in range(0,len(BV.piezometry.codes_bss)):
    ycs.append(watertable_elevation[0][BV.piezometry.y_iloc[j],BV.piezometry.x_iloc[j]])

for j in range(0,len(BV.piezometry.elevation_discrete)):
    yd.append(BV.piezometry.elevation_discrete[j])
    yds.append(watertable_elevation[0][BV.piezometry.y_iloc_discrete[j],BV.piezometry.x_iloc_discrete[j]])


yd = np.array(yd)
yds = np.array(yds)
yc = np.array(yc)
ycs = np.array(ycs)
y0 = np.concatenate((yd,yc))
y1 = np.concatenate((yds,ycs))

M = []
for i in BV.piezometry.date_discrete:
    M.append(int(i.split('/')[1]))
df = pd.DataFrame({'date': M, 'obs': yd, 'sim': yds})

from datetime import datetime as dt
months = [dt.strptime(str(m), '%m').strftime('%B') for m in range(1, 13)]
cmap = plt.cm.get_cmap('jet')  # no need to preselect number of colors in this case
colors = cmap(np.linspace(0, 1, len(months)))



fig, (ax1) = plt.subplots(1, figsize=(5,5),dpi=300)
ax1.plot(yc, ycs,'ok',markersize=10)
#ax1.plot(yd, yds,'^')#,c=BV.piezometry.date_discrete,cmap='jet_r')
for x, y, c in zip(df['obs'],df['sim'], df['date']):
    ax1.scatter(x, y, color=colors[c-1], label=months[c-1],marker='^',s=100)
    #ax2.scatter(x, x-y, color=colors[c-1], label=months[c-1],marker='^',s=100)
    
bounds = np.arange(len(months)+1)
norm = plt.matplotlib.colors.BoundaryNorm(bounds, cmap.N)
cbar = plt.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ticks=bounds+0.5)
cbar.set_ticklabels(months)

cbar.ax.tick_params(length=0, pad=7)
cbar.ax.invert_yaxis()

ax1.plot([min(y0),max(y0)],[min(y0),max(y0)],'-k')
#ax2.plot(yc, yc - ycs,'ok',markersize=10)

#ax2.plot([min(y0),max(y0)],[0,0],'-k')
ax1.set_xscale('log')
ax1.set_yscale('log')
#ax2.set_xscale('log')

corr_matrix = np.corrcoef(yc, ycs)
corr = corr_matrix[0,1]
R_sq = corr**2
print(R_sq)
ax1.set_xlabel(r'$\overline{h}_{obs}$ $[m]$',fontsize=15)
ax1.set_ylabel(r'$\overline{h}_{sim}$ $[m]$',fontsize=15)

plt.show()