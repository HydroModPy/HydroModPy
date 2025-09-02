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
root_dir = dirname(dirname(dirname(dirname(((abspath(__file__)))))))
sys.path.append(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

#%% HYDROMODPY

# Import HydroModPy modules
import NetCDFReader
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
first_year = 1960
last_year = 2024
parameters = '30_1.6e-5_0.2'
freq_input = 'M' 
sim_state = 'transient'
iD_set_simulations = 'explorSy_test1' #* ça il peut deviner le nom du dossier si je le met après le load de BV à revoir. 

out_path = folder_root.root_folder_results()
#out_path = r"C:\Users\theat\Documents\Python\Output_HydroModPy" # Manually set the output path
data_path = os.path.join(out_path, "data")
specific_data_path = os.path.join(data_path, study_site)

print(f"out_path; {out_path}, Data path: {data_path}, specific_data_folder; {specific_data_path}")
#%% ---- WATERSHED

#%% OPTIONS
# Name of the study site
# watershed_name = '_'.join([
#     "comparison_Q_HydroModPy_Simfen",study_site,parameters,str(first_year),str(last_year),
#     pd.to_datetime('today').strftime('%Y-%m-%d')
# ])
watershed_name = (f"Example_04_REA_{study_site}_{parameters}_{first_year}_{last_year}_{freq_input}_{sim_state}")

print('##### '+watershed_name.upper()+' #####')

watershed_path = os.path.join(out_path, watershed_name)
dem_path = os.path.join(data_path, 'regional dem.tif')

load = True
# watershed_name ='Strengbach'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = None # [x, y, snap distance, buffer size, crs proj]
bottom_path = None # path
save_object = True

#%% GEOGRAPHIC
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

#%%RECHARGE REANALYSIS
BV.climatic.update_recharge_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_REC_D.csv'),
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=first_year,
                                       last_year=last_year,
                                       time_step=freq_input,
                                       sim_state=sim_state)

BV.climatic.recharge = BV.climatic.recharge * BV.climatic.recharge.index.day #meandaypermonth to mm/month
BV.climatic.update_recharge(BV.climatic.recharge/1000, sim_state = sim_state) # from mm to m
BV.climatic.update_recharge(BV.climatic.recharge.resample('Y').sum(), sim_state = sim_state) # month to year
#%% RUNOFF REANALYSIS
BV.climatic.update_runoff_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_RUN_D.csv'),
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=first_year,
                                       last_year=last_year,
                                       time_step=freq_input,
                                       sim_state=sim_state)

BV.climatic.runoff = BV.climatic.runoff* BV.climatic.runoff.index.day #meandaypermonth to mm/month
BV.climatic.update_runoff(BV.climatic.runoff/1000, sim_state = sim_state) # from mm to m
BV.climatic.update_runoff(BV.climatic.runoff.resample('Y').sum(), sim_state = sim_state) # month to year

#%% FORMATTING RECHARGE AND RUNOFF

if isinstance(BV.climatic.recharge, float):
    print(f"Time-space daily average value for recharge = {BV.climatic.recharge} m")
    print(f"Time-space daily average value for runoff = {BV.climatic.runoff} m")
else:
    if isinstance(BV.climatic.recharge, xr.core.dataset.Dataset):
        R = BV.climatic.recharge.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        r = BV.climatic.runoff.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        R = R.resample('M').sum()
        r = r.resample('M').sum()
    elif isinstance(BV.climatic.recharge, pd.core.series.Series):  
        R = BV.climatic.recharge
        r = BV.climatic.runoff      

# Qsafran = R+r

#%% Qobs FORMATTING
Qobs = os.path.join(data_path,'J7214010_QmnJ(n=1_non-glissant)_01011981_31122024.csv')
Qobs = pd.read_csv(Qobs, delimiter=',')
#print (Qobs.columns)
#print(Qobs.head())
# Split the values at 'T' for the 'Date(TU)' column and remove the values after 'T'
Qobs["Date (TU)"] = Qobs["Date (TU)"].str.split('T').str[0]
Qobs["Date (TU)"] = pd.to_datetime(Qobs["Date (TU)"], format='%Y-%m-%d')
Qobs.set_index("Date (TU)", inplace=True)
Qobs = Qobs.drop(columns=["Statut", "Qualification", "Méthode", "Continuité"])

# print(Qobs.index)
# print ('--------')
# print (Qobs.columns)

Qobs = Qobs.squeeze()
Qobs = Qobs.rename('Q')
area = int(round(BV.geographic.area))
Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
Qobs = Qobs.resample('Y').sum() # m3/s to m/day

# F = Qobs / Qsafran


#%%Format for plots  
        
# Plots
fig, ax = plt.subplots(1,1, figsize=(6,3))
ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=0.5)
ax.plot(r, label='runoff_reanalysis', c='navy', lw=0.5)
ax.set_xlabel('Date')
ax.set_ylabel('[mm/]') #* rewrite when unit changes
plt.xticks(rotation=45, ha="right")
ax.legend()

#%% FORMATTING Q CSV

Qsim_simfen_path = os.path.join(specific_data_path,'simulation_01011964_31122023_simfen_LA_FLUME','output_simulation.csv')
Qsim_simfen = pd.read_csv(Qsim_simfen_path, sep=';',skiprows=7, index_col=0)

Qobs = select_period(Qobs, 1981, 2024)
robs= select_period(r, 1981, 2024)
#print(robs)

#Afficher les premières lignes pour vérifier le format des dates
#print(Qsim_simfen.head())
Qsim_simfen.index = pd.to_datetime(Qsim_simfen.index, format='%Y-%m-%d')
#print(type(Qsim_simfen.index))
Qsim_simfen = Qsim_simfen.squeeze()
Qsim_simfen = Qsim_simfen.rename('Q')
Qsim_simfen = select_period(Qsim_simfen, 1981, 2024)
rsim = select_period(r, 1981, 2024)
#print(rsim)

#%% normalisation R et r sur Qobs

# ratio = Qobs / (R+r)
# print (ratio)

# Plots
fig, ax = plt.subplots(1,1, figsize=(6,3))
ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=0.5)
ax.plot(r, label='runoff_reanalysis', c='navy', lw=0.5)
ax.set_xlabel('Date')
ax.set_ylabel('[m/D]') #*rewrite when unit changes
plt.xticks(rotation=45, ha="right")
ax.legend()

#%% STREAMFLOW
import hydroeval as he
    
area = int(round(BV.geographic.area))

Qobs = (Qobs / 1000 / (area*1000000)) * (3600 * 24) # m3/s to m/day
Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month  

Qsim_simfen = (Qsim_simfen / (area*1000000)) * (3600 * 24) # m3/s to m/day
Qsim_simfen = Qsim_simfen.resample('M').sum() * 1000 # m/day to mm/month

simul_list = sorted(glob.glob(os.path.join(simulations_folder,
                                           iD_set_simulations+'*')),
                   key=os.path.getmtime)

for i, simul in enumerate(simul_list[:]):
    
    fig, axes = plt.subplots(3, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(24,12))
    a0, a1, a2, a3, a4, a5 = axes.flatten()

    model_name = os.path.split(simul)[-1]
        
    Smod_path = os.path.join(simul, 
                             r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    
    Qmod = Smod['outflow_drain'] 
    Qmod = Qmod.squeeze() * 1000
    Qmod = (Qmod + (r * 1000)) * Qmod.index.day #index par la valeur contenue dans days (qui est le dernier jour du mois) et multiplie par cette valeur = mm/mois
    print (f'valeur de Qmod : {Qmod}')
    Rmod = Smod['recharge'] * Qmod.index.day
    
    yearsmaj = mdates.YearLocator(1)   # every year
    yearsmin = mdates.YearLocator(1)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')

    ax = a0
    ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='observed')
    ax.plot(Qmod, color='red', lw=2, label='modeled_hydromoodpy')
    # ax.plot(Rmod.index, Rmod*1000, color='blue', lw=2.5)
    ax.set_xlabel('Date')
    ax.set_ylabel('Q / A [mm/month]')
    ax.set_yscale('log')
    ax.set_ylim(0.0001, 200)
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)
    ax.set_xlim(pd.to_datetime('1994'), pd.to_datetime('2023'))
    ax.legend(labelspacing=1.2, loc='lower right', fontsize=12)
    ax.set_title(model_name.upper())
    for label in ax.get_xticklabels():
        label.set_rotation(45)
    
    # axb = ax.twinx()
    # axb.bar(Rmod.index, Rmod,color='blue', edgecolor='blue', lw=2.5)
    # axb.set_ylim(0,999)
    # axb.invert_yaxis()
    # axb.set_yticklabels([0.1,200])
    
    Qobs_stat = select_period(Qobs,1994,2023)
    Qmod_stat = select_period(Qmod,1994,2023)
    Qsim_simfen_stat = select_period(Qsim_simfen,1994,2023)
    
    ax = a1
    ax.scatter(Qobs_stat, Qmod_stat,
               s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.plot((0.01,1000),(0.01,1000), color='grey', zorder=-1)
    ax.set_xlim(0.1,500)
    ax.set_ylim(0.1,500)
    # ax.set_xlim(0.1,300)
    # ax.set_ylim(0.1,300)    
    ax.set_xlabel('$Q_{obs}$ / A [mm/month]')
    ax.set_ylabel('$Q_{sim}$ / A [mm/month]')
                
    fig.savefig(os.path.join(simulations_folder, '_figures',
                'STREAMFLOW_'+model_name+'.png'),
                bbox_inches='tight')
    
    NSE_mod_obs = he.evaluator(he.nse, Qmod_stat, Qobs_stat)[0]
    NSElog_mod_obs = he.evaluator(he.nse, Qmod_stat, Qobs_stat, transform='log')[0]
    RMSE_mod_obs = np.sqrt(np.nanmean((Qobs_stat.values-Qmod_stat.values)**2))
    KGE_mod_obs = he.evaluator(he.kge, Qmod_stat, Qobs_stat)[0][0]
    print(model_name.upper())
    print(round(NSE_mod_obs,2))
    print(round(NSElog_mod_obs,2))
    print(round(RMSE_mod_obs,2))
    print(round(KGE_mod_obs,2))
    
    ax = a2
    ax.plot(Qsim_simfen, color='b', lw=2, ls='-', zorder=0, label='modeled_simfen')
    ax.plot(Qobs, color='k', lw=2, label='observed')
    # ax.plot(Rmod.index, Rmod*1000, color='blue', lw=2.5)
    ax.set_xlabel('Date')
    ax.set_ylabel('Q / A [mm/month]')
    ax.set_yscale('log')
    ax.set_ylim(0.0001, 200)
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)
    ax.set_xlim(pd.to_datetime('1994'), pd.to_datetime('2023'))
    ax.legend(labelspacing=1.2, loc='lower right', fontsize=12)
    ax.set_title(model_name.upper())
    for label in ax.get_xticklabels():
        label.set_rotation(45)
        
    ax = a3
    ax.scatter(Qsim_simfen_stat, Qobs_stat,
               s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.plot((0.01,1000),(0.01,1000), color='grey', zorder=-1)
    ax.set_xlim(0.1,500)
    ax.set_ylim(0.1,500)
    # ax.set_xlim(0.1,300)
    # ax.set_ylim(0.1,300)    
    ax.set_xlabel('$Q_{obs}$ / A [mm/month]')
    ax.set_ylabel('$Q_{sim}$ / A [mm/month]')
                
    fig.savefig(os.path.join(simulations_folder, '_figures',
                'STREAMFLOW_'+model_name+'.png'),
                bbox_inches='tight')
    
    NSE_simfen_obs = he.evaluator(he.nse, Qsim_simfen_stat, Qmod_stat)[0]
    NSElog_simfen_obs = he.evaluator(he.nse, Qsim_simfen_stat, Qmod_stat, transform='log')[0]
    RMSE_simfen_obs = np.sqrt(np.nanmean((Qmod_stat.values-Qsim_simfen_stat.values)**2))
    KGE_simfen_obs = he.evaluator(he.kge, Qsim_simfen_stat, Qmod_stat)[0][0]
    print(model_name.upper())
    print(round(NSE_simfen_obs,2))
    print(round(NSElog_simfen_obs,2))
    print(round(RMSE_simfen_obs,2))
    print(round(KGE_simfen_obs,2))
    
    ax = a4
    ax.plot(Qsim_simfen, color='b', lw=2, ls='-', zorder=0, label='modeled_simfen')
    ax.plot(Qmod, color='red', lw=2, label='modeled_hydromodpy')
    # ax.plot(Rmod.index, Rmod*1000, color='blue', lw=2.5)
    ax.set_xlabel('Date')
    ax.set_ylabel('Q / A [mm/month]')
    ax.set_yscale('log')
    ax.set_ylim(0.0001, 200)
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)
    ax.set_xlim(pd.to_datetime('1994'), pd.to_datetime('2023'))
    ax.legend(labelspacing=1.2, loc='lower right', fontsize=12)
    ax.set_title(model_name.upper())
    for label in ax.get_xticklabels():
        label.set_rotation(45)
        
    ax = a5
    ax.scatter(Qmod_stat, Qsim_simfen_stat,
               s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.plot((0.01,1000),(0.01,1000), color='grey', zorder=-1)
    ax.set_xlim(0.1,500)
    ax.set_ylim(0.1,500)
    # ax.set_xlim(0.1,300)
    # ax.set_ylim(0.1,300)    
    ax.set_xlabel('$Q_{obs}$ / A [mm/month]')
    ax.set_ylabel('$Q_{sim}$ / A [mm/month]')
    
    fig.tight_layout()
    plt.subplots_adjust(hspace=1, wspace=0.2)
    
    fig.savefig(os.path.join(simulations_folder, '_figures',
                'STREAMFLOW_'+model_name+'.png'),
                bbox_inches='tight')
    
    NSE_simfen_mod = he.evaluator(he.nse, Qsim_simfen_stat, Qmod_stat)[0]
    NSElog_simfen_mod = he.evaluator(he.nse, Qsim_simfen_stat, Qmod_stat, transform='log')[0]
    RMSE_simfen_mod = np.sqrt(np.nanmean((Qmod_stat.values-Qsim_simfen_stat.values)**2))
    KGE_simfen_mod = he.evaluator(he.kge, Qsim_simfen_stat, Qmod_stat)[0][0]
    print(model_name.upper())
    print(round(NSE_simfen_mod,2))
    print(round(NSElog_simfen_mod,2))
    print(round(RMSE_simfen_mod,2))
    print(round(KGE_simfen_mod,2))
#%%
os.chdir(root_dir)
