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

# Filter warnings (before imports)
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import pkg_resources # Must be placed after DeprecationWarning as it is itself deprecated
warnings.filterwarnings('ignore', message='.*pkg_resources.*')
warnings.filterwarnings('ignore', message='.*declare_namespace.*')

# Libraries installed by default
import sys
import os

# Libraries need to be installed if not
import numpy as np
import pandas as pd

import matplotlib as mpl
import matplotlib.pyplot as plt
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# # Libraries added from 'pip install' procedure
import deepdish as dd
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True
import xarray as xr
xr.set_options(keep_attrs = True)
import plotly.express as px

#%% ROOT

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(((abspath(__file__))))))
sys.path.append(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

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
study_site = 'CANUT'
first_year = 2021
last_year = 2021 #ne pas mettre none sinon ca va beuguer
freq_input = 'D' 
sim_state = 'transient'

out_path = folder_root.root_folder_results()
#out_path = r"C:\Users\theat\Documents\Python\Output_HydroModPy" # Manually set the output path
data_path = os.path.join(out_path, "data")
specific_data_path = os.path.join(data_path, study_site)

print(f"out_path; {out_path}, Data path: {data_path}, specific_data_folder; {specific_data_path}")

#%% ---- EXTRACT CATCHMENT
watershed_name = f"param_clim_data_{study_site}"

print('##### '+watershed_name.upper()+' #####')

watershed_path = os.path.join(out_path, watershed_name)
dem_path = os.path.join(data_path, 'dem', 'regional dem.tif')

#%% ---- WATERSHED
load = False
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = [327816.965, 6777886.670, 150, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
bottom_path = None # path
save_object = True

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

#%% climatic settings
BV.add_climatic() 

#%% Reanalyse
BV.climatic.update_sim2_reanalysis(var_list=['recharge', 'runoff', 'precip',
                                             'evt', 'etp', 't',
                                              ],
                                       nc_data_path=os.path.join(
                                           specific_data_path,
                                           f"Meteo\Historiques SIM2"), #Path to the folder containing the clipped SIM2 .nc files.
                                       first_year=first_year,
                                       last_year=last_year,
                                       time_step='D',
                                       sim_state=sim_state,
                                       spatial_mean=True,
                                       geographic=BV.geographic,
                                       disk_clip='watershed') # for clipping the netcdf files saved on disk
                                                                # can be a shapefile path or a flag: 'watershed' or False

# Units
BV.climatic.evt = BV.climatic.evt / 1000# from mm to m 
BV.climatic.etp = BV.climatic.etp / 1000 # from mm to m
BV.climatic.precip = BV.climatic.precip / 1000 # from mm to m
BV.climatic.t = BV.climatic.t / 1000 # from mm to m
BV.climatic.runoff = BV.climatic.runoff / 1000 # from mm to m
# BV.climatic.recharge = BV.climatic.recharge / 1000 # from mm to m
#%% SAFRAN
BV.add_safransurfex(r"C:\\Users\\theat\\Documents\\Python\\02_Output_HydroModPy\\data\\Meteo\\REA")

#%%RECHARGE REANALYSIS
BV.climatic.update_recharge_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_REC_D.csv'),
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=first_year,
                                       last_year=last_year,
                                       time_step='D',
                                       sim_state=sim_state)

BV.climatic.update_recharge(BV.climatic.recharge / 1000, sim_state=sim_state) # from mm to m
# #%% RUNOFF REANALYSIS
# BV.climatic.update_runoff_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_RUN_D.csv'),
#                                        clim_mod='REA',
#                                        clim_sce='historic',
#                                        first_year=first_year,
#                                        last_year=last_year,
#                                        time_step='D',
#                                        sim_state=sim_state)

# BV.climatic.update_runoff(BV.climatic.runoff / 1000, sim_state=sim_state) # from mm to m
#%% R et r affectation

if isinstance(BV.climatic.recharge, float):
    print(f"Time-space daily average value for recharge = {BV.climatic.recharge} m")
    print(f"Time-space daily average value for runoff = {BV.climatic.runoff} m")
    R = BV.climatic.recharge
    r = BV.climatic.runoff  
else:
    if isinstance(BV.climatic.recharge, xr.core.dataset.Dataset):
        R = BV.climatic.recharge.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        r = BV.climatic.runoff.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
    elif isinstance(BV.climatic.recharge, pd.core.series.Series):  
        R = BV.climatic.recharge
        r = BV.climatic.runoff  

#%% Qobs FORMATTING et F normalization 

# ## option 1
# Qobs_path = os.path.join(specific_data_path,'hydrometry','J560681001.csv')
# Qobs = pd.read_csv(Qobs_path, delimiter=';')
# #print (Qobs.columns)
# #print(Qobs.head())
# Qobs["date"] = pd.to_datetime(Qobs["date"], format='%d/%m/%Y')
# Qobs.set_index("date", inplace=True)

# Qobs = Qobs.drop(columns=["time"])
# Qobs = Qobs.rename(columns={'Q_Lperday': 'Q'})
# Qobs['Q'] = Qobs['Q'] / 1000  # L/d to m3/d
# area = int(round(BV.geographic.area))
# Qobs = (Qobs / (area*1000000)) # m3/d to m/day
# Qobsyear = Qobs.resample('Y').sum().mean().values[0] # m/day to m/y

## option 2
Qobs_path = os.path.join(specific_data_path,'hydrometry', 'J751301001.csv')
Qobs = pd.read_csv(Qobs_path, delimiter=',')
#print (Qobs.columns)
#print(Qobs.head())

Qobs["Date (TU)"] = pd.to_datetime(Qobs["date_obs_elab"], format='%Y-%m-%d')
Qobs.set_index("Date (TU)", inplace=True)

Qobs = Qobs.drop(columns=["date_obs_elab","grandeur_hydro_elab","libelle_qualification","specific_discharge"])
Qobs = Qobs.rename(columns={"resultat_obs_elab": "Q"})

area = int(round(BV.geographic.area))
Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day

# Filter Qobs to the same period as other variables
Qobs = select_period(Qobs, first_year, last_year)

Qobsyear = Qobs.resample('Y').sum().mean().values[0]  # m/day to m/y

#%% Q resample by timescale
if freq_input == 'M':
    Qobs =Qobs.resample('M').mean()
if freq_input == 'W':
    Qobs = Qobs.resample('W').mean()
# to calculate the mean value as the same shape as modflow input value

#%% R AND r RESAMPLE BY YEAR AND NORMALIZATION

Rannual = R.resample('Y').sum().mean()
rannual = r.resample('Y').sum().mean()
Qsafran = Rannual+rannual
F = Qobsyear / Qsafran
print (f'F = {F}')
R = R * F
r = r * F

if freq_input == 'M':

    precip = BV.climatic.precip.resample('M').mean()*F
    evt = BV.climatic.evt.resample('M').mean()*F
    etp = BV.climatic.etp.resample('M').mean()*F
    t = BV.climatic.t.resample('M').mean()*F
    R = R.resample('M').mean()*F
    r = r.resample('M').mean()*F

if freq_input == 'W':

    precip = BV.climatic.precip.resample('W').mean()*F
    evt = BV.climatic.evt.resample('W').mean()*F
    etp = BV.climatic.etp.resample('W').mean()*F
    t = BV.climatic.t.resample('W').mean()*F
    R = R.resample('W').mean()*F
    r = r.resample('W').mean()*F

# Define variables for all frequencies (including daily 'D')
if freq_input == 'D':
    precip = BV.climatic.precip*F
    evt = BV.climatic.evt*F
    etp = BV.climatic.etp*F
    t = BV.climatic.t*F
    R = R*F
    r = r*F
#%%Exportation des données climatiques
# =============================================================================
df_climatic = pd.DataFrame({
    'recharge': R,
    'runoff': r,
    'precip': precip,
    'evt': evt,
    'etp': etp,
    't': t,
    'p-r': precip - r,
    'p-r-evt' : precip - r - evt, 
    'discharge' : Qobs['Q'] 
    })

df_climatic.index.name = 'time'
df_climatic.to_csv(os.path.join(data_path, study_site, 'Meteo', 'Historiques SIM2', f'climatic_data_{first_year}_{last_year}.csv'))
# =============================================================================

#%% PLOT VARIABLES
# Create an interactive plot for the variables in df_climatic with a logarithmic y-axis
fig = px.line(df_climatic, x=df_climatic.index, y=df_climatic.columns, 
              title="Interactive Visualization of Climatic Variables (Log Scale)",
              labels={"value": "Values (Log Scale)", "time": "Time"},
              template="plotly")
            #   log_y=True)  # Set y-axis to logarithmic scale

# Define the full file path for saving the HTML
output_file_path = os.path.join(watershed_path, "climatic_variables_log.html")
fig.write_html(output_file_path)

# Show the plot
fig.show()

print(f"Figure saved at: {output_file_path}")

#%% means values 
# R = BV.climatic.recharge.resample('Y').sum().mean()#mm/year
# r = BV.climatic.runoff.resample('Y').sum().mean()#mm/year
# P_year = BV.climatic.precip.resample('Y').sum().mean()
# etp_year = BV.climatic.etp.resample('Y').sum().mean()
