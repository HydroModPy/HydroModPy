#%% LIBRARIES MODULES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
import glob
import geopandas as gpd
from shapely.geometry.polygon import LineString, Polygon
from shapely.ops import linemerge, unary_union, polygonize
from datetime import datetime
import os
import re
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math
import seaborn as sns
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import rasterio
import fnmatch
import matplotlib.dates as matdates

# Gis
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                 
#%HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% WATERSHED MODEL

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/"
# Path where the results will be stored
out_path = "D:/Users/abherve/HYSTERESIS/"

dems_path = data_path + 'DEM/France/' # reginal DEM or conceptual DEM
shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = data_path + 'SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

surfex_path =  data_path + 'CLIMATE/FRANCE/SURFEX/Rennes/' # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'GEOLOGY/France/Layer/' # add geologic layers
oceanic_path = data_path + 'OCEANIC/' # add specific sea level files
hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/' # add hydrographic shapefiles
hydrometry_path = data_path + 'HYDROLOGY/France/Hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'HYDROLOGY/France/Intermittency/' # add intermittency data for automatic download
piezometry_path = False # add piezometry data for automatic download
subbasin_path = False # generate subbasins from stations or manual points

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates

watershed_name = 'Cheze' # search the name in watershed_library or just label your result folder
print('##### '+watershed_name.upper()+' #####')

dem_name = "BDALTI_bzh_75m.tif" # name of dem
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

types_obs = ['streams_fr','sections_bzh'] # list of shapefile name layers for clip hydrology
fields_obs = ['FID', 'Persistanc'] # list of shapefile name columns to translate as a tif

# Depending on the choices
dem_path = dems_path + dem_name

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
load = True

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              cell_size=cell_size)

if load != True :
    BV.add_surfex(surfex_path) 
    BV.add_geology(geology_path) 
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    BV.add_oceanic(oceanic_path)
    BV.add_hydrometry(hydrometry_path)
    BV.add_intermittency(intermittency_path)
    if piezometry_path == True:
        BV.add_piezometry()
    if subbasin_path == True:
        BV.add_subbasin()

# watershed_display.watershed_dem(BV)
# watershed_display.watershed_local(dem_path, BV)

#%% PARAMETERS MODEL

# Input recharge
var = 'REC'
mod = 'REA'
sce = 'historic'
typ = 'test1' # sinu / hist / proj

# Choice temporal of the simulation
sim_state = 'transient' # 'steady' or 'transient'
period = [1990,1995] # rehcarge period
first = period[0]
last = period[1]
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
start = str(period[0])+'-01-01' # necessary to specify the first time_step date

# Active of not modules
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = False # run modpath particle tracking if True
verbose = False # add print of MODFLOW in console
post_process = False # print time_step

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth
thick = 30 # m

# Hydraulic properties
Koptim = 2e-5

# Ks = np.array([Koptim/10,Koptim,Koptim*10]) * 3600 * 24 # m/second to m/month
# Sys = [0.1,0.01,0.001]

Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/month
Sys = [0.06]

#%% RUN MODEL

list_model_name = []
list_of_success = []
list_flow_model = []

compt = 1
# Update properties
for Sy in Sys:
    for K in Ks:
        # K = 1e-5
        # Sy = 0.01
        # print(K)
        BV.hydrodynamic.update_thickness(thick)
        BV.hydrodynamic.update_hyd_cond(K) 
        BV.hydrodynamic.update_porosity(Sy)
        
        # BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
        #                                   first_year = first, last_year = last, 
        #                                   time_step = time_step, sim_state=sim_state)
        # BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        # plt.plot(BV.forcing.recharge)
        
        BV.forcing.update_effppt_surfex(clim_mod = mod, clim_sce = sce,
                                        first_year = first, last_year = last, 
                                        time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        # plt.plot(BV.forcing.recharge)
                    
        date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
        date_today = date_today.replace('/','-')
        date_today = date_today.replace(':','-')
        date_today = date_today.replace(' ','_')
        
        model_name = typ+'_'+str(compt)+'_'+\
                     var+'-'+mod+'-'+sce+'_'+\
                     str(round(Sy*100,2))+';'+str(round(K,2))+';'+str(thick)+'_'+\
                     str(first)+'-'+str(last)
        
        # Run model
        try:
            print('SIM - ' + model_name)
            success, flow_model = BV.run_modflow(ident=model_name,
                                                modpath_sim=modpath_sim,
                                                sink_fill=sink_fill,
                                                box=box,
                                                lay_number=lay_number,
                                                bottom=bottom,
                                                thick_exp=thick_exp,
                                                cond_decay=cond_decay,
                                                verbose=True,
                                                post_process=post_process,
                                                time_step=time_step)
            if success == True:
                print(     'Success')
            else:
                print(     'Error')
        except:
            pass
        list_model_name.append(model_name)
        list_of_success.append(success)
        list_flow_model.append(flow_model)
        compt+=1
        
print(list_of_success)
                 
# BV.list_flow_model = list_flow_model
# BV.list_of_success = list_success
# BV.save_object()
        
# POSTPROCESS MODEL

for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
        
    if success==True:
        
            BV.matrix_modflow(success,
                              flow_model,
                              first_only = True,
                              watertable_elevation = True,
                              watertable_depth = True, 
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = False,
                              specific_discharge = False,
                              accumulation_flux = False,
                              perenn_intermit = False,
                              verbose = True,
                              export_tif = True)
            
            # # Extract results
            BV.results_modflow(ident=model_name,
                               actual_date=actual_date,
                               start=start,
                               time_step=time_step)
            
            # Plot maps
            # save_gif = False # save a gif after plots
            # surf = modflow_display.SurfaceOutputs(Rech, simulations_folder, stable_folder, model_name, 
            #                                       types_obs, save_gif=save_gif, first_only=True,
            #                                       outflow=True, accflux=True, intermittency=True, 
            #                                       chronics=True, sim_state=sim_state)

#%% FAST PLOT FOR ETR

obs_path = "D:/Users/abherve/HYSTERESIS/_data/Hydrometric_J7364220_La Chèze à Plélan-le-Grand [L'Enlevrier]_273631-2343510_9.3_88_1989-2021.csv"

dem_data = imageio.imread(stable_folder+'geographic/watershed_dem.tif')
area = toolbox.basin_area(dem_data, dem_data, '<=', -1000, 75)

scan = 'outflow_drain'

# ks = [koptim/100,koptim/10,koptim,koptim*10,koptim*100]
# sys = [0.0005,0.001,0.01,0.1,0.5]

BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                  first_year = first, last_year = last, 
                                  time_step = time_step, sim_state=sim_state)

compt=0

simul_list = glob.glob(simulations_folder+'*'+typ+'*'+sce+'*')
for simul in simul_list:
    model_name = simul.split('\\')[-1]
    
    Sy = float(model_name.split('_')[3].split(';')[0]) # %
    K = float(model_name.split('_')[3].split(';')[1]) / 24 / 3600 # m/s
    E = float(model_name.split('_')[3].split(';')[2]) # m
    D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
    params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
    Smod_path = simul+'/_watershed/_simulated_results.csv'            
    if not os.path.exists(Smod_path):
        compt += 1
        continue
    
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    outflow = Smod.outflow_drain * 30 * 1000 
    rec_pe_pos = BV.forcing.pe_pos * 30 * 1000
    rec_pe_neg = BV.forcing.pe_neg * 30 * 1000
    rec_surfex = BV.forcing.recharge * 30 * 1000

    fig, ax = plt.subplots(1,1,figsize=(8, 5))
    myFmt = DateFormatter("%Y")
    myLoc = matdates.YearLocator(1)
    
    ax.plot(rec_surfex, c='k', lw=2, label='REC SURFEX')
    ax.plot(rec_pe_pos, c='dodgerblue', lw=2, label='P-E > 0')
    ax.plot(rec_pe_neg, c='forestgreen', lw=2, label='P-E < 0')
    plt.plot(outflow, c='red', lw=2, label='discharge simulated')
    
    obs_data = pd.read_csv(obs_path, sep=';', parse_dates=True, index_col=0) # sep='\s+'
    obs_data = obs_data.resample('M').mean()
    obs_data = obs_data * 24 * 3600 * 30 * 1000  # mm/month
    obs_data['disch_norm'] = obs_data['Q'] / (area * 1000000)
    obs_data = obs_data[(obs_data.index.year>=first) & (obs_data.index.year<=last)]
    ax.plot(obs_data.disch_norm, c='darkorange', lw=2, label='discharge observed')
    
    ax.xaxis.set_major_formatter(myFmt)
    ax.xaxis.set_major_locator(myLoc)
    ax.legend(bbox_to_anchor=(1.32,0.75), bbox_transform=ax.transAxes)
    label = 'K='+str("{:.2e}".format(K))+'m/s'+' - '+'n='+str(Sy)+'%'+' - '+'D='+str("{:.2e}".format((K*E)/Sy))+'m²/s'
    ax.set_title(label)
    
    # ax.set_yscale('log')
    
#%%
"""
# plt.plot(df.recharge)
# plt.plot(df.outflow_drain)

x = pd.read_csv('D:/Users/abherve/HYSTERESIS/Cheze/results_stable/climatic/_ALL_D.csv',
                sep=';', parse_dates=True, index_col=0)
x = x[(x.index.year>=1990) & (x.index.year<2000)]
x = x.resample('M').sum()
# plt.plot(x['PPT_REA_historic'])
plt.plot(x['EFF_REA_historic'])
plt.plot(x['REC_REA_historic'])
# plt.plot(x['ETP_REA_historic'])
"""
