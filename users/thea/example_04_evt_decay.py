# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% ---- LIBRAIRIES
#%% PYTHON

# Filter warnings (before imports)
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import pkg_resources # Must be placed after DeprecationWarning as it is itself deprecated
warnings.filterwarnings('ignore', message='.*pkg_resources.*')
warnings.filterwarnings('ignore', message='.*declare_namespace.*')

# Libraries installed by default
import sys
import glob
import os
from sys import platform
import geopandas as gpd
from datetime import datetime

# Libraries need to be installed if not
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# # Libraries added from 'pip install' procedure
import deepdish as dd
import imageio
import hydroeval
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
import xarray as xr
xr.set_options(keep_attrs = True)

#%% ROOT

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname((abspath(__file__)))))
sys.path.append(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

#%% HYDROMODPY

# Import HydroModPy modules
from src import watershed_root
from src.watershed import climatic, geographic, geology, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

#%% ---- PERSONAL PARAMETERS AND PATHS
study_site = 'LA_FLUME'
first_year = 2020
last_year = 2020
freq_input = 'M'
sim_state = 'transient'
parameters = "1.37e-5_10.7%_exdp13.9_a0.03_bottom"
out_path = folder_root.root_folder_results()
# out_path = r"C:\Users\theat\Documents\Python\02_Output_HydroModPy" # Manually set the output path
data_path = os.path.join(out_path, "data")
specific_data_path = os.path.join(data_path, study_site)

print(f"out_path; {out_path}, Data path: {data_path}, specific_data_folder; {specific_data_path}")
#%% ---- WATERSHED
#%% OPTIONS
# Name of the study site
watershed_name = '_'.join([
    "RUN",study_site,parameters,str(first_year),str(last_year),freq_input,sim_state
])
print('##### '+watershed_name.upper()+' #####')

watershed_path = os.path.join(out_path, watershed_name)
dem_path = os.path.join(data_path,'dem','regional dem.tif')

load = True
# watershed_name ='Strengbach'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = [344966, 6797471, 150, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
bottom_path = None # path
save_object = True

#%% GEOGRAPHIC)

BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=from_lib, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=from_dem, # [path, cell size]
                              from_shp=from_shp, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              bottom_path=bottom_path, # path
                              save_object=save_object)

# Paths generated automatically but necessary for plots
stable_folder = os.path.join(out_path, watershed_name, 'results_stable')
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

#%% DATA

# visualization_watershed.watershed_local(dem_path, BV)

# Clip specific data at the catchment scale
BV.add_geology(os.path.join(data_path, 'geology'), types_obs='GEO1M.shp', fields_obs='CODE_LEG')
BV.add_hydrography(os.path.join(data_path, 'hydrography'), types_obs=['regional stream network'])
BV.add_hydrometry(os.path.join(data_path, 'hydrometry'), 'france hydrometric stations.shp')
BV.add_intermittency(os.path.join(data_path, 'intermittency'), 'regional onde stations.shp') BV.add_intermittency(os.path.join(data_path, 'intermittency'), types_obs='regional onde stations.shp')
# BV.add_piezometry()

# # Extract some subbasin from data available above
# BV.add_subbasin(os.path.join(data_path, 'additional'), 150)

# # General plot of the study site
# visualization_watershed.watershed_geology(BV)
# visualization_watershed.watershed_dem(BV)

#%% ---- RECHARGE
#%% climatic settings
BV.add_climatic()

# Reanalyse
BV.climatic.update_sim2_reanalysis(var_list=['recharge', 'runoff', 'precip',
                                             'evt', 'etp', 't', 'eff_rain'
                                              ],
                                       nc_data_path=os.path.join(
                                           specific_data_path,
                                           r"Meteo\Historiques SIM2"),
                                       first_year=first_year,
                                       last_year=last_year,
                                       time_step=freq_input,
                                       sim_state=sim_state,
                                       spatial_mean=True,
                                       geographic=BV.geographic,
                                       disk_clip='watershed') # for clipping the netcdf files saved on disk
                                                                # can be a shapefile path or a flag: 'watershed' or False
                                                                
# # # # Units
BV.climatic.evt = BV.climatic.evt / 1000 # from mm to m
BV.climatic.etp = BV.climatic.etp / 1000 # from mm to m
BV.climatic.precip = BV.climatic.precip / 1000 # from mm to m
BV.climatic.t = BV.climatic.t / 1000 # from mm to m
BV.climatic.runoff = BV.climatic.runoff / 1000 # from mm to m

#%%
# BV.add_safransurfex(r"C:\Users\theat\Documents\Python\02_Output_HydroModPy\data\Meteo\REA")

# #%%RECHARGE REANALYSIS
# BV.climatic.update_recharge_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_REC_D.csv'),
#                                        clim_mod='REA',
#                                        clim_sce='historic',
#                                        first_year=first_year,
#                                        last_year=last_year,
#                                        time_step=freq_input,
#                                        sim_state=sim_state)

# #BV.climatic.recharge = BV.climatic.recharge * BV.climatic.recharge.index.day #meandaypermonth to mm/month
# BV.climatic.update_recharge(BV.climatic.recharge/1000, sim_state = sim_state) # from mm to m

# BV.climatic.update_runoff_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_RUN_D.csv'),
#                                        clim_mod='REA',
#                                        clim_sce='historic',
#                                        first_year=first_year,
#                                        last_year=last_year,
#                                        time_step=freq_input,
#                                        sim_state=sim_state)

# BV.climatic.update_runoff(BV.climatic.runoff/1000, sim_state=sim_state) # from mm to m
BV.climatic.recharge = (BV.climatic.precip - BV.climatic.runoff - BV.climatic.etp)*0.94
BV.climatic.update_recharge(BV.climatic.recharge,sim_state=sim_state)
BV.climatic.runoff = BV.climatic.runoff*0.94
BV.climatic.etp = BV.climatic.etp * 0.94
#%% R and r ASSIGNATION
if isinstance(BV.climatic.recharge, float):
    print(f"Time-space daily average value for recharge = {BV.climatic.recharge} m")
    print(f"Time-space daily average value for runoff = {BV.climatic.runoff} m")
else:
    if isinstance(BV.climatic.recharge, xr.core.dataset.Dataset):
        R = BV.climatic.recharge.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        r = BV.climatic.runoff.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
    elif isinstance(BV.climatic.recharge, pd.core.series.Series):  
        R = BV.climatic.recharge
        r = BV.climatic.runoff
        
#%% Qobs FORMATTING et F normalization 
##option 1 
# Qobs_path = os.path.join(specific_data_path,'hydrometry','J560681001.csv')
# Qobs = pd.read_csv(Qobs_path, delimiter=';')
# #print (Qobs.columns)
# #print(Qobs.head())
# Qobs["date"] = pd.to_datetime(Qobs["date"], format='%d/%m/%Y')
# Qobs.set_index("date", inplace=True)

# Qobs = Qobs.rename(columns={'Q_Lperday': 'Q'})
# Qobs['Q'] = Qobs['Q'] / 1000  # L/d to m3/d
# area = int(round(BV.geographic.area))
# Qobs = (Qobs / (area*1000000)) # m3/d to m/day
# Qobsyear = Qobs.resample('Y').sum().mean().values[0] # m/day to m/y

#option 2 
Qobs_path = os.path.join(specific_data_path, 'hydrometry', 'J721401001.csv')
Qobs = pd.read_csv(Qobs_path, delimiter=',')
#print (Qobs.columns)
#print(Qobs.head())

Qobs["Date (TU)"] = pd.to_datetime(Qobs["date_obs_elab"], format='%Y-%m-%d')
Qobs.set_index("Date (TU)", inplace=True)

Qobs = Qobs.drop(columns=["date_obs_elab","grandeur_hydro_elab","libelle_qualification","specific_discharge"])
Qobs = Qobs.rename(columns={"resultat_obs_elab": "Q"})

area = int(round(BV.geographic.area))
Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
Qobsyear = Qobs.resample('Y').sum().mean().values[0]  # m/day to m/y

#%% Q resample by timescale
Qobsmonth = Qobs.resample('M').sum()
Qobsweek = Qobs.resample('W').sum()
Qobsweekmm = Qobsweek * 1000 # m/day to mm/week
Qobsweekmm = select_period(Qobsweekmm, first_year, last_year)
Qobsmonthmm = Qobsmonth * 1000 # m/day to mm/month
Qobsmonthmm = select_period(Qobsmonthmm, first_year, last_year)

if freq_input == 'D':
    Qobsmm = Qobs * 1000 # m/day to mm/day
    Qobsmm = select_period(Qobsmm, first_year, last_year)
    print(f"Qobsday : {Qobsmm}")
if freq_input == 'W':
    Qobsmm = select_period(Qobsweekmm,first_year,last_year)
    print(f"Qobs : {Qobsweekmm}")
    Qobsmm = Qobsmm.resample('W').mean() # to calculate the mean value as the same shape as modflow input value
if freq_input == 'M':
    Qobsmm = select_period(Qobsmonthmm,first_year,last_year)
    print(f"Qobs : {Qobsmonthmm}")
    Qobsmm = Qobsmm.resample('M').mean() # to calculate the mean value as the same shape as modflow input value

#%% R AND r RESAMPLE BY YEAR AND NORMALIZATION
#! ne pas faire tourner deux fois de suite sinon le facteur de normalisation tombe à 1 ou 0.99 car ca reprend les valeurs déja pondérées (serpent qui se mort la queue)

# if freq_input == 'W':
#     Rec = R*7
#     run = r * 7
# elif freq_input == 'M':
#     Rec = R * R.index.day
#     run = r * R.index.day
# else :
#     Rec = R
#     run = r

# Rannual = Rec.resample('Y').sum().mean()
# rannual = run.resample('Y').sum().mean()
# Qsafran = Rannual+rannual

# F = Qobsyear / Qsafran

# print (f'F = {F}')
# R = R * F
# r = r * F

# #%% PLOT Precip and Q
# # =============================================================================
# precip_mm_day = BV.climatic.precip * 1000  # m/day to mm/day
# Qobs_mm_day = Qobs * 1000  # m/day to mm/day

# fig, ax1 = plt.subplots(figsize=(8, 5))

# # Plot Qobs on the left y-axis
# ax1.plot(Qobs_mm_day, label='Qobs', c='navy', lw=2)
# ax1.set_ylabel('Qobs [mm/day]', color='navy')
# ax1.set_yscale('log')
# ax1.set_ylim(1e-2, 1e5)
# ax1.tick_params(axis='y', labelcolor='navy')
# ax1.set_xlim(pd.to_datetime(f'{first_year}'), pd.to_datetime(f'{last_year}'))

# # Create a second y-axis for precip on the right
# ax2 = ax1.twinx()
# ax2.plot(precip_mm_day, label='precip', c='blue', lw=2)
# ax2.set_ylabel('Precip [mm/day]', color='blue')
# ax2.set_ylim(60,0)  # Reverse the y-axis for precip
# ax2.tick_params(axis='y', labelcolor='blue')

# # Add a title and grid
# plt.title('Precipitation and Qobs')
# ax1.grid()

# # Show the plot
# plt.tight_layout()
# plt.savefig(os.path.join(watershed_path,'precip_discharge.png'), dpi=300)
# plt.show()

#%% PLOT INPUT DATA 
fig, ax = plt.subplots(1,1, figsize=(6,3))

if freq_input == 'D':   
    ax.plot(BV.climatic.recharge*1000, label='recharge', c='purple', lw=0.5)
    ax.plot(BV.climatic.precip*1000, label='precip', c='dodgerblue', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(BV.climatic.runoff*1000, label='runoff', c='cyan', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(BV.climatic.etp*1000, label='etp', c='orange', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(Qobsmm, label='Qobs', c='darkgreen', lw=0.5)

elif freq_input == 'W':
    ax.plot(BV.climatic.recharge*7*1000, label='recharge_reanalysis_normalized', c='purple', lw=0.5)
    ax.plot(BV.climatic.precip*7*1000, label='precip', c='dodgerblue', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(BV.climatic.runoff*7*1000, label='runoff', c='cyan', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(BV.climatic.etp*7*1000, label='etp', c='orange', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(Qobsmm, label='Qobs', c='darkgreen', lw=0.5)
    
elif freq_input == 'M':
    ax.plot(BV.climatic.recharge*BV.climatic.recharge.index.day*1000, label='recharge_reanalysis_normalized', c='purple', lw=0.5)
    ax.plot(BV.climatic.precip*BV.climatic.precip.index.day*1000, label='precip', c='dodgerblue', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(BV.climatic.runoff*BV.climatic.runoff.index.day*1000, label='runoff', c='cyan', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(BV.climatic.etp*BV.climatic.etp.index.day*1000, label='etp', c='orange', linestyle='--', lw=0.5, alpha=0.5)
    ax.plot(Qobsmm, label='Qobs', c='darkgreen', lw=0.5)

ax.set_xlabel('Date')
ax.set_ylabel(f'[mm/{freq_input}]')
ax.set_yscale('log')
plt.xticks(rotation=45, ha="right")
ax.legend()
plt.savefig(os.path.join(out_path, watershed_name, 'results_stable', '_figures', 'R_r.png'), dpi=300)

# #%% Plots R et r
# Qnormalized = Rec+run
# fig, ax = plt.subplots(1,1, figsize=(6,3))
# ax.plot(Qnormalized*1000, label='Qnormalized', c='orange', lw=0.5)
# ax.plot(Rec*1000, label='recharge_reanalysis_normalized', c='dodgerblue', lw=0.5)
# # ax.plot(r, label='runoff_reanalysis_normalized', c='navy', lw=0.5)
# ax.plot(Qobsmm, label='Qobs', c='darkgreen', lw=0.5)
# # ax.plot(BV.climatic.precip*1000, label='precip', c='blue', lw=0.5, linestyle = '--')
# # ax.plot(BV.climatic.recharge, label='recharge_reanalysis', c='deepskyblue', lw=0.5,  linestyle = '--')
# # ax.plot(BV.climatic.runoff, label='runoff_reanalysis', c='black', lw=0.5,  linestyle = '--')
# ax.set_xlabel('Date')
# ax.set_ylabel(f'[mm/{freq_input}]')
# ax.set_yscale('log')
# plt.xticks(rotation=45, ha="right")
# ax.legend()
# plt.savefig(os.path.join(out_path, watershed_name, 'results_stable', '_figures', 'R_r.png'), dpi=300)

#%% DEFINE

# Frame settings
box = True # or False
sink_fill = False # or True

# sim_state = 'transient' # 'steady' or 'transient'
sim_state = sim_state # 'steady' or 'transient'
plot_cross = False
dis_perlen = True

# Climatic settings
first_clim = 'mean' # or 'first or value
freq_time = freq_input

# Hydraulic settings
nlay = 10
lay_decay = 1 # 1 for no decay
bottom = 0 # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = None # if bottom is None, aquifer thickness
alpha = 0.03
hk = 1.37e-5 * 3600 * 24 # m/day
hk_decay = (alpha, None, True, [])
cond_drain = None # or value of conductance
exdp = 13.9
sy = 10.7/100
sy_decay = (alpha/2, None, True, [])
ss = 1e-5
ss_decay = (alpha/2, None, True, [])

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
split_temp = True

# # Particle tracking settings
# zone_partic = 'domain' # or watershed

plt.plot(hk/R)
# plt.yscale('log')

iD_set_simulations = 'explorSy_test1'

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

# Frame settings
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross)

# Climatic settings
recharge = R.copy()
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

runoff = r.copy()
BV.climatic.update_runoff(runoff, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_hk(hk)
BV.hydraulic.update_hk_decay(hk_decay_value=hk_decay[0], 
                             min_value=hk_decay[1], 
                             log_transf=hk_decay[2], 
                             grad_elev=hk_decay[3])
BV.hydraulic.update_sy(sy)
BV.hydraulic.update_sy_decay(sy_decay_value = sy_decay[0], 
                             min_value=sy_decay[1], 
                             log_transf=sy_decay[2], 
                             grad_elev=sy_decay[3])
BV.hydraulic.update_ss(ss)
BV.hydraulic.update_ss_decay(ss_decay_value=ss_decay[0], 
                             min_value=ss_decay[1],
                             log_transf=ss_decay[2], 
                             grad_elev=ss_decay[3])
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_exdp(exdp)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_dis_perlen(dis_perlen)

# Particle tracking settings
BV.settings.update_input_particles(zone_partic=BV.geographic.watershed_box_buff_dem) # or 'seepage_path'

#%% ---- MODELING
#%% MODFLOW

list_model_name = []
list_success_modflow = []
list_model_modflow = []


    
model_name = iD_set_simulations+'_'+str(round(sy))+'_'+str(round(hk,3)) # +'_'+str(round(thick,3))
BV.settings.update_model_name(model_name)
print(model_name)

model_modflow = BV.preprocessing_modflow(for_calib=False)
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

list_model_name.append(model_name)
list_success_modflow.append(success_modflow)
list_model_modflow.append(model_modflow)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_success_modflow'] = list_success_modflow
dictio['list_model_modflow'] = list_model_modflow
h5file = os.path.join(simulations_folder, 'results_listing_'+iD_set_simulations)
    
dd.io.save(h5file, dictio)

#%% RELOAD

h5file = os.path.join(simulations_folder, 'results_listing_'+iD_set_simulations)
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_success_modflow = d['list_success_modflow'][:]
list_model_modflow = d['list_model_modflow'][:]
print 
#%% POSTPROCESSING

# from importlib import reload
# reload(watershed_root)
# reload(modflow)

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    if success_modflow == True:
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  watertable_depth= True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  accumulation_flux = True,
                                  persistency_index=True,
                                  intermittency_monthly=True,
                                  intermittency_daily=False,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          datetime_format=True, 
                                                          subbasin_results=True,
                                                          intermittency_monthly=True) # or None
        
        netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                                  datetime_format=True)

#%% ---- PLOT
#%% CROSS MIN MAX
dates = pd.date_range(start=f'01/01/{first_year}', end=f'31/12/{last_year}', freq=freq_input)
    
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

simul_list = sorted(glob.glob(os.path.join(simulations_folder, iD_set_simulations+'*')),
                    key=os.path.getmtime)

fig, ax = plt.subplots(1, 1, figsize=(10, 5), dpi=300)

for i, simul in enumerate(simul_list[:]):
        
    model_name = os.path.split(simul)[-1]

    Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    Smod = Smod.reset_index()
    argmin = Smod['total_areas'].argmin()
    argmax = Smod['total_areas'].argmax()
    
    mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
        
    watertable_elevation = np.load(os.path.join(simulations_folder, 
                                                model_name, '_postprocess',
                                                'watertable_elevation'+'.npy'),
                                   allow_pickle=True).item()
    
    for key, color, label in zip([argmin, argmax], ['navy', 'dodgerblue'], ['Min', 'Max']):
        dem_data = imageio.imread(BV.geographic.watershed_dem)
        wt_data = watertable_elevation[key]
        
        cur_x = dem_data.shape[1] /2
        cur_y = dem_data.shape[0] /2 # 39
        
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof < 0] = np.nan
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof < 0] = np.nan
        
        dem_h_plot = dem_prof[int(cur_y), :]
        dem_h_plot[dem_h_plot == 0] = np.nan
        wt_h_plot = wt_prof[int(cur_y), :]
        wt_h_plot[wt_h_plot == 0] = np.nan
        
        ax.fill_between(np.arange(dem_h_plot.size) * 75, dem_h_plot - 30, wt_h_plot,
                        color=color, alpha=0.5, lw=0)
        ax.fill_between(np.arange(dem_h_plot.size) * 75, wt_h_plot, dem_h_plot,
                        color='saddlebrown', alpha=0.5, lw=0)  # Fill the space between max and topography
        ax.plot(np.arange(dem_h_plot.size) * 75, wt_h_plot, color=color, lw=1, label=f'{label} {str(dates[key])[:7]}')
    
    ax.fill_between(np.arange(dem_h_plot.size) * 75, 0, dem_h_plot - 30,
                    color='lightgrey', alpha=0.5, lw=0)
    ax.plot(np.arange(dem_h_plot.size) * 75, dem_h_plot - 30, color='dimgray', lw=1.5)
    ax.plot(np.arange(dem_h_plot.size) * 75, dem_h_plot, 'saddlebrown', lw=1.5, label='DEM')
    
# ax.set_xlim(4000, 12000)
# ax.set_ylim(20, 200)
ax.set_yticks([50, 100, 150, 200])
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Elevation [m]')
ax.legend()
ax.set_title('Water Table Elevation Profiles', fontsize=10)

fig.tight_layout()
fig.savefig(os.path.join(simulations_folder, '_figures',
            'CROSS_'+iD_set_simulations+'.png'),
            bbox_inches='tight')
 
#%% MAP MIN MAX
dates = pd.date_range(start='01/01/1981', end='31/12/2024', freq=freq_input)
    
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))

simul_list = sorted(glob.glob(os.path.join(simulations_folder, iD_set_simulations+'*')),
                   key=os.path.getmtime)
        
for simul in simul_list[:]:
    
    model_name = os.path.split(simul)[-1]
        
    Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
    min_area = Smod['total_areas'].min()
    min_idx = np.argmin(Smod['total_areas'])
    max_area = Smod['total_areas'].max()
    max_idx = np.argmax(Smod['total_areas'])
    max_year = Smod['total_areas'].index[max_idx]
    
    acc_npy = np.load(os.path.join(simul, '_postprocess', 'accumulation_flux.npy'), allow_pickle=True).item()
    inf = 0
    sup = 12
    compt = 0
    step = int(round(len(acc_npy)/12))
    
    for i in range(step):
        print(str(i)+'/'+str(step))
        interv = list(acc_npy.items())[inf:sup]
        for key in range(len(interv)):
            interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))

        zero = acc_npy[0] * 0
        for j in range(len(interv)):
            tempo = interv[j].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy()
        days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
        days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
    
    fig, axs = plt.subplots(1,2, figsize=(7,6))
    axs = axs = axs.ravel()
    
    for k, j in enumerate([min_idx, max_idx]):
            
        ax = axs[k]
    
        year = Smod['total_areas'].index[j]
        val = Smod.iloc[j]['total_areas']

        days_flux = acc_npy[j]
        
        ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
                     pad=10, fontsize=10)
        ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
        ax.imshow(np.ma.masked_where((days_flux<=0) | (mask <0),
                                     days_flux), 
                  cmap = mpl.colors.ListedColormap(['navy'])) # dodgerblue
        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
        
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        ax.axis('off')
            
        try:
            path_sub = os.path.join(glob.glob(
                os.path.join(stable_folder, 'subbasin','intermittency*'))[0],
                'watershed_contour.shp')
            wbt.vector_lines_to_raster(path_sub,
                                       os.path.join(glob.glob(
                                           os.path.join(stable_folder,
                                                        'subbasin',
                                                        'intermittency*'))[0],
                                           'watershed_contour.tif'),
                                       base = os.path.join(stable_folder,
                                                           'geographic',
                                                           'watershed_dem.tif'))
            line_sub = imageio.imread(os.path.join(glob.glob(
                os.path.join(stable_folder, 'subbasin', 'intermittency*'))[0],
                'watershed_contour.tif'))
            line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
            ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('grey'))
        except:
            pass
        
    fig.suptitle(model_name.upper(), y=0.85, fontsize=8)
    
    fig.tight_layout()
                
    fig.savefig(os.path.join(simulations_folder, '_figures',
                'MAPminmax_'+model_name+'.png'),
                bbox_inches='tight')
    
#%% MAP MIN MAX Q5 AND Q95
# Calcul des quantiles 5% et 95%

dates = pd.date_range(start='01/01/1981', end='31/12/2024', freq=freq_input)
    
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))

simul_list = sorted(glob.glob(os.path.join(simulations_folder, iD_set_simulations+'*')),
                   key=os.path.getmtime)
        
for simul in simul_list[:]:
    
    model_name = os.path.split(simul)[-1]
        
    Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
    # Calculate 5% and 95% quantiles instead of min/max
    q5_area = Smod['total_areas'].quantile(0.05)
    q95_area = Smod['total_areas'].quantile(0.95)
    
    # Find indices corresponding to these quantiles (closest values)
    q5_idx = np.argmin(np.abs(Smod['total_areas'].values - q5_area))
    q95_idx = np.argmin(np.abs(Smod['total_areas'].values - q95_area))
    
    acc_npy = np.load(os.path.join(simul, '_postprocess', 'accumulation_flux.npy'), allow_pickle=True).item()
    inf = 0
    sup = 12
    compt = 0
    step = int(round(len(acc_npy)/12))
    
    for i in range(step):
        print(str(i)+'/'+str(step))
        interv = list(acc_npy.items())[inf:sup]
        for key in range(len(interv)):
            interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))

        zero = acc_npy[0] * 0
        for j in range(len(interv)):
            tempo = interv[j].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy()
        days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
        days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
    
    fig, axs = plt.subplots(1,2, figsize=(7,6))
    axs = axs = axs.ravel()
    
    for k, j in enumerate([q5_idx, q95_idx]):
            
        ax = axs[k]
    
        year = Smod['total_areas'].index[j]
        val = Smod.iloc[j]['total_areas']

        days_flux = acc_npy[j]
        
        # Add quantile label to title
        label_text = f'Q5 ({str(year)[0:10]})' if k == 0 else f'Q95 ({str(year)[0:10]})'
        ax.set_title(label_text + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
                     pad=10, fontsize=10)
        ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
        ax.imshow(np.ma.masked_where((days_flux<=0) | (mask <0),
                                     days_flux), 
                  cmap = mpl.colors.ListedColormap(['navy'])) # dodgerblue
        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
        
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        ax.axis('off')
            
        try:
            path_sub = os.path.join(glob.glob(
                os.path.join(stable_folder, 'subbasin','intermittency*'))[0],
                'watershed_contour.shp')
            wbt.vector_lines_to_raster(path_sub,
                                       os.path.join(glob.glob(
                                           os.path.join(stable_folder,
                                                        'subbasin',
                                                        'intermittency*'))[0],
                                           'watershed_contour.tif'),
                                       base = os.path.join(stable_folder,
                                                           'geographic',
                                                           'watershed_dem.tif'))
            line_sub = imageio.imread(os.path.join(glob.glob(
                os.path.join(stable_folder, 'subbasin', 'intermittency*'))[0],
                'watershed_contour.tif'))
            line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
            ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('grey'))
        except:
            pass
        
    fig.suptitle(model_name.upper(), y=0.85, fontsize=8)
    
    fig.tight_layout()
                
    fig.savefig(os.path.join(simulations_folder, '_figures',
                'MAP_Q5_Q95_'+model_name+'.png'),
                bbox_inches='tight')

#%% PERSISTENCY

simul_list = sorted(glob.glob(os.path.join(simulations_folder, 
                                           iD_set_simulations+'*')),
                   key=os.path.getmtime)

line = imageio.imread(os.path.join(stable_folder,
                                   'geographic',
                                   'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder,
                                   'geographic',
                                   'watershed_dem.tif'))

fig, ax = plt.subplots(1, 1, figsize=(7, 6))

for i, simul in enumerate(simul_list[:1]):  # Only process the first simulation
        
    model_name = os.path.split(simul)[-1]

    pi = imageio.imread(os.path.join(simul, r'_postprocess/_rasters',
                                     'persistency_index_t(-).tif'))
    pi = np.ma.masked_where(pi == -9999, pi)
    pi = np.ma.masked_where(mask == -99999, pi)
    
    im = ax.imshow(pi, cmap='jet')
    
    ax.imshow(line, mpl.colors.ListedColormap(['k']),
              vmin=0, vmax=1)
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')
    
    ax.set_title(model_name.upper(), fontsize=8)
    
    cbar_ax = fig.add_axes([0.25, 0, 0.5, 0.02])
    cb = fig.colorbar(im, cax=cbar_ax, orientation="horizontal", pad=0.2)
    cb.set_label('Persistency index [-]', fontsize=10)

fig.tight_layout()

fig.savefig(os.path.join(simulations_folder, '_figures',
            'PI'+iD_set_simulations+'.png'),
            bbox_inches='tight')
    
#%% STREAMFLOW
#%% SEWAGE INPUT 
# area = int(round(BV.geographic.area))
# sewage_path = os.path.join (data_path, 'sewage_input.csv')
# sewage = pd.read_csv(sewage_path, sep=';', skiprows = 2,  parse_dates = ['DATE_MESURE'], index_col = 'DATE_MESURE')
# sewage.index = pd.to_datetime(sewage.index, format='%d/%m/%Y')
# sewage_filtered = sewage[(sewage['Système EU'] == 'Langan') | (sewage['Système EU'] == 'Chapelle Chaussée (La)')] #La chapelle chaussée n'a pas de valeur donc on va mettre la règlementaire par défaut 
# sewage_input = sewage_filtered['Qs']
# sewage_input_mmmonth = (sewage_input/(area*1000000)).resample('M').sum()*1000

# regulatory_value = pd.DataFrame({
#     'month': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
#     'values': [150, 150, 150, 150, 50, 10, 10, 10, 10, 50, 150, 150]
# }).set_index('month') #va remplacer les valeurs de la chapelle chaussée par les valeurs règlementaires

# # Initialize Qregulatory column with None values
# sewage['Qregulatory'] = None

# # Loop through all dates in the index (which was DATE_MESURE)
# for date in sewage_filtered.index:
#     # Get the month from the date (1-12)
#     month = date.month
#     if month in regulatory_value.index:
#         sewage_filtered.loc[date, 'Qregulatory'] = regulatory_value.loc[month, 'values']  # Assign regulatory value
# sewage_regulatory_mcubepersecond = sewage_filtered['Qregulatory']*1000/(24*60*60) # convert to l/s
# sewage_regulatory_monthmm = (sewage_filtered['Qregulatory']/(area*1000000)).resample('M').sum()*1000

#%% FORMATTING QobsGAUGED STATION CSV + SEWAGE INPUT

simul_list = sorted(glob.glob(os.path.join(simulations_folder,
                                           iD_set_simulations+'*')),
                   key=os.path.getmtime)

for i, simul in enumerate(simul_list[:]):
    
    fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                 figsize=(10,3))

    model_name = os.path.split(simul)[-1]
        
    Smod_path = os.path.join(simul, 
                             r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    
    Qmod = Smod['outflow_drain'] 
    Qmod = Qmod.squeeze()
    Qmod = Qmod*1000
    Qmod = (Qmod + (r * 1000)) 
    
    if freq_input == 'M' :
        Qmod = Qmod* Qmod.index.day
    elif freq_input == 'W':
        Qmod = Qmod * 7    
    # Qmod_sewage = (Qmod + sewage_input_mmmonth + sewage_regulatory_monthmm)
    print (f'valeur de Qmod : {Qmod}')
    # Rmod = Smod['recharge'] 
    # print (f'valeur de Rmod : {Rmod}')
    
    yearsmaj = mdates.YearLocator(1)   # every year
    yearsmin = mdates.YearLocator(1)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')

    ax = a0
    if freq_input == 'D':
        ax.plot(Qobsmm, color='k', lw=1, ls='-', zorder=0, label='observed')
    if freq_input == 'W':
        ax.plot(Qobsweekmm, color='k', lw=1, ls='-', zorder=0, label='observed')
    if freq_input == 'M':
        ax.plot(Qobsmonthmm, color='k', lw=1, ls='-', zorder=0, label='observed')
    ax.plot(Qmod, color='red', lw=1, label='modeled')
    # ax.plot(Rmod.index, Rmod*1000, color='blue', lw=2.5)
    ax.set_xlabel('Date')
    ax.set_ylabel('Q / A [mm/month]')
    ax.set_yscale('log')
    ax.set_ylim(0.0001, 1000)
    # years_5 = mdates.YearLocator(5)  # every 5 years
    # ax.xaxis.set_major_locator(years_5)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)
    ax.set_xlim(pd.to_datetime(f'{first_year}-01'), pd.to_datetime(f'{last_year}-12'))
    # ax.set_xlim(pd.to_datetime(f'2023-01'), pd.to_datetime(f'2023-12'))
    ax.legend()
    ax.set_title(model_name.upper(), fontsize=10)
    for label in ax.get_xticklabels():
        label.set_rotation(45)
    # axb = ax.twinx()
    # axb.bar(Rmod.index, Rmod,color='blue', edgecolor='blue', lw=2.5)
    # axb.set_ylim(0,999)
    # axb.invert_yaxis()
    # axb.set_yticklabels([0.1,200])
    if freq_input == 'D':
        Qobs_stat = select_period(Qobsmm,first_year,last_year)
    if freq_input == 'W':
        Qobs_stat = select_period(Qobsweekmm,first_year,last_year)
    if freq_input == 'M':
        Qobs_stat = select_period(Qobsmonthmm,first_year,last_year)

    Qmod_stat = select_period(Qmod,first_year,last_year)
    
    import hydroeval as he
    NSE = he.evaluator(he.nse, Qmod_stat, Qobs_stat)[0]
    NSElog = he.evaluator(he.nse, Qmod_stat, Qobs_stat, transform='log')[0]
    RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qmod_stat.values)**2))
    KGE = he.evaluator(he.kge, Qmod_stat, Qobs_stat)[0][0]
    print(model_name.upper())
    print(f'NSE = {NSE}')
    print(f'NSElog = {NSElog}')
    print(f'RMSE = {RMSE}')
    print(f'KGE = {KGE}')
    
        # Store metrics in DataFrame
    metrics_df = pd.DataFrame({
        'model_name': [model_name],
        'NSE': [round(NSE, 2)],
        'NSElog': [round(NSElog, 2)],
        'RMSE': [round(RMSE, 2)],
        'KGE': [round(KGE, 2)]
    })
    
    # Define the CSV file path
    metrics_csv_path = os.path.join(simulations_folder, '_figures', 'model_metrics.csv')
    
    # Check if the file already exists to determine whether to write headers
    if os.path.isfile(metrics_csv_path):
        metrics_df.to_csv(metrics_csv_path, mode='a', header=False, index=False)
    else:
        metrics_df.to_csv(metrics_csv_path, index=False)
    
    
    ax = a1
    ax.scatter(Qobs_stat, Qmod_stat, edgecolor='none', alpha=0.75, facecolor='forestgreen')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.plot((0.01,1000),(0.01,1000), color='grey', zorder=-1)
    ax.set_xlim(0.01,1000)
    ax.set_ylim(0.01,1000)
    # ax.set_xlim(0.1,300)
    # ax.set_ylim(0.1,300)    
    ax.set_xlabel('$Q_{obs}$ / A [mm/month]', fontsize=12)
    ax.set_ylabel('$Q_{sim}$ / A [mm/month]', fontsize=12)
    fig.tight_layout()
                
    fig.savefig(os.path.join(simulations_folder, '_figures',
                'STREAMFLOW_'+model_name+'.png'),
                bbox_inches='tight')
    
# #%% VALUE PER YEAR FOR TURC BUDYKO EQUATION when timepath is daily
# Qmod_year = Smod['outflow_drain'] 
# Qmod_year = Qmod_year.squeeze()
# Qmod_year = Qmod_year*Qmod_year.index.day
# Qmod_year = Qmod_year*1000
# Qmod_year = (Qmod_year+ (r * 1000))
# Qmod_year = Qmod_year.resample('Y').sum().mean()
# print (Qmod_year)

# precip_year = BV.climatic.precip.resample('Y').sum().mean() * 1000  # mm
# etp_year = BV.climatic.etp.resample('Y').sum().mean() * 1000  # mm
# print(precip_year)
# print(etp_year)
#%% SATURATION

simul_list = sorted(glob.glob(os.path.join(simulations_folder,
                                           iD_set_simulations+'*')),
                   key=os.path.getmtime)

for i, simul in enumerate(simul_list[:]):
    
    model_name = os.path.split(simul)[-1]
        
    Sonde_path = os.path.join(glob.glob(
        os.path.join(simul, r'_subbasins/intermittency_*'))[0],
        '_simulated_timeseries.csv')
    Sonde = pd.read_csv(Sonde_path, sep=';', index_col=0, parse_dates=True)

    # BV.add_intermittency(data_path, 'regional onde stations.shp')

    # d = BV.intermittency.flowing
    # assec = d[d==1].dropna()
    # invi = d[d==2].dropna()
    # low = d[d==3].dropna()
    # accep = d[d==4].dropna()
    # visib = d[d==5].dropna()
    # d = d.resample('M').mean()
    
    # Smod['onde'] = d
    
    from datetime import timedelta
    x_months = Smod.index #+ timedelta(days=-30)
    Smod['date'] = x_months
    Smod.index = Smod['date']
    
    fig, ax = plt.subplots(1, 1, figsize=(7,3.5))
    
    ax.fill_between(Smod.index, 0, Smod['total_areas'],
                    interpolate=False, color='dodgerblue', alpha=0.5,
                    step='pre', label='Intermittent part')
    ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                    interpolate=False, color='navy', alpha=0.5,
                    step='pre', label='Perennial part')
    ax.legend()
    ax.step(Smod.index, Smod['total_areas'], color='dodgerblue',
            marker=None, markeredgecolor='none',
            markersize=5, lw=1, label='upstream',
            where='pre')
    ax.step(Smod.index, Smod['perenn_areas'], color='navy',
            marker=None, markeredgecolor='none',
            markersize=5, lw=1, label='upstream',
            where='pre')

    # ax.set_yticks(np.arange(0,15.05,2.5))
    ax.set_ylabel('Drainge density [%]')
    plt.xticks(rotation=45, ha="right")

    years_maj = mdates.YearLocator()   # every year
    months_maj = mdates.MonthLocator()  # every x month
    ax.xaxis.set_major_locator(years_maj)
    ax.xaxis.set_minor_locator(months_maj)
    
    ax.set_title(model_name.upper(), fontsize=10)
    
    fig.tight_layout()
                
    fig.savefig(os.path.join(simulations_folder, '_figures',
                'SATURATION_'+model_name+'.png'),
                bbox_inches='tight')
                
#%% ---- NOTES

os.chdir(root_dir)
#%%
