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
import logging
import os
from sys import platform
import geopandas as gpd
from datetime import datetime
from scipy.optimize import minimize

# Libraries need to be installed if not
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
#from IPython import get_ipython
#get_ipython().run_line_magic('matplotlib', 'inline')

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
first_year = 2021
last_year = 2021
freq_input = 'M'
sim_state = 'transient' 
parameters = "testdailyimpact"
out_path = folder_root.root_folder_results()
#out_path = r"C:\Users\theat\Documents\Python\Output_HydroModPy" # Manually set the output path
data_path = os.path.join(out_path, "data")
specific_data_path = os.path.join(data_path, study_site)

print(f"out_path; {out_path}, Data path: {data_path}, specific_data_folder; {specific_data_path}")
#%% ---- WATERSHED
#%% OPTIONS
# Name of the study site
watershed_name = '_'.join([
    'calib',study_site,parameters,str(first_year),str(last_year),freq_input,sim_state
])

print('##### '+watershed_name.upper()+' #####')

watershed_path = os.path.join(out_path, watershed_name)
dem_path = os.path.join(data_path, 'dem', 'regional dem.tif')

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
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

#%% DATA

# visualization_watershed.watershed_local(dem_path, BV)

# Clip specific data at the catchment scale
# BV.add_geology(os.path.join(data_path, 'geology'), types_obs='GEO1M.shp', fields_obs='CODE_LEG')
BV.add_hydrography(os.path.join(data_path, 'hydrography'), types_obs=['regional stream network'])
BV.add_hydrometry(os.path.join(data_path, 'hydrometry'), 'france hydrometric stations.shp')
# BV.add_intermittency(os.path.join(data_path, 'intermittency'), 'regional onde stations.shp')
# BV.add_piezometry()

#Extract some subbasin from data available above
# BV.add_subbasin(os.path.join(data_path, 'additional'), 150)

#%% RECHARGE et RUISSELLEMENT DE SURFACE DIRECT (données d'entrée)
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
                                                                
#%% Units
BV.climatic.evt = BV.climatic.evt / 1000 # from mm to m
BV.climatic.etp = BV.climatic.etp / 1000 # from mm to m
BV.climatic.precip = BV.climatic.precip / 1000 # from mm to m
BV.climatic.t = BV.climatic.t / 1000 # from mm to m
BV.climatic.runoff= BV.climatic.runoff / 1000 # from mm to m
BV.climatic.recharge = BV.climatic.precip - BV.climatic.evt - BV.climatic.runoff
# BV.climatic.recharge = BV.climatic.recharge/1000
# BV.climatic.recharge = (BV.climatic.precip - BV.climatic.etp - BV.climatic.runoff).where(
#     (BV.climatic.precip - BV.climatic.etp - BV.climatic.runoff) > 0,
#     0
# )

#%% UPDATE RECHARGE RUNOFF
# BV.add_safransurfex(r"C:\Users\theat\Documents\Python\02_Output_HydroModPy\data\Meteo\REA")

# # #%%RECHARGE REANALYSIS
# BV.climatic.update_recharge_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_REC_D.csv'),
#                                        clim_mod='REA',
#                                        clim_sce='historic',
#                                        first_year=first_year,
#                                        last_year=last_year,
#                                        time_step=freq_input,
#                                        sim_state=sim_state)

# BV.climatic.update_recharge(BV.climatic.recharge/1000, sim_state = sim_state) # from mm to m


# BV.climatic.update_runoff_reanalysis(path_file=os.path.join(out_path, watershed_name, 'results_stable', 'climatic', '_RUN_D.csv'),
#                                        clim_mod='REA',
#                                        clim_sce='historic',
#                                        first_year=first_year,
#                                        last_year=last_year,
#                                        time_step=freq_input,
#                                        sim_state=sim_state)

# BV.climatic.update_runoff(BV.climatic.runoff/1000, sim_state=sim_state) # from mm to m

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

# Qobs = Qobs.drop(columns=["time"])
# Qobs = Qobs.rename(columns={'Q_Lperday': 'Q'})
# Qobs['Q'] = Qobs['Q'] / 1000  # L/d to m3/d
# area = int(round(BV.geographic.area))
# Qobs = (Qobs / (area*1000000)) # m3/d to m/day
# Qobsyear = Qobs.resample('Y').sum().mean().values[0] # m/day to m/y

##option 2
# Qobs_path = os.path.join(specific_data_path,'hydrometry','J560681001.csv')
# Qobs = pd.read_csv(Qobs_path, delimiter=',')
# #print (Qobs.columns)
# #print(Qobs.head())
# Qobs["Date (TU)"] = Qobs["Date (TU)"].str.split('T').str[0]
# Qobs["Date (TU)"] = pd.to_datetime(Qobs["Date (TU)"], format='%Y-%m-%d')
# Qobs.set_index("Date (TU)", inplace=True)

# Qobs = Qobs.drop(columns=["Statut", "Qualification", "Méthode", "Continuité"])
# Qobs = Qobs.squeeze()
# Qobs = Qobs.rename('Q')

# area = int(round(BV.geographic.area))
# Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
# Qobsyear = Qobs.resample('Y').sum().mean() # m/day to m/y

##option 3 
Qobs_path = os.path.join(specific_data_path,'hydrometry','J721401001.csv')
Qobs = pd.read_csv(Qobs_path, delimiter=',')
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

if freq_input == 'w':
    Rec = R*7
    run = r * 7
elif freq_input == 'M':
    Rec = R * R.index.day
    run = r * R.index.day
else :
    Rec = R
    run = r

Rannual = Rec.resample('Y').sum().mean()
rannual = run.resample('Y').sum().mean()
Qsafran = Rannual+rannual

F = Qobsyear / Qsafran

print (f'F = {F}')
R = R * F
r = r * F

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

#%% Plots R et r
Qnormalized = Rec+run
fig, ax = plt.subplots(1,1, figsize=(6,3))
ax.plot(Qnormalized*1000, label='Qnormalized', c='orange', lw=0.5)
ax.plot(Rec*1000, label='recharge_reanalysis_normalized', c='dodgerblue', lw=0.5)
# ax.plot(r, label='runoff_reanalysis_normalized', c='navy', lw=0.5)
ax.plot(Qobsmm, label='Qobs', c='darkgreen', lw=0.5)
# ax.plot(BV.climatic.precip*1000, label='precip', c='blue', lw=0.5, linestyle = '--')
# ax.plot(BV.climatic.recharge, label='recharge_reanalysis', c='deepskyblue', lw=0.5,  linestyle = '--')
# ax.plot(BV.climatic.runoff, label='runoff_reanalysis', c='black', lw=0.5,  linestyle = '--')
ax.set_xlabel('Date')
ax.set_ylabel(f'[mm/{freq_input}]')
ax.set_yscale('log')
plt.xticks(rotation=45, ha="right")
ax.legend()
plt.savefig(os.path.join(out_path, watershed_name, 'results_stable', '_figures', 'R_r.png'), dpi=300)

#%% DEFINE FIRST RUN 

# Frame settings
r_steady=r.mean()
R_steady=R.mean()
print(f"R mean: {R_steady}, r mean: {r_steady}")
print(f"R: {R}, r: {r}")


box = True # or False
sink_fill = False # or True

sim_state_steady = 'steady' # 'steady' or 'transient'
plot_cross = False
dis_perlen = True

# Climatic settings
first_clim = 'mean' # or 'first or value
freq_time = freq_input

# Hydraulic settings
nlay = 10
lay_decay = 1.25

bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 30 # if bottom is None, aquifer thickness
alpha = (1/21)
hk = 1.0e-4* 3600 * 24 # m/day = Kmax qui va être optimisé dans la suite
hk_decay = (alpha, None, True,[]) # soit une décroissance de 10m
cond_drain = None # or value of conductance
exdp = 0

sy = 1/100 # [-]
sy_decay = ((alpha/2), None, True, [])
ss = 1e-5
ss_decay = ((alpha/2), None, True, [])

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
split_temp = True

# # Particle tracking settings
# zone_partic = 'domain' # or watershed

# plt.plot(hk/R)
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
BV.settings.update_simulation_state(sim_state_steady)
BV.settings.update_check_model(plot_cross=plot_cross)

# Climatic settings
recharge = R.copy()
BV.climatic.update_recharge(recharge, sim_state=sim_state_steady)
BV.climatic.update_first_clim(first_clim)

runoff = r.copy()
BV.climatic.update_runoff(runoff, sim_state=sim_state_steady)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) 
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_hk(hk)
BV.hydraulic.update_hk_decay(hk_decay_value=hk_decay[0], 
                             min_value=hk_decay[1], 
                             log_transf=hk_decay[2], 
                             grad_elev=hk_decay[3])
BV.hydraulic.update_sy(sy) 
BV.hydraulic.update_sy_decay(sy_decay_value=sy_decay[0], 
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
# BV.settings.update_input_particles(zone_partic=BV.geographic.watershed_box_buff_dem) # or 'seepage_path' - DÉSACTIVÉ
#%% CLASS MatchingStreams

class MatchingStreams:
    """ 
    
    Class for the calibration based on river occurency
        
    Attributes
    ----------
    
    Methods
    ----------
    
    """

    def __init__(self, 
                 watershed, 
                 iteration_label=None,
                 from_calib=True):
        
        self.geographic = watershed.geographic
        self.hydrography = watershed.hydrography
        if from_calib==True:
            self.calibration_folder = watershed.calibration_folder
        else:
            self.calibration_folder = watershed.simulations_folder
        self.iteration_label = iteration_label
        
        self.watershed_shp = watershed.geographic.watershed_shp
        self.watershed_fill = watershed.geographic.watershed_fill
        self.watershed_direc = watershed.geographic.watershed_direc
        
        try:
            self.prepare_files()
        except:
            print("pas de création de fichier")
            
        self.sim_to_obs()
        self.obs_to_sim()
        # self.get_indicator()
        
    def prepare_files(self):
        #files are necessary for whiteboxtool
        self.results_folder=os.path.join(self.calibration_folder, self.iteration_label, '_postprocess')
        toolbox.create_folder(self.results_folder)
        # New folder results
        self.dichotomy_folder = os.path.join(self.calibration_folder, self.iteration_label, '_matchingstreams')
        toolbox.create_folder(self.dichotomy_folder)
        # Observed buff data
        self.buff_tif_obs = self.hydrography.tif_streams
        # Mask observed
        self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)
        # Obs to points
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
        self.pt_obsf = os.path.join(self.dichotomy_folder, 'obs_ptf.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
        # Trace downslope obs
        self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
        
        # Mask simulated
        tif_sim = os.path.join(self.results_folder,'_rasters','seepage_areas_t(0).tif')
        self.tif_sim = os.path.join(self.dichotomy_folder,'sim.tif')
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, False)
        # Sim to points
        self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)
        self.pt_simf = os.path.join(self.dichotomy_folder, 'sim_ptf.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_simf)
        # Trace downslope sim
        self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)
        
    def sim_to_obs(self):
        # Simflow to points
        self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        self.pt_sim_flowf = os.path.join(self.dichotomy_folder, 'simflowf.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)   
        
        # Distance of dem to obs
        self.dist_dem_obs = os.path.join(self.dichotomy_folder, 'dist_dem_obs.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)
        
        # Distance of dem to obsflow
        self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, 'dist_dem_obsflow.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_dem_obsflow)

        # Sim to Obs and Obsflow
        wbt.add_point_coordinates_to_table(self.pt_sim)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
        wbt.add_point_coordinates_to_table(self.pt_simf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)
        # Simflow to Obs and Obsflow
        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
        wbt.add_point_coordinates_to_table(self.pt_sim_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)

    def obs_to_sim(self):
        # Simflow to points
        self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        self.pt_obs_flowf = os.path.join(self.dichotomy_folder, 'obsflowf.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flowf)
        
        # Distance of dem to sim
        self.dist_dem_sim = os.path.join(self.dichotomy_folder, 'dist_dem_sim.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_sim, self.dist_dem_sim)
        # Distance of dem to simflow
        self.dist_dem_simflow = os.path.join(self.dichotomy_folder, 'dist_dem_simflow.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_dem_simflow)

        # Obs to Sim and Simflow
        wbt.add_point_coordinates_to_table(self.pt_obs)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs)
        wbt.add_point_coordinates_to_table(self.pt_obsf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obsf)
        # Obsflow to Sim and Simflow
        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs_flow)
        wbt.add_point_coordinates_to_table(self.pt_obs_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obs_flowf)

#%%CALIBRATION hk and hkdecay
run_optimization = True

if run_optimization:
    optim_folder = os.path.join(calibration_folder, 'optimization_results')
    os.makedirs(optim_folder, exist_ok=True)

    all_simulations_results = []
    all_Qmod_Qobs_results = []
    use_time_filter = True
    
    calib_start_date = f"{first_year}-01-01"
    calib_end_date = f"{last_year}-12-31"
    
    use_seasonal_filter = False
    season_start_month = 7
    season_start_day = 1
    season_end_month = 12
    season_end_day = 31
    
    def filter_dates(dates):
        """Filter dates based on time and seasonal criteria"""
        if not isinstance(dates, pd.DatetimeIndex):
            dates = pd.DatetimeIndex(dates)
        mask = pd.Series(True, index=dates)

        if use_time_filter:
            mask = mask & (dates >= calib_start_date) & (dates <= calib_end_date)

            if use_seasonal_filter:
                def is_in_season(date):
                    start = pd.Timestamp(date.year, season_start_month, season_start_day)
                    # Adjust end date if season ends in the next year
                    if season_end_month < season_start_month:
                        end = pd.Timestamp(date.year + 1, season_end_month, season_end_day)
                    else:
                        end = pd.Timestamp(date.year, season_end_month, season_end_day)
                    
                    return (date >= start) & (date <= end)
                
                seasonal_mask = dates.map(is_in_season)
                mask = mask & seasonal_mask

        return mask

    def normalize(x, xmin, xmax):
        return (x - xmin) / (xmax - xmin)

    def denormalize(x_norm, xmin, xmax):
        return x_norm * (xmax - xmin) + xmin

    optimization_results = {"model_name": None, "model_modflow": None, "best_error": np.inf}

    # # Define bounds and normalization factors
    # # thick_min, thick_max = 20, 30 # m
    # log_hk_min, log_hk_max = np.log10(1e-8*24*3600), np.log10(1e-2*24*3600)  # Log scale
    # hk_decay_min, hk_decay_max = 0.003, 0.1  # m
    # sy_min, sy_max = 0.1/100, 10/100
    compt = 0

    # Error function using normalized parameters
    def erreur_modele_norm(params_norm):
        global compt
    
        # Convert normalized parameters back to real values
        # thick = denormalize(params_norm[2], thick_min, thick_max)
        log_hk_value = denormalize(params_norm[0], log_hk_min, log_hk_max)
        hk_value = 10**log_hk_value 
        #hk_decay_value = denormalize(params_norm[1], hk_decay_min, hk_decay_max)# Convert log(K) to hk
        # sy_value = denormalize(params_norm[2], sy_min, sy_max)
        
        print(f'hk = {hk_value/24/3600}')
        BV.hydraulic.update_hk(hk_value)
        # BV.hydraulic.update_sy(sy_value)
        #BV.hydraulic.update_hk_decay(hk_decay_value)

        # Model name
        timestamp = datetime.now().strftime("%H%M%S") #permet d'afficher l'heure à laquelle le script à tourner
        model_name = f"optim_{compt}_{timestamp}_hk{hk_value/24/3600:.2e}ms"#_hk_decay{hk_decay_value:.3f}"
        logging.info(f"\nSimulation {compt}: hk={hk_value/24/3600:.2e}m/s")#, hk_decay={hk_decay_value:.3f}m")
        BV.settings.update_model_name(model_name)
        BV.settings.update_check_model(plot_cross=False, check_grid=True)

        model_modflow = BV.preprocessing_modflow(for_calib=True)
        success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

        if not success_modflow:
            print("Échec de la simulation!")
            compt += 1  # Still increment counter on failure
            return 1e6

        # Post-processing
        BV.postprocessing_modflow(model_modflow,
                                    watertable_elevation=True,
                                    seepage_areas=True,
                                    outflow_drain=True,
                                    accumulation_flux=True,
                                    watertable_depth=True,
                                    groundwater_flux=False,
                                    groundwater_storage=False,
                                    intermittency_yearly=True,
                                    export_all_tif=False)

        # Matching streams
        iter_results = MatchingStreams(BV, iteration_label=model_name, from_calib=True)
        obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams', 'obsflowf.shp'))
        simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams', 'simflowf.shp'))
    
        mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1'] >= 0]['VALUE1'])
        mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1'] >= 0]['VALUE1'])
    
        obs_distance = mean_obsf_to_simf
        sim_distance = mean_simf_to_obsf

        matching = (abs(sim_distance) + abs(obs_distance)) / 2
        
        print('INDICATORMATCHINGSRTEAM : ', matching)
        errormatchingstream = matching
        optimization_results["model_name"] = model_name
        optimization_results["model_modflow"] = model_modflow
    
        if np.isnan(errormatchingstream) or obs_distance == 0:
            return np.inf  # Large error if indicator is invalid
        
        error = errormatchingstream # Average error between NSElog and matching streams
        # Save the results    
        current_simulation = {
        "obs_distance": obs_distance,
        "sim_distance": sim_distance,
        "iteration": compt,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model_name": model_name,
        "hk": hk_value,
        "hk_ms": hk_value/24/3600,
        "log_hk": log_hk_value,  # Ajout du log(hk) dans les résultats
        #"hk_decay_value": hk_decay_value,
        # "sy": sy_value,
        "thick": thick,
        # "NSElog": NSElog,
        "matchingstream": matching,
        'errormatchingstream': errormatchingstream,
        # "nse": nse,
        # "r_squared": r_squared,
        # "rmse": rmse,
        # "error_nselog": errorNSElog,
        "error": error,
        # "filtered_points": len(filtered_dates),
        # "total_points": len(sim_dates),
        }
        
        # Qmod_Qobs ={
        #     'Qmod': Qmod,
        #     'Qobs': Qobsmonthmm,
        # }
        
        # all_Qmod_Qobs_results.append(Qmod_Qobs)
        #pd.DataFrame (all_Qmod_Qobs_results).to_csv(os.path.join(optim_folder,'all_Qmod_Qosb_results.csv'))
        
        # Append the results to the list
        all_simulations_results.append(current_simulation)

        pd.DataFrame(all_simulations_results).to_csv(
            os.path.join(optim_folder, 'all_simulations_results_stream.csv'), 
            index=False
        )

        # Save if the error is the best so far
        if error < optimization_results["best_error"]:
            optimization_results["model_name"] = model_name
            optimization_results["model_modflow"] = model_modflow
            optimization_results["best_error"] = error
            # optimization_results["best_NSElog"] = NSElog
            optimization_results["best_params"] = {
                "hk": hk_value,
                "log_hk": log_hk_value,  # Ajout du log(hk) dans les meilleurs paramètres
                #"hk_decay_vlaue": hk_decay_value,
                # "sy": sy_value,
                # "thick": thick
            }
            # optimization_results["filtered_dates"] = filtered_dates
            logging.info("► Meilleure simulation jusqu'à présent ◄")

        compt += 1
        return error

    # Run the optimization
    print("\n=== DÉMARRAGE DE L'OPTIMISATION SIMPLEX ===")
    start_time = datetime.now()
    print(f"Démarrage: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    if use_time_filter:
        filter_info = f"Période de calibration: {calib_start_date} à {calib_end_date}"
        if use_seasonal_filter:
            filter_info += f", saison: {season_start_day}/{season_start_month} à {season_end_day}/{season_end_month}"
        print(filter_info)

    # Define the bounds for the parameters using log scale for hk
    hk_min_mday, hk_max_mday = 1e-8 * 24 * 3600, 1e-2 * 24 * 3600  # m/day
    log_hk_min = np.log10(hk_min_mday)  # log10 de la valeur en m/jour
    log_hk_max = np.log10(hk_max_mday)  # log10 de la valeur en m/jour
    
    #hk_decay_min, hk_decay_max = 0.003, 0.1  # Conductivité hydraulique decay bounds in m

        
    # Initial values
    hk_init = hk
    #hk_decay_init = hk_decay
    
    # Convertir hk_init en log(hk_init) pour la normalisation
    log_hk_init = np.log10(hk_init)

    # Normalize the initial values with hk in log scale
    x0_norm = [
        normalize(log_hk_init, log_hk_min, log_hk_max),
        #normalize(hk_decay, hk_decay_min, hk_decay_max),
    ]

    # Log des bornes et valeurs initiales pour vérification
    print(f"Valeur initiale hk: {hk_init:.2e} m/jour ({hk_init/24/3600:.2e} m/s), log(hk): {log_hk_init:.4f}")
    print(f"Bornes hk: [{hk_min_mday:.2e}, {hk_max_mday:.2e}] m/jour, log(hk): [{log_hk_min:.4f}, {log_hk_max:.4f}]")

    # Run the optimization using the Nelder-Mead method (Simplex)
    result = minimize(
        erreur_modele_norm, 
        x0_norm, 
        method='Nelder-Mead',
        options={
            'xatol': 0.05,
            'fatol': 0.05,
            'maxiter': 30,
            'disp': True
        }
    )

    # Conversion des résultats optimaux du log(hk) vers hk
    best_log_hk = denormalize(result.x[0], log_hk_min, log_hk_max)
    best_hk = 10**best_log_hk
    # best_hk_decay = denormalize(result.x[1], hk_decay_min, hk_decay_max)

    end_time = datetime.now()
    duration = end_time - start_time

    print("\n=== RÉSULTATS DE L'OPTIMISATION ===")
    print(f"Conductivité hydraulique optimale: {best_hk/24/3600:.2e} m/s ({best_hk:.2e} m/jour)")
    print(f"Log(K) optimal: {best_log_hk:.4f}")
    # print(f"Porosité efficace optimale: {best_sy:.4f}")
    # print(f"Décroissance de la conductivité hydraulique optimale: {best_hk_decay:.3f} m")
    # print(f"Épaisseur optimale: {best_thick:.2f} m")
    # print(f"NSElog: {optimization_results.get('best_NSElog', 'N/A')}")
    print(f"distance optimale : {optimization_results.get('matchingstream', 'N/A')} m")
    # logging.info(f"NSE: {optimization_results.get('best_nse', 'N/A')}")
    # logging.info(f"R²: {optimization_results.get('best_r_squared', 'N/A')}")
    # logging.info(f"RMSE: {optimization_results.get('best_rmse', 'N/A')} m³")
    print(f"Meilleur modèle: {optimization_results['model_name']}")
    print(f"Nombre de simulations: {compt}")
    print(f"Durée totale: {duration}")

    # Use the best parameters for the final run
    BV.hydraulic.update_hk(best_hk)
    # BV.hydraulic.update_hk_decay(best_hk_decay)

    # Update the model name with the best parameters
    model_name = f"final_optimized_hk{best_hk/24/3600:.2e}"#_hk_decay{best_hk_decay:.1f}"
    BV.settings.update_model_name(model_name)

    # Save the optimization results
    optim_results = {
        "best_hk": best_hk,
        "best_hk_ms": best_hk/24/3600,
        "best_log_hk": best_log_hk,  # Ajout du log(hk) dans les résultats
        # "best_hk_decay": best_hk_decay,
        # "best_sy": best_sy,
        # "best_thickness": best_thick,
        # "best NSElog": optimization_results.get('best_NSElog'),
        # "best_nse": optimization_results.get('best_nse'),
        # "best_r_squared": optimization_results.get('best_r_squared'),
        # "best_rmse": optimization_results.get('best_rmse'),
        "iterations": compt,
        "duration_seconds": duration.total_seconds(),
        "optimization_start": start_time.strftime('%Y-%m-%d %H:%M:%S'),
        "optimization_end": end_time.strftime('%Y-%m-%d %H:%M:%S'),
        "best_model": optimization_results['model_name'],
        "time_filter": {
            "enabled": use_time_filter,
            "global_start": calib_start_date,
            "global_end": calib_end_date,
            "seasonal_filter": use_seasonal_filter,
            "season_start": f"{season_start_day}/{season_start_month}",
            "season_end": f"{season_end_day}/{season_end_month}"
        }
    }

    # Create optimization results folder if it doesn't exist
    optim_df = pd.DataFrame([optim_results])
    optim_df.to_csv(os.path.join(optim_folder, f'optimization_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'), index=False)

    print(f"Résultats d'optimisation sauvegardés dans {optim_folder}")
else: 
    print("Optimisation désactivée, utilisation des paramètres définis manuellement.")

#%% PRINT EACH VALUE OF ERRORMATCHINGSTREAM
stable_folder = os.path.join(out_path, watershed_name, 'results_stable')
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
optim_folder = os.path.join(calibration_folder, 'optimization_results')
# Paths generated automatically but necessary for plots

fig2, (b1) = plt.subplots(gridspec_kw={'width_ratios': [1]},  
                              figsize=(10, 5))

result_each_calib = pd.read_csv(os.path.join(optim_folder, 'all_simulations_results_stream.csv'))
step = result_each_calib['iteration']
result_each_calib.set_index('iteration', inplace=True)
matchingstream = result_each_calib['matchingstream']

error_matchingstream = result_each_calib['errormatchingstream']

# Plot errormatchingstream and error_nselog
bx = b1
bx.plot(step, error_matchingstream, label='error_matchingstream', color='orange')
bx.set_xlabel('Step')
bx.set_ylabel('Values of error_nselog', size = 8)
bx.set_yscale('log')
bx.legend()
bx.grid()

# Adjust layout and save the figure
fig2.tight_layout()
fig2.savefig(os.path.join(calibration_folder,'_figures','error_metrics_matchingstream.png'), dpi=300)
plt.show()

#%% PRINT PARAMETERS VARIATIONS
datahkmin = 1e-8
datahkmax = 1e-2
datasymin = 0.001
datasymax = 0.1
datahkdecaymin = 0.003
datahkdecaymax = 0.1

fig, (ax0) = plt.subplots(1,1,figsize=(10, 6))

ax = ax0
ax.plot(result_each_calib.index, result_each_calib['hk_ms'], linestyle='--', label='hk_ms', color='blue')
# ax.plot(datta.index, datahkmin, linestyle='--', label='hk_min', color='grey')
# ax.plot(data.index, datahkmax, linestyle='--', label='hk_max', color='grey')
ax.set_ylabel('hk_ms (m/s)')
ax.legend(loc='upper right')
ax.set_ylim(datahkmin, datahkmax)
ax.set_title('Hydraulic conductivity (hk_ms) optimization')
ax.set_xlabel('Simulation index')
ax.set_yscale('log')
plt.tight_layout()
plt.savefig(os.path.join(calibration_folder,'_figures','hk_ms_variation.png'), dpi=300)
# ax = ax1
# ax.plot(result_each_calib.index, result_each_calib['sy'], linestyle='--', label='sy', color='green')
# # ax.plot(data.index, datasymin, linestyle='--', label='sy_min', color='grey')
# # ax.plot(data.index, datasymax, linestyle='--', label='sy_max', color='grey')
# ax.set_ylabel('sy')
# ax.legend(loc='upper right')
# ax.set_ylim(datasymin, datasymax)
# ax.set_title('Specific yield (sy) optimization')
# ax.set_xlabel('Simulation index')
# plt.tight_layout()

#%% run best model 
BV.settings.update_model_name(model_name)
BV.settings.update_check_model(plot_cross=False, check_grid=True)

model_modflow = BV.preprocessing_modflow(for_calib=True)
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

if not success_modflow:
    print("Échec de la simulation!")

# Post-processing
BV.postprocessing_modflow(model_modflow,
                            watertable_elevation=True,
                            seepage_areas=True,
                            outflow_drain=True,
                            accumulation_flux=True,
                            watertable_depth=True,
                            groundwater_flux=False,
                            groundwater_storage=False,
                            intermittency_yearly=True,
                            export_all_tif=False)

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                    model_modpath=None,
                                                    datetime_format=True, 
                                                    subbasin_results=True,
                                                    intermittency_monthly=True) # or None
        
# netcdf_results = BV.postprocessing_netcdf(model_modflow,
#                                             datetime_format=True)

#%% PLOTS MATCHING STREAMS
fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
dem_data = np.ma.masked_where(dem_data < 0, dem_data)

contour = imageio.imread(BV.geographic.watershed_contour_tif)
contour = np.ma.masked_where(contour < 0, contour)

obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
                                                'regional stream network.tif'))
obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)

seep_river_data = imageio.imread(os.path.join(calibration_folder, model_name,
                                                r'_postprocess/_rasters/seepage_areas_t(0).tif'))
seep_river_data = np.ma.masked_where(seep_river_data <= 0, seep_river_data)

sim_river_data = imageio.imread(os.path.join(calibration_folder, model_name,
                                                r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
sim_river_data = np.ma.masked_where(sim_river_data <= 0, sim_river_data)

im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7)
im_seep = ax.imshow(seep_river_data, cmap=mpl.colors.ListedColormap('darkorange'), alpha=0.7)

ax.set_xlabel('X [pixels]')
ax.set_ylabel('Y [pixels]')
# ax.set_title('K = '+'{:.2e}'.format(model_name.hk.mean()/24/3600)+' m/s')

fig.tight_layout()

fig.savefig(os.path.join(calibration_folder, '_figures',
            'MAP_'+model_name+'_'+str(compt)+'.png'),
            bbox_inches='tight')

# fig.savefig(os.path.join(model_modflow.save_fig,
#             'MAP_'+model_name+'_'+str(compt)+'.png'),
#             bbox_inches='tight')

#%% FIXED CROSS-SECTION

fig, ax = plt.subplots(1, 1, figsize=(6,4), dpi=300)
print(stable_folder)

mask = imageio.imread(stable_folder+'/geographic/'+'watershed_dem.tif')
watertable_elevation = np.load(calibration_folder+'/'+model_name+'/_postprocess/'+'watertable_elevation'+'.npy', allow_pickle=True).item()

dem_data = imageio.imread(BV.geographic.watershed_dem)
wt_data = watertable_elevation[0]

xvalues = np.linspace(-1,1,dem_data.shape[1])
yvalues = np.linspace(-1,1,dem_data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues)

cur_x = dem_data.shape[1] /2
cur_x = 65

wt_prof = wt_data.astype(float)
wt_prof[wt_prof<0] = np.nan
dem_max = dem_data.max()
dem_prof = dem_data.astype(float)
dem_prof[dem_prof<0] = np.nan
dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
dem_v_plot = dem_prof[:,int(cur_x)]
dem_v_plot[dem_v_plot == 0] = np.nan
wt_v_plot = wt_prof[:,int(cur_x)]
wt_v_plot[wt_v_plot == 0] = np.nan
wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*25, dem_v_plot-50, wt_v_plot, color='dodgerblue', alpha=0.5, lw=0)
w_prof = ax.plot(np.arange(xx.shape[0])*25, wt_v_plot, color='navy', lw=1.5)
wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*25, wt_v_plot, dem_v_plot, color='saddlebrown', alpha=0.5, lw=0)
d_prof = ax.plot(np.arange(xx.shape[0])*25, dem_v_plot, 'saddlebrown', lw=1.5)
ax.fill_between(np.arange(xx.shape[0])*25, 0, dem_v_plot-20, color='lightgrey', alpha=0.5, lw=0)
ax.plot(np.arange(xx.shape[0])*25, dem_v_plot-50, color='dimgray', lw=1.5)

ax.set_xlim(600, 3000)
ax.set_ylim(40, 140)
#ax.set_yticks([90,100,110,120,130])
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Elevation [m]')
plt.tight_layout()

# fig.savefig(out_path+'/'+watershed_name+'/results_simulations/'+model_name+'/_postprocess/_figures/'+'2D_cross.png', dpi=300, bbox_inches='tight')

#%% PROFIL DE CONDUCTIVITÉ HYDRAULIQUE EN FONCTION DE LA PROFONDEUR
# Extract hk values from the model
hk_3d = model_modflow.hk  # Shape: (nlay, nrow, ncol)
zbot_3d = model_modflow.zbot  # Shape: (nlay, nrow, ncol)
dem = model_modflow.dem  # Shape: (nrow, ncol)

# Define the cross-section position (same as the previous plot)
cur_x = 65  # Column index for the cross-section

# Extract the vertical profile at this position
# We'll take the middle row for simplicity
cur_y = dem.shape[0] // 2  # Middle row

# Get hk values along the vertical at this position
hk_vertical = hk_3d[:, cur_y, cur_x]  # hk for all layers at this (y,x) position
zbot_vertical = zbot_3d[:, cur_y, cur_x]  # bottom elevation of each layer

# Calculate layer centers for plotting
layer_centers = np.zeros(len(zbot_vertical))
layer_centers[0] = (dem[cur_y, cur_x] + zbot_vertical[0]) / 2  # Top layer
for i in range(1, len(zbot_vertical)):
    layer_centers[i] = (zbot_vertical[i-1] + zbot_vertical[i]) / 2

# Calculate depth from surface
dem_at_point = dem[cur_y, cur_x]
depth_from_surface = dem_at_point - layer_centers

# Create the figure with two subplots side by side
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), dpi=300)

# --- Plot 1: hk as a function of depth ---
ax1.plot(hk_vertical / (24 * 3600), depth_from_surface, 'o-', color='darkblue', linewidth=2, markersize=8)
ax1.set_xlabel('Conductivité hydraulique [m/s]', fontsize=12)
ax1.set_ylabel('Profondeur depuis la surface [m]', fontsize=12)
ax1.set_title(f'Profil vertical de K\nPosition: ligne {cur_y}, colonne {cur_x}', fontsize=13)
ax1.set_xscale('log')
ax1.grid(True, alpha=0.3, which='both')
ax1.invert_yaxis()  # Depth increases downward

# Add text with parameters
alpha_value = alpha if 'alpha' in locals() else hk_decay[0]
textstr = f'hk_surface = {best_hk/(24*3600):.2e} m/s\nalpha (decay) = {alpha_value:.4f} m⁻¹\nnlay = {nlay}'
ax1.text(0.05, 0.95, textstr, transform=ax1.transAxes, fontsize=10,
         verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

# --- Plot 2: hk as a function of elevation ---
ax2.plot(hk_vertical / (24 * 3600), layer_centers, 'o-', color='darkgreen', linewidth=2, markersize=8, 
         label=f'K profile (min: {np.min(hk_vertical / (24 * 3600)):.2e} m/s, max: {np.max(hk_vertical / (24 * 3600)):.2e} m/s)')

ax2.set_xlabel('Conductivité hydraulique [m/s]', fontsize=12)
ax2.set_ylabel('Élévation [m]', fontsize=12)
ax2.set_title(f'Profil vertical de K (élévation)\nPosition: ligne {cur_y}, colonne {cur_x}', fontsize=13)
ax2.set_xscale('log')
ax2.grid(True, alpha=0.3, which='both')

# Add horizontal line for DEM
ax2.axhline(y=dem_at_point, color='brown', linestyle='--', linewidth=1.5, label='Surface (DEM)')

# Add hk range to the legend
hk_min = np.min(hk_vertical / (24 * 3600))
hk_max = np.max(hk_vertical / (24 * 3600))
ax2.legend([f'Surface (DEM)', f'Range de K: {hk_min:.2e} - {hk_max:.2e} m/s'])

plt.tight_layout()
plt.savefig(os.path.join(calibration_folder, '_figures', f'hk_vertical_profile_{model_name}.png'), 
            dpi=300, bbox_inches='tight')
plt.show()

# --- Optional: 2D cross-section showing hk variation as grid ---
fig3, ax3 = plt.subplots(1, 1, figsize=(14, 7), dpi=300)

# Extract a full cross-section (all rows, fixed column)
hk_cross_section = hk_3d[:, :, cur_x] / (24 * 3600)  # Convert to m/s
zbot_cross_section = zbot_3d[:, :, cur_x]
ztop_cross_section = np.zeros_like(zbot_cross_section)
ztop_cross_section[0, :] = dem[:, cur_x]  # Top of first layer is DEM
ztop_cross_section[1:, :] = zbot_cross_section[:-1, :]  # Top of layer i is bottom of layer i-1

# Resolution of the grid
resolution = 75  # meters (as specified)
x_coords = np.arange(dem.shape[0]) * resolution  # Distance in meters

# Plot each cell as a rectangle (pcolormesh style)
from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection

patches = []
colors = []

for layer_idx in range(nlay):
    for row_idx in range(dem.shape[0]):
        # Get cell boundaries
        x_left = row_idx * resolution
        x_right = (row_idx + 1) * resolution
        z_bottom = zbot_cross_section[layer_idx, row_idx]
        z_top = ztop_cross_section[layer_idx, row_idx]
        
        # Skip invalid cells
        if z_bottom < 0 or z_top < 0 or z_top <= z_bottom:
            continue
        
        # Create rectangle for this cell
        width = resolution
        height = z_top - z_bottom
        rect = Rectangle((x_left, z_bottom), width, height, linewidth=0.5, 
                         edgecolor='black', facecolor='none')
        patches.append(rect)
        colors.append(hk_cross_section[layer_idx, row_idx])

# Create patch collection with colors (reversed colormap)
pc = PatchCollection(patches, cmap='jet_r', 
                     norm=mpl.colors.LogNorm(vmin=np.array(colors).min(), 
                                            vmax=np.array(colors).max()),
                     edgecolors='black', linewidths=0.3)
pc.set_array(np.array(colors))
ax3.add_collection(pc)

# Plot the DEM on top
ax3.plot(x_coords, dem[:, cur_x], color='saddlebrown', linewidth=2.5, label='Surface (DEM)', zorder=10)

# Plot the watertable
wt_cross_section = wt_data[:, cur_x]
wt_cross_section_masked = wt_cross_section.astype(float)
wt_cross_section_masked[wt_cross_section_masked < 0] = np.nan
ax3.plot(x_coords, wt_cross_section_masked, color='yellow', linewidth=2.5, label='Nappe phréatique', zorder=10)

# Fill between watertable and bottom to show saturated zone
bottom_elevation = zbot_cross_section[-1, :]
# ax3.fill_between(x_coords, wt_cross_section_masked, bottom_elevation, 
#                  color='dodgerblue', alpha=0.3, label='Zone saturée', zorder=5)

# Plot the bottom boundary
ax3.plot(x_coords, bottom_elevation, color='dimgray', linewidth=2, label='Fond de l\'aquifère', linestyle='--')

# Add colorbar
cbar = plt.colorbar(pc, ax=ax3, pad=0.02)
cbar.set_label('Conductivité hydraulique [m/s]', fontsize=12)

# Set axis limits
ax3.set_xlim(x_coords.min(), x_coords.max())
z_min = np.nanmin(zbot_cross_section[zbot_cross_section > 0])
z_max = np.nanmax(dem[:, cur_x])
ax3.set_ylim(z_min - 5, z_max + 5)

ax3.set_xlabel('Distance [m]', fontsize=12)
ax3.set_ylabel('Élévation [m]', fontsize=12)
ax3.set_title(f'Coupe transversale 2D - Grille de conductivité hydraulique (colonne {cur_x})\nRésolution: {resolution}m × {nlay} couches', fontsize=13)
ax3.grid(True, alpha=0.3, linestyle=':', linewidth=0.5)
ax3.legend(fontsize=10)

# Add text with model info
textstr = f'Résolution horizontale: {resolution} m\nNombre de couches: {nlay}\nhk_surface: {hk/(24*3600):.2e} m/s\nDécroissance: α = {alpha_value:.4f} m⁻¹'
ax3.text(0.02, 0.98, textstr, transform=ax3.transAxes, fontsize=9,
         verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.7))

plt.tight_layout()
plt.savefig(os.path.join(calibration_folder, '_figures', f'hk_cross_section_2D_grid_{model_name}.png'), 
            dpi=300, bbox_inches='tight')
plt.show()

print(f"\n=== PROFIL DE CONDUCTIVITÉ HYDRAULIQUE ===")
print(f"Position de la coupe: ligne {cur_y}, colonne {cur_x}")
print(f"Élévation du DEM à cette position: {dem_at_point:.2f} m")
print(f"\nValeurs de hk par couche (m/s):")
for i, (hk_val, depth, elev) in enumerate(zip(hk_vertical / (24*3600), depth_from_surface, layer_centers)):
    print(f"  Couche {i+1}: hk = {hk_val:.2e} m/s, profondeur = {depth:.2f} m, élévation = {elev:.2f} m")

# %%
