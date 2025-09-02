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
root_dir = dirname(dirname(dirname(((abspath(__file__))))))
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
parameters = "1.6e-5_0.2"
out_path = folder_root.root_folder_results()
#out_path = r"C:\Users\theat\Documents\Python\Output_HydroModPy" # Manually set the output path
data_path = os.path.join(out_path, "data")
specific_data_path = os.path.join(data_path, study_site)

print(f"out_path; {out_path}, Data path: {data_path}, specific_data_folder; {specific_data_path}")

#%% ---- WATERSHED
#%% OPTIONS
# Name of the study site
watershed_name = '_'.join([
    "Example_04_REA",study_site,parameters,str(first_year),str(last_year),freq_input,sim_state
])

print('##### '+watershed_name.upper()+' #####')

watershed_path = os.path.join(out_path, watershed_name)
dem_path = os.path.join(data_path, 'regional dem.tif')

load = False
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
BV.add_geology(data_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
BV.add_hydrography(data_path, types_obs=['regional stream network'])
BV.add_hydrometry(data_path, 'france hydrometric stations.shp')
BV.add_intermittency(data_path, 'regional onde stations.shp')
# BV.add_piezometry()

#Extract some subbasin from data available above
BV.add_subbasin(os.path.join(data_path, 'additional'), 150)

# # General plot of the study site
# visualization_watershed.watershed_geology(BV)
# visualization_watershed.watershed_dem(BV)

#%% ---- RECHARGE
#%% climatic settings
BV.add_climatic()
first_year = first_year
last_year = last_year

##%%% Reanalyse
BV.climatic.update_sim2_reanalysis(var_list=['recharge', 'runoff', 'precip',
                                             'evt', 'etp', 't',
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

# Units
BV.climatic.evt = BV.climatic.evt / 1000 # from mm to m
BV.climatic.etp = BV.climatic.etp / 1000 # from mm to m
BV.climatic.precip = BV.climatic.precip / 1000 # from mm to m
BV.climatic.t = BV.climatic.t / 1000 # from mm to m
#%% SAFRAN
BV.add_safransurfex(r"C:\\Users\\theat\\Documents\\Python\\02_Output_HydroModPy\\data\\Meteo\\REA")
#%%RECHARGE REANALYSIS
BV.climatic.update_recharge_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_REC_D.csv'),
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=first_year,
                                       last_year=last_year,
                                       time_step=freq_input,
                                       sim_state=sim_state)

#BV.climatic.recharge = BV.climatic.recharge * BV.climatic.recharge.index.day
BV.climatic.update_recharge(BV.climatic.recharge / 1000, sim_state = sim_state) # from mm to m
# BV.climatic.update_recharge(BV.climatic.recharge.resample('M').sum(), sim_state = sim_state) # days to month
#%% RUNOFF REANALYSIS
BV.climatic.update_runoff_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_RUN_D.csv'),
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=first_year,
                                       last_year=last_year,
                                       time_step=freq_input,
                                       sim_state=sim_state)

#BV.climatic.runoff = BV.climatic.runoff* BV.climatic.runoff.index.day
BV.climatic.update_runoff(BV.climatic.runoff / 1000, sim_state = sim_state) # from mm to m
# BV.climatic.update_runoff(BV.climatic.runoff.resample('M').sum(), sim_state = sim_state)

#%% Format for plots
if isinstance(BV.climatic.recharge, float):
    print(f"Time-space daily average value for recharge = {BV.climatic.recharge} m")
    print(f"Time-space daily average value for runoff = {BV.climatic.runoff} m")
else:
    if isinstance(BV.climatic.recharge, xr.core.dataset.Dataset):
        R = BV.climatic.recharge.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        r = BV.climatic.runoff.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        # R = R.resample('M').sum()
        # r = r.resample('M').sum()
    elif isinstance(BV.climatic.recharge, pd.core.series.Series):  
        R = BV.climatic.recharge
        r = BV.climatic.runoff        

# Plots
fig, ax = plt.subplots(1,1, figsize=(6,3))
ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=2)
ax.plot(r, label='runoff_reanalysis', c='navy', lw=2)
ax.set_xlabel('Date')
ax.set_ylabel('[m/M]')
plt.xticks(rotation=45, ha="right")
ax.legend()

#%% ---- PARAMETRIZATION
#%% DEFINE

# Frame settings
box = True # or False
sink_fill = False # or True

# sim_state = 'transient' # 'steady' or 'transient'
sim_state = sim_state # 'steady' or 'transient'
plot_cross = False
dis_perlen = True

# Climatic settings
first_clim = 'first' # or 'first or value
freq_time = freq_input

# Hydraulic settings
nlay = 1
lay_decay = 10 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 30 # if bottom is None, aquifer thickness
hk = 1.6e-5* 3600 * 24 # m/day 
cond_drain = None # or value of conductance

########## LOOP ##########
list_porosity = np.array([0.2]) / 100 # [-] 

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
split_temp = True

# # Particle tracking settings
# zone_partic = 'domain' # or watershed
plt.plot(hk/R)


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
BV.hydraulic.update_cond_drain(cond_drain)

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

for i, sy in enumerate(list_porosity[:]):
    BV.hydraulic.update_sy(sy)
    
    model_name = iD_set_simulations+'_'+str(i)+'_'+str(round(sy,3))
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

iD_set_simulations = 'explorSy_test1'

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
        #print (cur_x, cur_y)
        # cur_x = 95
        # cur_y = 95
        
        
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
        ax.plot(np.arange(dem_h_plot.size) * 75, wt_h_plot, color=color, lw=1, label=f'{label} {str(dates[key])[:7]}')
    
    ax.fill_between(np.arange(dem_h_plot.size) * 75, 0, dem_h_plot - 30,
                    color='lightgrey', alpha=0.5, lw=0)
    ax.plot(np.arange(dem_h_plot.size) * 75, dem_h_plot - 30, color='dimgray', lw=1.5)
    ax.plot(np.arange(dem_h_plot.size) * 75, dem_h_plot, 'saddlebrown', lw=1.5, label='DEM')
    
ax.set_xlim(4000, 12000)
ax.set_ylim(20, 200)
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

# iD_set_simulations = 'explorSy_mperday_monthly_steady'
# iD_set_simulations = 'explorSy_mperday_monthly_transient'
# iD_set_simulations = 'explorSy_mpermonth_monthly_transient'
# iD_set_simulations = 'explorSy_mpermonth_monthly_steady'
#%% FORMATTING Qobs CSV
Qobs_path = os.path.join(data_path, 'J721401001.csv')
Qobs = pd.read_csv(Qobs_path, sep=',')
# Afficher les premières lignes pour vérifier le format des dates
# print(Qobs.head())

Qobs["Date (TU)"] = Qobs["Date (TU)"].str.split('T').str[0]
Qobs["Date (TU)"] = pd.to_datetime(Qobs["Date (TU)"], format='%Y-%m-%d')
Qobs.set_index("Date (TU)", inplace=True)

Qobs= Qobs.drop(columns=["Statut","Qualification","Méthode","Continuité"])
Qobs = Qobs.squeeze()
Qobs = Qobs.rename('Q')


area = int(round(BV.geographic.area))
Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month


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
    Qmod = (Qmod + (r * 1000)) * Qmod.index.day
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
    ax.plot(Qobs, color='k', lw=1, ls='-', zorder=0, label='observed')
    ax.plot(Qmod, color='red', lw=1, label='modeled')
    # ax.plot(Rmod.index, Rmod*1000, color='blue', lw=2.5)
    ax.set_xlabel('Date')
    ax.set_ylabel('Q / A [mm/month]')
    ax.set_yscale('log')
    ax.set_ylim(0.0001, 200)
    years_5 = mdates.YearLocator(5)  # every 5 years
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)
    ax.set_xlim(pd.to_datetime(f'{first_year}-01'), pd.to_datetime(f'{last_year}-12'))
    ax.legend()
    ax.set_title(model_name.upper(), fontsize=10)
    for label in ax.get_xticklabels():
        label.set_rotation(45)
    
    # axb = ax.twinx()
    # axb.bar(Rmod.index, Rmod,color='blue', edgecolor='blue', lw=2.5)
    # axb.set_ylim(0,999)
    # axb.invert_yaxis()
    # axb.set_yticklabels([0.1,200])
    
    Qobs_stat = select_period(Qobs,first_year,last_year)
    Qmod_stat = select_period(Qmod,first_year,last_year)
    
    import hydroeval as he
    NSE = he.evaluator(he.nse, Qmod_stat, Qobs_stat)[0]
    NSElog = he.evaluator(he.nse, Qmod_stat, Qobs_stat, transform='log')[0]
    RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qmod_stat.values)**2))
    KGE = he.evaluator(he.kge, Qmod_stat, Qobs_stat)[0][0]
    print(model_name.upper())
    print(round(NSE,2))
    print(round(NSElog,2))
    print(round(RMSE,2))
    print(round(KGE,2))
    
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
    ax.scatter(Qobs_stat, Qmod_stat,
               s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.plot((0.01,1000),(0.01,1000), color='grey', zorder=-1)
    ax.set_xlim(0.1,500)
    ax.set_ylim(0.1,500)
    # ax.set_xlim(0.1,300)
    # ax.set_ylim(0.1,300)    
    ax.set_xlabel('$Q_{obs}$ / A [mm/month]', fontsize=12)
    ax.set_ylabel('$Q_{sim}$ / A [mm/month]', fontsize=12)
    fig.tight_layout()
                
    fig.savefig(os.path.join(simulations_folder, '_figures',
                'STREAMFLOW_'+model_name+'.png'),
                bbox_inches='tight')
    
#%% VALUE PER YEAR FOR TURC BUDYKO EQUATION when timepath is daily
Qmod_year = Smod['outflow_drain'] 
Qmod_year = Qmod_year.squeeze() * 1000
Qmod_year = (Qmod_year+ (r * 1000))
Qmod_year = Qmod_year.resample('Y').sum().mean()
print (Qmod_year)

precip_year = BV.climatic.precip.resample('Y').sum().mean() * 1000  # mm
etp_year = BV.climatic.etp.resample('Y').sum().mean() * 1000  # mm
print(precip_year)
print(etp_year)
#%% SATURATION

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

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
    x_months = Smod.index # 
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

    ax.set_ylim(-0,12)
    # ax.set_yticks(np.arange(0,15.05,2.5))
    ax.set_ylabel('Drainge density [%]')
    ax.set_xlim(pd.to_datetime(f'{first_year}-01'), pd.to_datetime(f'{last_year}-12'))
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
