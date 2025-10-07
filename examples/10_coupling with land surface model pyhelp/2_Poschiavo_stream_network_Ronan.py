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
import os

# Libraries need to be installed if not
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio

import matplotlib as mpl
import matplotlib.pyplot as plt
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# # Libraries added from 'pip install' procedure
import deepdish as dd
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

import glob

#%% ROOT
"""
# Import HydroModPy modules
from os.path import dirname, abspath
# DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
DIR = 'C:/Users/rabherve/GitHub/HydroModPy-dev/'
sys.path.append(DIR)
"""

# Import HydroModPy modules
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
sys.path.append(os.path.join(DIR, "src"))


# from os.path import dirname, abspath
# root_dir = dirname(dirname(dirname(abspath(__file__))))
# sys.path.append(root_dir)
print("Root path directory is: {0}".format(DIR.upper()))

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


from src.modeling import downslope, modflow, modpath, timeseries


from pyhelp.pyhelp_netcdf import preprocessing_pyhelp


#%% PERSONAL

#data_path = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/Data_temporal/Hydromodpy/'
#gis_path = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/Raster/'

data_path = os.path.join(DIR, "examples", "10_coupling with land surface model pyhelp", "data")

# The folder out_path is created in the example_path root directory:

# Or define it manually
# out_path = "C:/Users/mathi/Dev/pyhelp-master/Poschiavo_Mathias/8_urse/"
out_path = os.path.join(DIR, "examples", "results")

print('The results of the example will be saved here :', out_path)

#%% ---- WATERSHED

#%% OPTIONS

# dem_path = os.path.join(gis_path, 'eu_dem_clipp_ursa_v2.tif')
dem_path = os.path.join(data_path, "ursa_RS3_rot0_250.tif")
watershed_name = "Example_10_Urse"
# watershed_name ='Strengbach'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = [os.path.join(data_path, "watershed_urse_EPSG2056.shp"), 10]
# from_xyv = [327816.965, 6777886.670, 150, 20 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
from_xyv = [2798418.619, 1133789.585, 500, 20, 'EPSG:2056']
bottom_path = None # path
save_object = True

#%% PYHELP_PATH
pyhelp_workdir = os.path.join(out_path, watershed_name, "results_pyhelp")
era5_folder = os.path.join(data_path, "CSVs")

#if already completed grid : 
#grid_base_csv = "C:/Users/Pelissierm/pyhelp/test/CSVs/input_grid_base1.csv"

ready_csvs = [
    os.path.join(era5_folder, "precip_input_data.csv"),
    os.path.join(era5_folder, "airtemp_input_data.csv"),
    os.path.join(era5_folder, "solrad_input_data.csv")
]

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

load = True
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
stable_folder = os.path.join(out_path, 'results_stable')
simulations_folder = os.path.join(out_path, 'results_simulations')

#%% DATA

KB4_loc = [2796960.102,1133328.361] #???
visualization_watershed.watershed_dem(BV)
      
#%% ---- PYHELP

grid_kwargs = dict(
    growth_start=140, growth_end=280, wind=2.5,
    hum1=60, hum2=65, hum3=70, hum4=70,
    nlayer=1, LAI=2.4, EZD=44.5, CN=55,
    lay_type1=1, thick1=100, poro1=0.45, fc1=0.23, wp1=0.116,
    ksat1=0.0037, dist_dr1=50, slope1=35,
)


# CSV météo et grid déjà prêts
"""
nc = preprocessing_pyhelp(
    workdir = pyhelp_workdir,
    outpath = simulations_folder,
    grid_csv = grid_base_csv,
    ready_csvs = ready_csvs,
)
print(nc)
"""

sim_num = "x"

# CSV météo prêts mais update des paramètres du grid
nc = preprocessing_pyhelp(
    workdir = os.path.join(pyhelp_workdir, sim_num),
    outpath = os.path.join(pyhelp_workdir, sim_num),
    #grid_csv = grid_base_csv,
    ready_csvs = ready_csvs,
    grid_kwargs = grid_kwargs,
    dem = dem_path,
    shapefile = from_shp[0],
)
#print(nc)


# Pas de CSV météo ni grid
"""nc = preprocessing_pyhelp(
    workdir = pyhelp_workdir,
    outpath = simulations_folder,
    dem = dem_path,
    #shapefile = from_shp[0],
    era5_folder = era5_folder,
    grid_kwargs = grid_kwargs,           
    conda_env   = "pyhelp_env",
)

print("NetCDF :", nc)"""    



#%% csv formating

csv_path = os.path.join(pyhelp_workdir, sim_num, "help_example_daily_mean.csv")

df = pd.read_csv(csv_path)
df = df.rename(columns={df.columns[0]: "time"})
formatted_csv_path =  pyhelp_workdir + "/help_example_daily_mean_formatted.csv"
df.to_csv(formatted_csv_path, index=False)

#%% YEARLY

rec_path = pyhelp_workdir + "/help_example_daily_mean_formatted.csv"
rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
rec_mean = rec_mean.set_index(['time'])
# rec_mean[rec_mean==0] = np.nan
years = rec_mean.index.year.unique()

# Calculer la moyenne annuelle
rec_annual = rec_mean.resample('Y').sum()

# Extraire les années pour l'axe X
years = rec_annual.index.year
rec_annual.index = years  # Remplacer l'index par les années pures

# Tracé
plt.figure(figsize=(9, 4.5), dpi=150)

plt.plot(rec_annual.index, rec_annual['rechg'], label='Ref', color='black', lw=4)

plt.xlabel('Years')
# plt.yscale('log')  # Optionnel selon échelle
plt.grid(True, which='both', linestyle='--', alpha=0.5)
plt.legend()
plt.title('Recharge [mm/year]')

# Mettre les années en xticks proprement
plt.xticks(ticks=years, labels=[str(y) for y in years])

plt.tight_layout()
plt.show()

#%% MONTHLY

rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
# rec_mean = rec_mean.set_index(['time'])
# rec_mean[rec_mean==0] = np.nan
years = rec_mean['time'].dt.year.unique()

# Ajouter colonnes année et mois
rec_mean['year'] = rec_mean['time'].dt.year
rec_mean['month'] = rec_mean['time'].dt.month

# Sélectionner uniquement les colonnes numériques à sommer
cols_to_sum = ['rechg']

# Grouper par année et mois, et sommer
rec_monthly = rec_mean.groupby(['year', 'month'], as_index=False)[cols_to_sum].sum()

# Créer une colonne datetime pour l'axe x (1er jour de chaque mois)
rec_monthly['time'] = pd.to_datetime(dict(year=rec_monthly['year'], month=rec_monthly['month'], day=1))

# Mettre en index temporel
rec_monthly = rec_monthly.set_index('time')

# Liste des années
years = rec_monthly['year'].unique()

# Tracé
fig, axs = plt.subplots(5, 2, figsize=(12, 12), dpi=300, sharey=True)
axs = axs.ravel()

for i, y in enumerate(years[1:]):  # Saute la première année si besoin
    ax = axs[i]
    data_y = rec_monthly[rec_monthly['year'] == y]

    ax.plot(data_y.index, data_y['rechg'], color='k', lw=3, zorder=2, label='Ref')

    ax.set_yscale('log')
    ax.set_xlim(pd.to_datetime(f'{y}-01-01'), pd.to_datetime(f'{y}-12-31'))
    ax.set_ylim(1e-2, 1e3)
    ax.set_title(str(y))

    month_ticks = pd.date_range(start=f'{y}-01-01', end=f'{y}-12-31', freq='MS')
    ax.set_xticks(month_ticks)
    ax.set_xticklabels([str(m.month) for m in month_ticks])
    
    if i == 0:
        ax.legend(loc='upper left', frameon=False, fontsize=13)

plt.suptitle('Recharge [mm/month]', fontsize=16)
plt.tight_layout()

#%% DAILY

rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
rec_mean = rec_mean.set_index(['time'])
# rec_mean[rec_mean==0] = np.nan
years = rec_mean.index.year.unique()

fig, axs = plt.subplots(5,2, figsize=(12,12), dpi=300, sharey=True)
axs = axs.ravel()

for i, y in enumerate(years[1:]):
    ax = axs[i]
    ax.plot(rec_mean['rechg'], color='k', lw=3, zorder=2, label='Ref')
    ax.set_yscale('log')
    ax.set_xlim(pd.to_datetime('01-'+str(y)), pd.to_datetime('12-'+str(y)))
    # ax.set_xticks(rotation=45)
    ax.set_ylim(1e-2,100)
    # ax.set_ylabel('Recharge [mm/day]')
    # ax.legend(loc='upper left')
    ax.set_title(str(y))
    month_ticks = pd.date_range(start=f'{y}-01-01', end=f'{y}-12-31', freq='MS')
    ax.set_xticks(month_ticks)
    ax.set_xticklabels([str(m.month) for m in month_ticks])
    if i == 0:
        ax.legend(loc='upper left', frameon=False, fontsize=13)

plt.suptitle('Recharge [mm/day]')
plt.tight_layout()

#%% ---- CALIBRATION

#%% CLASS FUNCTION

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
              
        self.prepare_files()
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

#%% PREPARE PARAMETERS FOR RUN

vers = 'DICHOT1' # dichotomy on 30 catchments (all hydrosystems)
 
box = False # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False
dis_perlen = True
nlay = 1
lay_decay = 1 # 1 for no decay
first_clim = 'mean' # or 'first or value
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-10 * 3600 * 24 
Klog_transf = False
sy = 1 / 100 # -
sy_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
hk_decay = 0
ss = 1e-5
ss_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1
bottom = None
thickness = 50

rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
rec_mean = rec_mean.set_index(['time'])

recharge_ref = rec_mean['rechg']

print(f"Recharge rech_ref : {recharge_ref.mean()*365} mm/y")

#%% LAUNCH A FIRST TIME DICHOTOMY

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=None, out_path=out_path, load=True)
area = BV.geographic.area

path_dem = BV.geographic.watershed_dem
dem = imageio.imread(path_dem)
dem = np.ma.masked_array(dem, mask=dem<0)
dem_cells = dem.count()

path_buff = BV.geographic.watershed_buff_dem
buff = imageio.imread(path_buff)
buff = np.ma.masked_array(buff, mask=buff<0)
buff_cells = buff.count()

path_box = BV.geographic.watershed_box_buff_dem
boxc = imageio.imread(path_box)
boxc = np.ma.masked_array(boxc, mask=boxc<0)
boxc_cells = boxc.count()

# Fill
# globals()['df_'+watershed_name] = pd.DataFrame()

# Create folders
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
toolbox.create_folder(simulations_folder)
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
toolbox.create_folder(BV.calibration_folder)
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

# Type obs hydro
BV.add_hydrography(data_path+'/'+'hydro/', types_obs=['stream_network_urse_reproj'])
        
# Objects
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()
BV.add_oceanic(sea_level)

# Updated
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.climatic.update_first_clim(first_clim)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_sy(sy)
BV.hydraulic.update_sy_decay(sy_decay)
BV.hydraulic.update_ss(ss)
BV.hydraulic.update_ss_decay(ss_decay)
BV.hydraulic.update_vka(vka)
BV.hydraulic.update_hk_vertical(verti_hk)
BV.hydraulic.update_sy_vertical(verti_sy)
BV.hydraulic.update_ss_vertical(verti_ss)
BV.hydraulic.update_bottom(bottom)
BV.settings.update_dis_perlen(dis_perlen)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.settings.update_input_particles(zone_partic=zone_partic)
BV.hydraulic.update_hk_decay(hk_decay, min_value=Kmin, log_transf=Klog_transf) # 0
BV.hydraulic.update_thick(thickness) # 30 / intervient pas si bottom != None

recharges = [
    ("ref", recharge_ref)
]

for irec, (name, drec) in enumerate(recharges):
    print(f"{irec}: traitement de la recharge {name}")
    
    df_optim = pd.DataFrame()
    df_calib = pd.DataFrame()
    
    # Specific recharge
    recharge = drec.mean()/1000
    BV.climatic.update_recharge(recharge, sim_state=sim_state)
        
    KRmin = 1
    KRmax = 10000

    # Define permeability range
    Kmin = KRmin * recharge
    Kmax = KRmax * recharge
    
    # Params
    params_df = pd.DataFrame(columns=['params', 'init_values', 'lower_bounds', 'higher_bounds', 'units', 'scale'])
    params_df.loc[0] = ['k1', '?', Kmin, Kmax, 'm/j', 'lin']
    params_file = vers+'_BOUNDS_CALIB_PARAMS'
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
    
    p_min = params_df['lower_bounds'].values[0]
    p_max = params_df['higher_bounds'].values[0]
    diff = p_max - p_min
    half = (p_min + p_max) / 2

    # start = datetime.datetime.now()
    # oclock_start = start.strftime("%Y%m%d_%Hh%Mm%Ss")
    
    gap = 1
    compt = 0
    
    success_modflow = False # init
    
    list_of_model_names = []

    # Main dichotomy loop
    
    valid_result = True
    
    while (diff > ((gap/100) * half)):
                            
        # now = datetime.datetime.now()
        # if  (now - start).seconds > datetime.timedelta(seconds=5*60).total_seconds():
        #     print("Loop exceeded 5 minutes, terminating.")
        #     df_optim.loc[0,:] = np.nan
        #     df_optim.loc[0,'NAME_RECAL'] = watershed_name   
        #     success_modflow = False
        #     break                    
        
        half = (p_min + p_max) / 2
        hyd_cond = half.copy() # if K in calib_params.csv
        kr = hyd_cond / BV.climatic.recharge
        
        # Update value
        BV.hydraulic.update_hk(hyd_cond)
        
        # Change
        model_name = vers+'_'+\
                     str(name)+'_'+\
                     str(watershed_name)+'_'+str(int(round(area,1)))+'_'+\
                     str(compt)+'_'+\
                     str(round(thickness,1))+'-'+str(int(round(recharge*365*1000,1)))+'_'+\
                     str("{:.1e}".format(hyd_cond/24/3600))+'-'+str(int(round(hyd_cond/recharge,1))) #+'-'+oclock
                     
        print(model_name)
        BV.settings.update_model_name(model_name)
        
        # Check grid                    
        if compt == 0:
            check_grid = True
        else:
            check_grid = False                        
        BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)

        # Run
        model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
        success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
        
        # if not success_modflow:
        #     print("Modflow run failed, retrying if possible.")
        #     break  # Sortie prématurée pour forcer retry
        
        # Cells
        if compt == 0:
            prob_cells = model_modflow.prob_cells
        
        # Post-process
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  accumulation_flux = True,
                                  watertable_depth = True, 
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  intermittency_yearly = True,
                                  export_all_tif = False)
        
        iter_results = MatchingStreams(BV, iteration_label=model_name, from_calib=True)
        
        # obs_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
        # obs_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
        # obsf_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
        obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflowf.shp'))
        
        if not os.path.exists(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp')):
            valid_result = False
            break  # Sortie prématurée pour forcer retry ==> not really good
        
        # sim_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
        # sim_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
        # simf_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
        simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))
    
        # mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
        # mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
        # mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
        mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])
        
        # mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
        # mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
        # mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
        mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])
                
        ### Conditions
        obs = mean_obsf_to_simf
        sim = mean_simf_to_obsf
        indicator = sim/obs
    
        if sim > obs:
            p_min = half
        if sim < obs:
            p_max = half
        if np.isnan(indicator):
            p_max = half
        
        diff = p_max - p_min
        
        print('==> SIMULATION : '+str(compt))
        print('    K/R = '+str(round(kr, 4)))
        print('    GAP = '+str(round((gap/100) * kr, 4)))
        print('    INDICATOR = '+str(round(indicator, 4)))
                                                
        list_of_model_names.append(BV.calibration_folder+'/'+model_name+'/')
        
        df_calib.loc[compt,'IDX_NODPOL'] = i
        df_calib.loc[compt,'NAME_RECAL'] = watershed_name  
        df_calib.loc[compt,'MODEL_NAME'] = model_name
        df_calib.loc[compt,'COMPT_SIM'] = compt
        df_calib.loc[compt,'INPUT_REC'] = round(BV.climatic.recharge*1000*365, 4) # mm/y
        df_calib.loc[compt,'AQUI_THICK'] = round(thickness, 4)
        df_calib.loc[compt,'DSO'] = round(sim, 4)
        df_calib.loc[compt,'DOS'] = round(obs, 4)
        df_calib.loc[compt,'DOPTIM'] = round((sim+obs)/2, 4)            
        df_calib.loc[compt,'DSO/DOS'] = round(indicator, 4)
        df_calib.loc[compt,'DSO/DOS_LG'] = round(np.log10(indicator)**2, 10)                    
        df_calib.loc[compt,'K_OPTIM'] = float("{:.5e}".format(hyd_cond/24/3600))                
        df_calib.loc[compt,'K/R_OPTIM'] = round(hyd_cond/BV.climatic.recharge, 4)
        df_calib.loc[compt,'TMAX_OPTIM'] = df_calib.loc[compt,'K_OPTIM'] * thickness

        compt += 1
        
    # if valid_result == True:
    #     break
    # else:
    #     print("PROBLEM!")
        
    # if (success_modflow==True) and (os.path.exists(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))):
    #     break  # Exit retry loop if successful

    if (success_modflow==True) and (os.path.exists(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))):
        # break  # Exit retry loop if successful

        # for to_delete in list_of_model_names[:-1]:
        #     shutil.rmtree(to_delete)
        
        # Save ALL
        name_for_save = vers+'_'+str(name)+'_'+str(watershed_name)+'_'+str(round(area,1))
        df_calib.to_csv(BV.calibration_folder+'/'+name_for_save+'_CALIB'+'.csv', sep=';', index=True)
    
        # Save model_modflow
        model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
        dictio = {}
        dictio['model_modflow'] = model_modflow
        h5file = BV.calibration_folder+'/'+model_name+'.h5'
        dd.io.save(h5file, dictio)
        # d = dd.io.load(h5file)
        # model_modflow = d['model_modflow'][:]
        del(dictio)

        # print(list_of_model_names)  
        
        # for to_delete in list_of_model_names[:-1]:
        #     shutil.rmtree(to_delete)
        
        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          datetime_format=False,
                                                          subbasin_results=False,
                                                          intermittency_yearly=True) # or None
        
        listfile = os.path.join(BV.calibration_folder, model_name, model_name + '.list')
        # lst = MfListBudget(listfile)  # <-- utile si tu veux analyser les budgets
        # with open(listfile, 'r') as f:
        #     lines = f.readlines()
        # for line in reversed(lines):
        #     if "Elapsed run time" in line:
        #         match = re.search(r'Elapsed run time:\s+([\d.]+)\s+Seconds', line)
        #         if match:
        #             elapsed_time = float(match.group(1))
        #             print(f"Temps de simulation : {elapsed_time} secondes")
        #         del(lines)
        #         break
        
        del(model_modflow)

        # end = datetime.datetime.now()
        # oclock_end = end.strftime("%Y%m%d_%Hh%Mm%Ss")
        
        sim_series = pd.read_csv(BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_timeseries/_simulated_timeseries.csv', sep=';')
        
        df_optim.loc[0,'IDX_NODPOL'] = i
        df_optim.loc[0,'NAME_RECAL'] = watershed_name
        
        # df_optim.loc[0,'HYDRO_OBS'] = type_obs
        df_optim.loc[0,'MODEL_NAME'] = model_name
        
        df_optim.loc[0,'GRID_RES'] = 75
        df_optim.loc[0,'GRID_BOX'] = boxc_cells
        df_optim.loc[0,'GRID_BUFF'] = buff_cells
        df_optim.loc[0,'GRID_CATCH'] = dem_cells
        df_optim.loc[0,'GRID_CHECK'] = round(prob_cells, 4)
        
        df_optim.loc[0,'COMPT_SIM'] = compt
        
        # df_optim.loc[0,'TIME_BEG'] = oclock_start
        # df_optim.loc[0,'TIME_END'] = oclock_end
        # df_optim.loc[0,'TIME_CAL'] = abs((start - end).total_seconds() / 60) # min
        # df_optim.loc[0,'TIME_SIM'] = round(elapsed_time,2)
        
        df_optim.loc[0,'INPUT_REC'] = round(BV.climatic.recharge*1000*365, 4) # mm/y
        df_optim.loc[0,'AQUI_THICK'] = round(thickness, 4)
    
        df_optim.loc[0,'DSO'] = round(sim, 4)
        df_optim.loc[0,'DOS'] = round(obs, 4)
        df_optim.loc[0,'DOPTIM'] = round((sim+obs)/2, 4)

        df_optim.loc[0,'DSO/DOS'] = round(indicator, 4)
        df_optim.loc[0,'OF_DSO/DOS'] = round(np.log10(indicator)**2, 10)
    
        df_optim.loc[0,'K_OPTIM'] = float("{:.5e}".format(hyd_cond/24/3600))                
        df_optim.loc[0,'K/R_OPTIM'] = round(hyd_cond/BV.climatic.recharge, 4)
        
        df_optim.loc[0,'WT_ELEV'] = round(sim_series['watertable_elevation'].values[0], 4)
        df_optim.loc[0,'WT_DEPTH'] = round(sim_series['watertable_depth'].values[0], 4)
        
        df_optim.loc[0,'HSAT_OPTIM'] = round(thickness - sim_series['watertable_depth'].values[0], 4) 
        df_optim.loc[0,'HSAT_PROP'] = round((sim_series['watertable_depth'].values[0]/(thickness - sim_series['watertable_depth'].values[0])), 4)
        
        df_optim.loc[0,'TMAX_OPTIM'] = df_optim.loc[0,'K_OPTIM'] * thickness
        df_optim.loc[0,'TSAT_OPTIM'] = df_optim.loc[0,'K_OPTIM'] * df_optim.loc[0,'HSAT_OPTIM']
                    
        df_optim.loc[0,'GW_STORAG'] = round(sim_series['groundwater_storage'].values[0], 4)
        df_optim.loc[0,'GW_FLOW'] = round(sim_series['groundwater_flux'].values[0]/(75*50), 4)
        
        df_optim.loc[0,'DD_SEEP'] = round(sim_series['seepage_areas'].values[0], 4)
        df_optim.loc[0,'DD_NETW'] = round(sim_series['total_areas'].values[0], 4)
        df_optim.loc[0,'DD_RATIO'] = round(sim_series['total_areas'].values[0]/sim_series['seepage_areas'].values[0], 4)
        
        df_optim.loc[0,'OUT_SEEP'] = round(sim_series['outflow_drain'].values[0]*365*1000, 4)
        df_optim.loc[0,'OUT_ACC'] = round((1000*(BV.geographic.area*1e6)*sim_series['outflow_drain'].values[0])/24/60/60, 4)               
        # df_optim.loc[0,'OUT_ACC'] = round(sim_series['accumulation_flux'].values[0]/24/60/60, 4)
        # ==> Potential troubles with accumulation_flux raster
        df_optim.loc[0,'OUT_PROP'] = round(df_optim.loc[0,'OUT_SEEP'] / df_optim.loc[0,'INPUT_REC'], 4)
                                                
        df_optim.to_csv(BV.calibration_folder+'/'+name_for_save+'_OPTIM'+'.csv', sep=';', index=True)

    else:
        df_optim.loc[0,:] = np.nan
        df_optim.loc[0,'NAME_RECAL'] = watershed_name
                            
        name_for_save = vers+'_'+str(name)+'_'+str(watershed_name)+'_'+str(round(area,1))
        df_optim.to_csv(BV.calibration_folder+'/'+name_for_save+'_OPTIM'+'.csv', sep=';', index=True)

#%% QUICK FIGURES CALIBRATION

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=None, out_path=out_path, load=True)
area = BV.geographic.area

stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

model_name_ref = 'DICHOT1_ref_Example_10_Urse_6_0_50-752_1.2e-04-5000'

WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')
WC_shp = gpd.read_file(WC0)

HYD0 = os.path.join(stable_folder, 'hydrography', 'stream_network_urse_reproj.shp')
HYD_shp = gpd.read_file(HYD0)

for i, model_name in enumerate([model_name_ref]):
    
    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
    calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

    simflowf = gpd.read_file(calibration_folder+'/'+model_name+'/_matchingstreams/'+'simflowf.shp')
    
    fig, ax = plt.subplots(1,1, figsize=(10,10), dpi=300)
    
    simflowf.plot(ax=ax, column='VALUE1', cmap='RdYlGn_r', lw=0, zorder=1)
    
    HYD_shp.plot(ax=ax, color='blue', lw=2, zorder=0)
    
    WC_shp.plot(ax=ax, facecolor='None', zorder=2, lw=2)
    
    ax.set_title(model_name, fontsize=10)
    
#%% ---- TRANSIENT

#%% PARAMETERS

    
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')


BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=None, out_path=out_path, load=True)
area = BV.geographic.area

# Objects
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()
BV.add_oceanic('None')

box = False # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = False
dis_perlen = True
nlay = 1
lay_decay = 1 # 1 for no decay
first_clim = 'mean' # or 'first or value
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-10 * 3600 * 24 
Klog_transf = False
sy = 1 / 100 # -
sy_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
hk_decay = 0
ss = 1e-5
ss_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1
bottom = None
thickness = 50

rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
rec_mean = rec_mean.set_index(['time'])

recharge_ref = rec_mean['rechg']

print(f"Recharge rech_ref : {recharge_ref.mean()*365} mm/y")

# Updated
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.climatic.update_first_clim(first_clim)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_sy(sy)
BV.hydraulic.update_sy_decay(sy_decay)
BV.hydraulic.update_ss(ss)
BV.hydraulic.update_ss_decay(ss_decay)
BV.hydraulic.update_vka(vka)
BV.hydraulic.update_hk_vertical(verti_hk)
BV.hydraulic.update_sy_vertical(verti_sy)
BV.hydraulic.update_ss_vertical(verti_ss)
BV.hydraulic.update_bottom(bottom)
BV.settings.update_dis_perlen(dis_perlen)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.settings.update_input_particles(zone_partic=zone_partic)
BV.hydraulic.update_hk_decay(hk_decay, min_value=Kmin, log_transf=Klog_transf) # 0
BV.hydraulic.update_thick(thickness) # 30 / intervient pas si bottom != None

#%% MODFLOW

model_name_ref = 'DICHOT1_ref_Example_10_Urse_6_0_50-752_1.2e-04-5000'

WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')
WC_shp = gpd.read_file(WC0)

HYD0 = os.path.join(stable_folder, 'hydrography', 'stream_network_urse_reproj.shp')
HYD_shp = gpd.read_file(HYD0)

recharges = [
    ("ref", recharge_ref)
]

list_model_name = []
list_success_modflow = []
list_model_modflow = []

iD_set_simulations = 'TRANS1'

for irec, (name, drec) in enumerate(recharges):
    print(f"{irec}: traitement de la recharge {name}")

    recharge = drec / 1000
    # recharge = recharge.to_frame()
    # recharge.index.name = None
    BV.climatic.update_recharge(recharge, sim_state=sim_state)
    
    rech_mean_day = recharge.mean()
    
    name_for_save = 'DICHOT1'+'_'+str(name)+'_'+str(watershed_name)+'_'+str(round(area,1))

    read_optim = pd.read_csv(BV.calibration_folder+'/'+name_for_save+'_OPTIM'+'.csv', sep=';')
    
    K_optim = (read_optim['K_OPTIM']*60*60*24)[0] # m/s to m/day

    BV.hydraulic.update_hk(K_optim)
    
    model_name = iD_set_simulations+'_'+name+'_'+str(round((K_optim/rech_mean_day),1))
    BV.settings.update_model_name(model_name)
    print(model_name)
    
    BV.settings.update_check_model(plot_cross=False, check_grid=True)

    model_modflow = BV.preprocessing_modflow(for_calib=False)
    success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
    
    list_model_name.append(model_name)
    list_success_modflow.append(success_modflow)
    list_model_modflow.append(model_modflow)

print(list_model_name)
print(list_success_modflow)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_success_modflow'] = list_success_modflow
dictio['list_model_modflow'] = list_model_modflow
h5file = os.path.join(simulations_folder,'results_listing_'+iD_set_simulations)
    
dd.io.save(h5file, dictio)

#%% RELOAD

iD_set_simulations = 'TRANS1'

h5file = os.path.join(simulations_folder,'results_listing_'+iD_set_simulations)
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_success_modflow = d['list_success_modflow'][:]
list_model_modflow = d['list_model_modflow'][:]
# sys.exit(1)

#%% POSTPROCESSING

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
                                  persistency_index = True,
                                  intermittency_daily = True,
                                  intermittency_weekly = False,
                                  intermittency_monthly = False,
                                  export_all_tif = True)
        
        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          datetime_format=True, 
                                                          subbasin_results=True,
                                                          intermittency_daily=True) # or None
        
        netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                                  datetime_format=True)

#%% QUICK FIGURES TRANSIENT

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=None, out_path=out_path, load=True)
area = BV.geographic.area

stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

model_name_ref = 'TRANS1_ref_129.2'

WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')
WC_shp = gpd.read_file(WC0)

HYD0 = os.path.join(stable_folder, 'hydrography', 'stream_network_urse_reproj.shp')
HYD_shp = gpd.read_file(HYD0)

from matplotlib.colors import ListedColormap, BoundaryNorm
import matplotlib.pyplot as plt
import matplotlib.cm as cm

# Discretize 'jet_r' into 10 colors
n_colors = 10
cmap = ListedColormap(cm.get_cmap('jet_r', n_colors)(np.arange(n_colors)))
bounds = np.linspace(0, 1, n_colors + 1)
norm = BoundaryNorm(bounds, cmap.N)

for i, model_name in enumerate([model_name_ref]):
    
    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
    calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    persist = rasterio.open(simulations_folder+'/'+model_name+'/_postprocess/_rasters/persistency_index_t(-).tif')

    persist_data = persist.read(1)
    persist_masked = np.ma.masked_where((persist_data <= 0) | (dem.read(1) < 0), persist_data)

    fig, ax = plt.subplots(1, 1, figsize=(10, 10), dpi=300)

    rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)),
                       ax=ax, transform=dem.transform,
                       cmap='Greys', alpha=0.5, zorder=-5)

    img = rasterio.plot.show(persist_masked, ax=ax, transform=dem.transform,
                             cmap=cmap, norm=norm, alpha=1, zorder=-4)

    WC_shp.plot(ax=ax, facecolor='None', edgecolor='black', lw=2, zorder=2)

    ax.set_title(model_name, fontsize=10)

    cbar = fig.colorbar(img.get_images()[1], ax=ax, fraction=0.03, pad=0.02,
                        ticks=np.round(bounds, 2))
    cbar.set_label('Persistency Index')

    plt.tight_layout()

#%% ---- PLOT MATHIAS

#%% CROSS
"""
compt = 1

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    
    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

    dem_data = imageio.imread(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    wt_data = imageio.imread(os.path.join(simulations_folder, model_name, 
                                          r'_postprocess/_rasters/watertable_elevation_t(0).tif'))
    wt_data = np.ma.masked_where(wt_data < 0, wt_data)
    
    # river_data = imageio.imread(os.path.join(stable_folder, 'hydrography', 
    #                                          'regional stream network.tif'))

    xvalues = np.linspace(-1,1,dem_data.shape[1])
    yvalues = np.linspace(-1,1,dem_data.shape[0])
    xx, yy = np.meshgrid(xvalues,yvalues)
    
    cur_x = dem_data.shape[1] /2
    # cur_y = dem_data.shape[0] /2
    
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    dem_v_plot = dem_prof[:,int(cur_x)]
    dem_v_plot[dem_v_plot == 0] = np.nan

    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    wt_v_plot = wt_prof[:,int(cur_x)]
    wt_v_plot[wt_v_plot == 0] = np.nan

    # wt_prof_min = wt_data.astype(float)
    # wt_prof_min[wt_prof_min<0] = np.nan
    # wt_v_plot_min = wt_prof_min[:,int(cur_x)]
    # wt_v_plot_min[wt_v_plot_min == 0] = np.nan
    
    # Facecolor watertable
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75,
                                dem_v_plot-30, wt_v_plot,
                                color='dodgerblue', alpha=0.5, lw=0)
    # Line watertable
    w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1)
    
    # Facecolor unsaturated
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 
                                wt_v_plot, dem_v_plot,
                                color='saddlebrown', alpha=0.5, lw=0)
    
    # Line unsaturated
    d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
    
    # Facecolor noflow
    ax.fill_between(np.arange(xx.shape[0])*75,
                    0, dem_v_plot-30,
                    color='lightgrey', alpha=1, lw=0, zorder=10)
    # Line noflow
    ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-30, color='dimgray', lw=1.5)
    
    # Settings
    # ax.set_xlim(1000, 4000)
    ax.set_ylim(2000, 3000)
    # ax.set_yticks([90,100,110,120,130])
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')
    ax.set_title('K = '+'{:.2e}'.format(model_modflow.hk.mean()/24/3600)+' m/s')
    
    compt += 1
    
    # fig.tight_layout
    
    # fig.savefig(os.path.join(model_modflow.figure_file,
    #             'CROSS_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
        
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'CROSS_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')

""" 
#%% MAP
import rasterio
from rasterio.plot import show
import geopandas as gpd
from rasterio.features import geometry_mask
compt = 0
stream_obs=gpd.read_file("C:/Users/mathi/Dev/pyhelp-master/Poschiavo_Mathias/8_urse/stream_network_urse.shp")

   
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

lin0 = os.path.join(stable_folder, 'geographic', 'watershed_contour.tif')
mask0 = os.path.join(stable_folder, 'geographic', 'watershed_dem.tif')
WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')

WC_shp = gpd.read_file(WC0)
stream_obs_clip = gpd.clip(stream_obs, WC_shp)

with rasterio.open(mask0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent2 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

with rasterio.open(lin0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent1 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    

    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)
    
    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)),
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.25, zorder=0)

    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
    
    stream_obs_clip.plot(ax=ax, edgecolor="cyan",linewidth=0.5)
    # ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
    #              pad=10, fontsize=10)
    ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0, extent=extent2)

    # dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
    # dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    # contour = imageio.imread(BV.geographic.watershed_contour_tif)
    # contour = np.ma.masked_where(contour < 0, contour)
    
    # obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
    #                                              'regional stream network.tif'))
    # obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)
    
    seep_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                  r'_postprocess/_rasters/seepage_areas_t(0).tif'))
    seep_river_data = np.ma.masked_where((seep_river_data <= 0) | (mask <0), seep_river_data)
    # seep_river_data = rasterio.mask(seep_river_data, WC0)
    
    
    sim_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                 r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
    sim_river_data = np.ma.masked_where((sim_river_data <= 0) | (mask <0), sim_river_data)
    
    
    # im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
    # im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
    # im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
    im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7, extent=extent2)
    im_seep = ax.imshow(seep_river_data, cmap=mpl.colors.ListedColormap('darkorange'), alpha=0.7, extent=extent2)

    # ax.set_xlabel('X [pixels]')
    # ax.set_ylabel('Y [pixels]')
    # ax.set_title('K = '+'{:.2e}'.format(model_modflow.hk.mean()/24/3600)+' m/s')
    # ax.set_title('K = '+'{:.1e}'.format(model_modflow.hk.mean())+' m/d')
    ax.set_title('K/R = '+'{:.1f}'.format(model_modflow.hk.mean()/recharge))
    ax.imshow(line, cmap=mpl.colors.ListedColormap('k'), extent=extent1)
    ax.plot(KB4_loc[0],KB4_loc[1], 'r*')
    plt.axis('off')
    compt += 1
    
    fig.tight_layout()

    # fig.savefig(os.path.join(model_modflow.figure_file,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
    
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
#%% MAP outlet flow
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

lin0 = os.path.join(stable_folder, 'geographic', 'watershed_contour.tif')
mask0 = os.path.join(stable_folder, 'geographic', 'watershed_dem.tif')
WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')

WC_shp = gpd.read_file(WC0)
stream_obs_clip = gpd.clip(stream_obs, WC_shp)

with rasterio.open(mask0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent2 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

with rasterio.open(lin0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent1 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
    
    stream_obs_clip.plot(ax=ax, edgecolor="cyan",linewidth=0.5)
    # ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
    #              pad=10, fontsize=10)
    ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0, extent=extent2)

    # dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
    # dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    # contour = imageio.imread(BV.geographic.watershed_contour_tif)
    # contour = np.ma.masked_where(contour < 0, contour)
    
    # obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
    #                                              'regional stream network.tif'))
    # obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)
    
    seep_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                  r'_postprocess/_rasters/outflow_drain_t(0).tif'))
    seep_river_data = np.ma.masked_where((seep_river_data <= 0) | (mask <0), seep_river_data)
    # seep_river_data = rasterio.mask(seep_river_data, WC0)
    
    
    sim_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                 r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
    sim_river_data = np.ma.masked_where((sim_river_data <= 0) | (mask <0), sim_river_data)
    
    
    # im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
    # im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
    # im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
    # im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7, extent=extent2)
    im_seep = ax.imshow(seep_river_data, cmap='jet', alpha=0.7, extent=extent2)

    # ax.set_xlabel('X [pixels]')
    # ax.set_ylabel('Y [pixels]')
    # ax.set_title('K = '+'{:.2e}'.format(model_modflow.hk.mean()/24/3600)+' m/s')
    # ax.set_title('K = '+'{:.1e}'.format(model_modflow.hk.mean())+' m/d')
    ax.set_title('K/R = '+'{:.1f}'.format(model_modflow.hk.mean()/recharge))
    ax.imshow(line, cmap=mpl.colors.ListedColormap('k'), extent=extent1)
    ax.plot(KB4_loc[0],KB4_loc[1], 'r*')
    plt.axis('off')
    compt += 1
    
    fig.tight_layout()

    # fig.savefig(os.path.join(model_modflow.figure_file,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
    
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')    
#%% GRAPH

fig, ax = plt.subplots(1, 1, figsize=(5,4), dpi=300)

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    
    simulations_folder = os.path.join(out_path, watershed_name, 
                                      'results_simulations')
    
    simul_csv = pd.read_csv(os.path.join(simulations_folder, model_name,
                            r'_postprocess/_timeseries/', '_simulated_timeseries.csv'),
                            sep=';')
    

    ax.plot(model_modflow.hk.mean()/24/3600,
            simul_csv['seepage_areas'],
            marker='o', ms=8, lw=0, color='k')
    
    ax.set_xscale('log')
    ax.set_xlabel('K [m/s]')
    ax.set_ylabel('Drainage density [%]')
    
    # fig.tight_layout()
    
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'GRAPH_sat_'+iD_set_simulations+'.png'),
    #             bbox_inches='tight')

#%% ---- NOTES

os.chdir(DIR)
