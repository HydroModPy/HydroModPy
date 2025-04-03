# -*- coding: utf-8 -*-
"""
Created on Fri Mar 21 10:39:38 2025

@author: Ronan
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
import rasterio as rio
import geopandas as gpd
import glob
import matplotlib.dates as mdates
import rasterio
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib as mpl
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# # Libraries added from 'pip install' procedure
import deepdish as dd
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Add
from shapely.geometry import LineString, Polygon, MultiPolygon
import flopy
import flopy.utils.postprocessing as pp
import flopy.utils.binaryfile as bf 
from scipy.optimize import minimize
import datetime

#%% ROOT

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
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

#%% PATHS

regression_path = os.path.join(root_dir, "examples", "09_transport model for an agricultural catchment/")
data_path = os.path.join(regression_path, "data/")

# The folder out_path is created in the example_path root directory:
out_path = os.path.join(root_dir, "examples", "results")
# Or define it manually
# out_path = 'C:/Simulations/HydroModPy/'

print('The results of the example will be saved here :', out_path)

#%% ---- WATERSHED

#%% OPTIONS

dem_path = data_path + 'bdalti25m_naizin_regional_v0.tif'
load = True
watershed_name = 'Example_09_Naizin'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = [265545.208,6783317.640, 50, 20 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
bottom_path = None # path
save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

load = load
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
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

#%% DATA

BV.add_hydrography(data_path , types_obs=['botopage2024_naizin_streams_perennial-intermittent'], fields_obs=['FID'])
BV.add_subbasin(data_path, 50)

visualization_watershed.watershed_local(dem_path, BV)
visualization_watershed.watershed_dem(BV)

area = BV.geographic.area

#%% ---- RECHARGE

#%% CASES

# Necessary to set model parameters
BV.add_climatic()

# BV.climatic.update_sim2_reanalysis(var_list=['recharge', 'runoff',],
#                                         nc_data_path=data_path,
#                                         first_year=1990,
#                                         # last_year=2002,
#                                         time_step='D',
#                                         sim_state='transient',
#                                         spatial_mean=True,
#                                         geographic=BV.geographic,
#                                         disk_clip='watershed')

BV.climatic.update_recharge_reanalysis(path_file=data_path+'_climate_REANALYSIS.csv',
                                        clim_mod='REA',
                                        clim_sce='historic',
                                        first_year=2000,
                                        last_year=2019,
                                        time_step='W',
                                        sim_state='transient')

BV.climatic.update_runoff_reanalysis(path_file=data_path+'_climate_REANALYSIS.csv',
                                      clim_mod='REA',
                                      clim_sce='historic',
                                      first_year=2000,
                                      last_year=2019,
                                      time_step='W',
                                      sim_state='transient')

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

R_mm_day = BV.climatic.recharge
r_mm_day = BV.climatic.runoff

fig, axs = plt.subplots(2,1, figsize=(8,5), sharex=True)
axs = axs.ravel()

ax = axs[0]
ax.plot(7*R_mm_day, label='Recharge', c='navy', lw=1)
ax.fill_between(R_mm_day.index, 7*R_mm_day, (7*R_mm_day)+(7*r_mm_day), label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
ax.set_ylabel('[mm/week]')
ax.legend(loc='upper right')
ax.set_title('No log', fontsize=8)

ax = axs[1]
ax.plot(7*R_mm_day, label='Recharge', c='navy', lw=1)
ax.fill_between(R_mm_day.index, 7*R_mm_day, (7*R_mm_day)+(7*r_mm_day), label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
ax.set_yscale('log')
ax.set_xlabel('Date')
ax.set_title('Log', fontsize=8)

# Save plot as PNG
fig.tight_layout()

#%% ---- MODELING

#%% VERSION

vers = 'TRANS13' # 10.0 %

#%% FUNCTION

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

#%% MODFLOW

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=None, out_path=out_path, load=True)
area = BV.geographic.area

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/' # necessary for plots

BV.calibration_folder = calibration_folder
        
box = True # or False
sink_fill = False # or True
# sim_state = 'steady' # 'steady' or 'transient'
sim_state = 'transient' # 'steady' or 'transient'
# first_clim = 'mean' # or 'first or value
plot_cross = True
cross_ylim = [0,150]
check_grid = True
dis_perlen = True
nlay = 10
lay_decay = 1.2 # 1 for no decay
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
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
bottom = 0 
thickness = 100
Klog_transf = False

# Recharge
BV.add_climatic()
# recharge = 200 / 1000 / 365
# runoff = (200*0.1) / 1000 / 365
# first_clim = 'mean' # or 'first or value
R_mm_day = (R_mm_day * 0) + 2
recharge = select_period(R_mm_day/1000, 2003, 2003)
runoff = select_period(r_mm_day/1000, 2003, 2003)
first_clim = 200/365/1000 # or 'first or value
BV.climatic.update_first_clim(first_clim)
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_runoff(runoff, sim_state=sim_state)

# Objects
BV.add_settings()
BV.add_hydraulic()
BV.add_oceanic(sea_level)

# Fixed
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
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
BV.hydraulic.update_thick(thickness)

alpha = 15 # in m
n_factor = 2

the_K0 = 5e-5*24*3600
BV.hydraulic.update_hk(the_K0)
Kmin_for_hk_decay = 1e-8*24*3600
BV.hydraulic.update_hk_decay(1/alpha, min_value=Kmin_for_hk_decay, log_transf=Klog_transf, grad_elev=[93,136,-20]) # 0

# the_sy0 = 0.1/100 #
the_sy0 = 10/100 #
BV.hydraulic.update_sy(the_sy0)
Symin_for_sy_decay = 0.1/100   
BV.hydraulic.update_sy_decay((1/alpha)/n_factor, min_value=Symin_for_sy_decay, log_transf=Klog_transf, grad_elev=[93,136,-20]) # 0
# BV.hydraulic.update_sy_decay(0) # 0

the_ss0 = 1e-10
BV.hydraulic.update_ss(the_ss0)
# Ssmin_for_ss_decay = 1e-10 
# BV.hydraulic.update_ss_decay((1/alpha)/n_factor, min_value=Ssmin_for_ss_decay, log_transf=Klog_transf, grad_elev=[93,136,-20]) # 0
BV.hydraulic.update_ss_decay(0) # 0

compt = 0

# Change

model_name = vers+'_'+str(watershed_name)+'_'+str(round(area,1))+'_'+str(round(np.mean(recharge)*365*1000,1))+'_'+\
             str(compt)+'_'+\
             str(round(the_K0/np.mean(recharge),1))+'_'+\
             str("{:.2e}".format(the_K0/24/3600))+'-'+str(round(alpha,1))+'_'+\
             str(round(the_sy0*100,1))+'_'+\
             str("{:.2e}".format(the_ss0))
print(model_name)

BV.settings.update_model_name(model_name)

BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid, cross_ylim=[0,200])

model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
          
list_model_name = []
list_model_name.append(model_name)
list_model_modflow = []
list_model_modflow.append(model_modflow)
     
dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_model_modflow'] = list_model_modflow
h5file = BV.calibration_folder+'/'+model_name+'/'+'results_'+model_name
dd.io.save(h5file, dictio)
    
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

prob_cells = model_modflow.prob_cells

BV.postprocessing_modflow(model_modflow,
                          watertable_elevation = True,
                          seepage_areas = True,
                          outflow_drain = True,
                          accumulation_flux = True,
                          watertable_depth = True, 
                          groundwater_flux = False,
                          groundwater_storage = False,
                          intermittency_weekly = True,
                          intermittency_yearly = False,
                          export_all_tif = False)

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=None,
                                                  datetime_format=True, 
                                                  subbasin_results=True,
                                                  intermittency_weekly=True,
                                                  intermittency_yearly=False) # or None

"""
iter_results = MatchingStreams(BV, iteration_label=model_name, from_calib=True)

# obs_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
# obs_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
# obsf_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflowf.shp'))

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
        
### vf simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year) ==> isba
obs = mean_obsf_to_simf
sim = mean_simf_to_obsf
indicator = sim/obs
"""

#%% PLOT STREAMFLOW

area = int(round(BV.geographic.area))

Qobs_path = data_path + 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'
Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
date = pd.to_datetime(Qobs[0]+' '+Qobs[1], format="%d/%m/%Y %H:%M:%S")
Qobs.index = date
Qobs = Qobs[2].to_frame(name="Q")
Qobs = Qobs / 1000 # L/d to m3/d
Qobs = (Qobs / (area*1000000)) # m3/d to m/day
Qobs = Qobs.resample('W').mean()
# Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month
# Qobs = select_period(Qobs, 2003, 2003)
Qobs = Qobs * 7 * 1000

simul_list = sorted(glob.glob(os.path.join(calibration_folder,vers+'*')), key=os.path.getmtime)

for i, simul in enumerate(simul_list[:]):
    
    fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(12,3.5), dpi=300)

    model_name = os.path.split(simul)[-1]

    Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    
    Rmod = Smod['recharge'] * 7 * 1000
    rmod = Smod['runoff'] * 7 * 1000 
    
    Omod = (Smod['outflow_drain'] * 7 * 1000)
    Qmod = Omod + rmod
    
    ax = a0
    ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
    ax.fill_between(Omod.index, Omod, Qmod, color='red', lw=1, label='Simualted : outflow + runoff', alpha=0.5)
    ax.plot(Omod, color='red', lw=2, label='Simulated: outflow')
    ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
    ax.set_xlabel('Date')
    ax.set_ylabel('Q / A [mm/week]')
    # ax.set_yscale('log')
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.set_xlim(pd.to_datetime('2002'), pd.to_datetime('2005'))
    ax.legend(loc='upper left')
    ax.set_title(model_name.upper(), fontsize=10)
    ax.set_ylim(None,50)
    
    axb = ax.twinx()
    axb.bar(Rmod.index, Rmod, color='dodgerblue', width=10, edgecolor='None', lw=0, alpha=1, label='Recharge')
    axb.set_ylim(0,100)
    axb.invert_yaxis()
    axb.set_yticklabels([0,100])
    axb.legend(loc='upper right')
    
    Qobs_stat = select_period(Qobs,2003,2003)
    Qmod_stat = select_period(Qmod,2003,2003)
    
    import hydroeval as he
    NSE = he.evaluator(he.nse, Qmod_stat, Qobs_stat)[0]
    NSElog = he.evaluator(he.nse, Qmod_stat, Qobs_stat, transform='log')[0]
    RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qmod_stat.values)**2))
    KGE = he.evaluator(he.kge, Qmod_stat, Qobs_stat)[0][0]
    print(model_name.upper())
    print('NSE',round(NSE,2))
    print('NSElog',round(NSElog,2))
    print('RMSE',round(RMSE,2))
    print('KGE',round(KGE,2))
    
    ax = a1
    ax.scatter(Qobs_stat, Qmod_stat, s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
    ax.set_xlim(1,500)
    ax.set_ylim(1,500)
    ax.set_xlim(0.1,300)
    ax.set_ylim(0.1,300)
    
    ax.set_xlabel('$Q_{obs}$ / A [mm/week]', fontsize=12)
    ax.set_ylabel('$Q_{sim}$ / A [mm/week]', fontsize=12)

    fig.tight_layout()

#%% PLOT PIEZOMETRY

area = int(round(BV.geographic.area))

# Qobs_path = data_path + 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'
# Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
# date = pd.to_datetime(Qobs[0]+' '+Qobs[1], format="%d/%m/%Y %H:%M:%S")
# Qobs.index = date
# Qobs = Qobs[2].to_frame(name="Q")
# Qobs = Qobs / 1000 # L/d to m3/d
# Qobs = (Qobs / (area*1000000)) # m3/d to m/day
# Qobs = Qobs.resample('W').mean()
# # Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month
# # Qobs = select_period(Qobs, 2003, 2003)
# Qobs = Qobs * 7 * 1000

simul_list = sorted(glob.glob(os.path.join(calibration_folder,vers+'*')), key=os.path.getmtime)

for i, simul in enumerate(simul_list[:]):
    

    model_name = os.path.split(simul)[-1]

    Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    
    Rmod = Smod['recharge'] * 7 * 1000
    
    WTEmod = Smod['watertable_elevation']
    WTDmod = Smod['watertable_depth']

    fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(12,3.5), dpi=300)

    ax = a0
    # ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
    # ax.fill_between(Omod.index, Omod, Qmod, color='red', lw=1, label='Simualted : outflow + runoff', alpha=0.5)
    ax.plot(WTDmod, color='red', lw=2, label='Simulated: watertable')
    # ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
    ax.set_xlabel('Date')
    ax.set_ylabel('WT depth [m]')
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
    ax.legend(loc='upper left')
    ax.set_title(model_name.upper(), fontsize=10)
    ax.set_ylim(0,None)
    ax.invert_yaxis()

    axb = ax.twinx()
    axb.bar(Rmod.index, Rmod, color='dodgerblue', width=10, edgecolor='None', lw=0, alpha=1, label='Recharge')
    axb.set_ylim(0,100)
    axb.invert_yaxis()
    axb.set_yticklabels([0,100])
    axb.legend(loc='upper right')
    
#%% MODPATH

BV.settings.update_input_particles(
                                # zone_partic = tif_file_clip,
                                # zone_partic = BV.geographic.watershed_box_buff_dem,
                                zone_partic = os.path.join(BV.calibration_folder, model_name, '_postprocess/_rasters','seepage_areas_t(0).tif'),
                                cell_div = 1, # 1
                                zloc_div = False,  # or False, add cells at cell bottom
                                bore_depth = None, # '[0,5,10] for 3 particles or None
                                track_dir = 'backward',
                                # track_dir = 'forward', # backward
                                sel_random = None, # or int
                                sel_slice = None, # or int
                                )

model_modpath = BV.preprocessing_modpath(model_modflow, for_calib=True)
success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

BV.postprocessing_modpath(model_modpath,
                      ending_point=True,
                      starting_point=True,
                      pathlines_shp=True,
                      particles_shp=True,
                      random_id=None, # select randomly to save (for pathlines and particles)
                      ) # None

BV.filtprocessing_modpath(model_modpath,
                      norm_flux=True, # for forward only
                      filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                      filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                      filt_inout=True, # delete particles in and out in the same cell (first layer)
                      calc_rtd=False, # compute residence time distribution
                      random_id=None, # select randomly to keep
                      ) # None

#%% PLOT AGE



#%% MT3DMS

mf = flopy.modflow.Modflow.load(calibration_folder+model_name+'/'+model_name+'.nam')

nper = mf.nper

bin_path = root_dir + '/bin/win/'

model_name_mt = model_name + '_mt'

## RUN MT3DMS ##
mt = flopy.mt3d.Mt3dms(modflowmodel=mf, modelname=model_name_mt, version='mt3d-usgs',
                       model_ws=model_modflow.full_path,
                       exe_name=bin_path+'mt3d-usgs_1.1.0_64.exe',
                       ftlfilename='mt3d_link.ftl', namefile_ext='mtnam', verbose=False, ftlfree=False)

gcg = flopy.mt3d.Mt3dGcg(mt, mxiter=10,
                         # cclose=1e-7,
                         # iter1=1000
                         )

new_stepsize = 1

# timprs=[]
# for i in range(1,mf.nper*new_stepsize+1):
#     timprs.append(i)

timprs = [mf.nper]

ssflag = ['True']   # This one is for the transport simulation (STEADY FOR THE FIRST PERIOD)
for i in range(mf.nper*new_stepsize):
    ssflag.append(' ')  
    
btn = flopy.mt3d.Mt3dBtn(mt,
                         nlay=mf.nlay,
                         nrow=mf.nrow,
                         ncol=mf.ncol,
                         laycon=1,
                         # nper=mf.nper*new_stepsize+1,
                         nper=mf.nper,
                         ncomp=1,
                         mcomp=1,
                         Legacy99Stor=True,
                         NoWetDryPrint=True,
                         # OmitDryBudg=True,
                         MFStyleArr=True,
                         delr=model_modflow.resolution,
                         delc=model_modflow.resolution,
                         prsity=model_modflow.sy,
                         sconc=50,
                         nstp=model_modflow.nstp,
                         tsmult=1,
                         # nprs=mf.nper*new_stepsize+1,
                         nprs=mf.nper,                        
                         timprs=timprs,
                         obs=None,
                         ssflag=ssflag,
                         nprmas=0,
                         perlen=model_modflow.perlen,
                         savucn=True,
                         species_names='NO3',
                         DRYCell=True,
                         chkmas=False, # True ?
                         thkmin=0.01,
                         # icbund=1,
                         # nprobs = 10,
                         cinact=1e30,
                         unitnumber=None,
                         tunit='D', lunit='M', munit='KG',
                         )
                         #, thkmin=0.0001/(delv/nlay))    

# ADVECTION PACKAGE
adv = flopy.mt3d.Mt3dAdv(mt,
                         mixelm=-1,
                         # percel=0.75
                         )
    # Solution method (mixelm)
    # • Finite Difference Method (FDM)
    # • MOC : Method of Characteristics (MOC)
    # • MMOC : Modified Method of Characteristics (MMOC)
    # • HMOC : Hybrid Method of Characteristics (HMOC)
    # • TVD (MIXELM = -1 - try to use this one)

# DISPERSION PACKAGE
# mt3d.mtdsp.Mt3dDsp(mt,
#                    al=0,
#                    trpt=1,
#                    trpv=1,
#                    dmcoef=0,
#                    extension='dsp') # Not used for the moment
disp = flopy.mt3d.mtdsp.Mt3dDsp(mt,
                   al=10,
                   trpt=0.1, # ratio of the horizontal transverse dispersivity to the longitudinal dispersivity, 10x moins
                   trpv=0.01, # ratio of the vertical transverse dispersivity to the longitudinal dispersivity, 100x moins
                   dmcoef=1e-5,
                   extension='dsp') # Not used for the moment

# REACTIVITY = DENITRIFICATION
# Denit_Rate = np.array([0.5, 1, 1.5, 2, 4, 6, 10, 15, 20, 40, 100])      # Denitrification rate [yr]    
Denit_Rate = np.array([1])      # Denitrification rate [yr]
# Denit_Rate = 1 / (Denit_Rate*12)    # Denitrification rate [1/month]
Denit_Rate = 1 / (Denit_Rate)
# Denit_Rate[-1] = 0  # We put no denitrification to replace the last value
NO3reac = Denit_Rate
lambdaNO3 = NO3reac/new_stepsize

rct = flopy.mt3d.mtrct.Mt3dRct(mt,
                               isothm=0, # no sorption is simulated
                               ireact=1, # ireact=100  for zero order
                               igetsc=0, # 0 : the initial concentration for the sorbed or immobile phase is not read
                               rhob=None,
                               rc1=lambdaNO3[0], # (unit, T-1)
                               )

# SSM PACKAGE
Input_Conc_new=np.zeros(mf.nper*new_stepsize)
RechargeNO3Conc_model = np.zeros(mf.nper)
# RechargeNO3Conc_model[:25] = RechargeNO3Conc_model[:25]+50
# RechargeNO3Conc_model[25:] = RechargeNO3Conc_model[25:]*0
RechargeNO3Conc_model[:] = RechargeNO3Conc_model[:]+50
for iper in range(nper):
    Input_Conc_new[iper*new_stepsize:(iper+1)*new_stepsize] = RechargeNO3Conc_model[iper]
    
crch = {}
# crch[0]=50
crch[0] = np.ones((mf.nrow,mf.ncol))*50
for step in range(nper*new_stepsize):
    # crch[step+1] = Input_Conc_new[step]
    crch[step+1] = np.ones((mf.nrow,mf.ncol))*Input_Conc_new[step]
    # crch[step+1][0:70,:] = crch[step+1][0:70,:]*2

# ssm_data = {}
# itype = flopy.mt3d.Mt3dSsm.itype_dict()
# [K,I,J,CSS,iSSType] = layer, row, column, source concentration, type of sink/source: well-constant concentration cell 
# # print(itype)
# ssm_data[0] = [(0, wrow, wcol, 10.0, itype['WEL'])]
# # ssm_data.append((0, wrow1, wcol1, Q1, itype['WEL']))
# ssm = flopy.mt3d.Mt3dSsm(mt, stress_period_data=ssm_data)
ssm = flopy.mt3d.Mt3dSsm(mt,
                         crch=crch,
                         # mxss=mf.nrow*mf.ncol*(nper*new_stepsize+1)+10,
                         mxss=None,
                         stress_period_data=None)

# RUN MT3D
mt.write_input()
success2, mtoutput = mt.run_model(silent=not True, pause=False, normal_msg='normal termination')
   
## Return results: streamflow, river concentration, hydraulic heads (4D array) and GW concentration (4D array)
## And compute criterias

#%% PLOT CONCENTRATION

ucnobj  = bf.UcnFile(model_modflow.full_path + '/' + 'MT3D001.ucn')
concobj_1c = ucnobj.get_alldata(mflay=None) # 4D:[time, lay, row, col]

concobj_1c_fil = concobj_1c.copy()
concobj_1c_fil[concobj_1c_fil==1e30] = np.nan

# test=concobj_1c_fil[0][3]
# plt.imshow(test)
# plt.colorbar()

times = ucnobj.get_times() # simulation time
mytime = times[8] # the last simulation time
conc = ucnobj.get_data(totim=mytime)
conc[conc==1e30] = np.nan

# for the_time in range(len(concobj_1c_fil)):
    
#     try:
#         seep = imageio.imread(os.path.join(simul, r'_postprocess/_rasters/outflow_drain_t('+str(int(the_time))+').tif'))
#     except:
#         pass
    
#     # the_time = 5
#     conc_plt = concobj_1c_fil[the_time][0]
#     conc_plt[seep<=0] = np.nan
    
#     fig = plt.figure(figsize=(10,10))
#     ax = fig.add_subplot(1, 1, 1, aspect='equal')
#     modelmap = flopy.plot.map.PlotMapView(ax=ax, model=mf)
#     # lc = modelmap.plot_grid() # grid
#     cs = modelmap.plot_array(conc_plt, ax=ax, cmap='jet',
#                               norm = mcolors.LogNorm(vmin=0.1, vmax=50)
#                              ) # head contour
#     # plt.plot(wpt[0],wpt[1],'ro')
#     ax.set_title('C  %g week' % the_time)
#     divider = make_axes_locatable(ax)
#     cax = divider.new_vertical(size='5%', pad=0.6, pack_start = True)
#     fig.add_axes(cax)
#     fig.colorbar(cs, cax = cax, orientation = 'horizontal', label='[NO3]')
#     fig.tight_layout()

fig, ax = plt.subplots(1,1, figsize=(7,5), dpi=300)
for i in range(len(concobj_1c_fil)):
    the_time=i
    try:
        # seep = imageio.imread(os.path.join(simul, r'_postprocess/_rasters/outflow_drain_t('+str(int(the_time))+').tif'))
        seep = imageio.imread(os.path.join(simul, r'_postprocess/_rasters/outflow_drain_t('+str(int(0))+').tif'))
    except:
        pass
    # xi = concobj_1c_fil[i][0]
    conc_plt = concobj_1c_fil[the_time][0]
    # conc_plt[seep<=0] = np.nan
    xi = conc_plt.copy()
    ax.scatter(i, np.nanmax(xi), color='k', label='Rate decay: 1/10 years')
    ax.set_xlabel('Time')
    ax.set_ylabel('[NO3]')
    ax.set_title('Time 0: steady-state - Injection with rehcarge', fontsize=10)
    if i==0:
        ax.legend(loc='upper right')
    
# list_to_plot = np.arange(0,len(concobj_1c_fil),1)
# for i in list_to_plot:
#     print(i)
#     fig, ax = plt.subplots(1,1, figsize=(8,8), dpi=300)
#     ax.set_title('Time : '+ str(i))
#     xi = concobj_1c_fil[i][0]
#     # norm = mcolors.Normalize(vmin=0, vmax=50)
#     norm = mcolors.LogNorm(vmin=0.1, vmax=100)
#     sm = cm.ScalarMappable(cmap='jet', norm=norm)
#     sm.set_array([])    
#     dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')    
#     rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, xi), 
#                                   ax=ax, transform=dem.transform,
#                                   cmap='jet', alpha=0.5, zorder=-5,
#                                   # vmin=0, vmax=10,
#                                   norm=norm
#                                   )    
#     shp_bv = gpd.read_file(BV.geographic.watershed_shp)
#     shp_hydro = gpd.read_file(BV.hydrography.streams)    
#     shp_bv.plot(ax=ax, facecolor='None', lw=3)
#     shp_hydro.plot(ax=ax, color='navy', lw=2)
#     divider = make_axes_locatable(ax)
#     cax = divider.new_vertical(size='5%', pad=0.6, pack_start = True)
#     fig.add_axes(cax)
#     fig.colorbar(sm, cax = cax, orientation = 'horizontal', label='[NO3]')
#     fig.tight_layout()
    
#     fig.savefig(calibration_folder+'_figures/'+'V0'+'_'+str(i)+'_'+model_name+'.png', dpi=300, bbox_inches='tight')
                    
#     plt.close()

# gif = True                   
# if gif == True:
#     begin_by = calibration_folder+'_figures/'+'V0'
#     filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
#     images = []
#     for filename in filenames:
#         images.append(imageio.imread(filename))
#     gif_name = 'V0'
# imageio.mimsave(calibration_folder+'_figures/'+gif_name+'.gif', images, duration=0.5, loop=0, format='GIF-PIL')
    
### USEFUL LINKS
# https://www2.hawaii.edu/~jonghyun/classes/S18/CEE696/files/11_flopy_mt3dms_transport_modeling.pdf
# https://download.feflow.com/html/help72/feflow/09_Parameters/Auxiliary_Data/peclet_number.html
# https://flopy.readthedocs.io/en/3.4.2/Notebooks/mt3dms_examples.html#

#%% PLOT DECAY

import numpy as np
import matplotlib.pyplot as plt

# Paramètres
time = np.linspace(0, 100, 1000)  # Temps en années, de 0 à 10 ans
C0 = 50  # Concentration initiale en mg/L
rates = [1/1, 1/5, 1/10, 1/30, 1/100]  # Taux de dégradation en 1/an

# Calcul de la concentration pour chaque taux de dégradation (modèle de dégradation de premier ordre)
def first_order_reaction(C0, rate, time):
    return C0 * np.exp(-rate * time)

# Création du graphique
plt.figure(figsize=(10, 6))

# Tracer la courbe pour chaque taux de dégradation
for rate in rates:
    concentration = first_order_reaction(C0, rate, time)
    plt.plot(time, concentration, label=f"Rate = {1/rate}y"+'   -   '+str(round(rate,2))+'y⁻¹')

# Ajout des labels et titre
plt.title("Dégradation des Nitrates (Réaction de Premier Ordre) au Cours du Temps")
plt.xlabel("Temps (années)")
plt.ylabel("Concentration en Nitrates (mg/L)")
plt.legend(title="Taux de dégradation (y⁻¹)")
plt.xlim(0,100)
plt.grid(True)
# plt.xscale('log')

# Affichage du graphique
plt.show()


#%% ---- NOTES
