# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan
"""

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
# import seaborn as sns
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates
import flopy
import random
import pickle

# Plot
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
import earthpy.spatial as es
import earthpy.plot as ep

# Gis
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                 
#%HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root, calib_analysis, calib_basis

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

#%% ---- CATCHMENT

#%% PATH WATERSHED

# user = 'Clement'
user = 'Ronan'

if user == 'Clement':
    dem_name = "BDALTI_25M_09_MERGED.tif" # name of dem 
    #dem_name = 'BDALTI_09_75m.tif'
    #############################################################
    git_path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = os.path.join("D:/GoogleDrive/1.TRAVAIL/PYTHON/FLOPY/_data/")
    # Path where the results will be stored
    out_path = os.path.join("D:/GoogleDrive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_out/")
    # Figure folder outputs
    figsim_folder = os.path.join("D:/GoogleDrive/1.TRAVAIL/PYTHON/FLOPY/_figures/")
    #############################################################
    
if user == 'Ronan':
    # dem_name = 'BDALTI_09_75m.tif'
    dem_name = 'BDALTI_09_25m.tif'
    #############################################################
    git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/"
    # Path where the results will be stored
    out_path = "C:/Users/ronan/Documents/SIMULATIONS/LASSET/"
    # Figure folder outputs
    # figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures2/_outputs/'
    fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/LASSET/figures/v2/"
    path_obs = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/LASSET/data/"
    #############################################################

dems_path = data_path + 'DEM/France/' # reginal DEM or conceptual DEM
# shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = data_path + '/SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

surfex_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/CLIMATE/France/SURFEX/Midi-Pyrenees/rea/" 
              # add surfex models in .h5 format (France scale, else, specify None)
drias_path = data_path + 'DRIAS/Lasset/from_ronan/'
geology_path = data_path + 'GEOLOGY/France/Layer/' # add geologic layers
oceanic_path = data_path + 'OCEANIC/' # add specific sea level files
hydrology_path = data_path + 'HYDROLOGY/' # add hydrographic shapefiles
hydrometry_path = data_path + 'HYDROMETRY/' # add hydrometry data for automatic download
intermittency_path = data_path + 'HYDROLOGY/France/Intermittency/' # add intermittency data for automatic download
piezometry_path = False # add piezometry data for automatic download
subbasin_path = False # generate subbasins from stations or manual points

# dem_name = "BDALTI_25M_09_MERGED.tif" # name of dem
# dem_name = "BDALTI_09_75m.tif"

from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

from_xy = []
# Depending on the choices
dem_path = dems_path + dem_name

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates
# watershed_names = ['Pompage'] # search the name in watershed_library or just label your result folder

watershed_names = ['Lasset_decay']
code_names = ['?']

#%% GENERATE WATERSHED

load = True

for watershed_name in watershed_names[:]:

    print('##### '+watershed_name.upper()+' #####')

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  modflow_path=modflow_path,
                                  library_path=library_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xy=[601020,6193860,100,50],
                                  cell_size=cell_size)
    
    # watershed_display.watershed_dem(BV)
    # watershed_display.watershed_local(dem_path, BV)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
#%% DATA WATERSHED

#% Merger les points shp
# pt_streams = hydrology_path + 'stream_digit_pt.shp'
# pt_zh = hydrology_path + 'zh_digit_pt.shp'
# merge_path = pt_streams+';'+pt_zh
# pt_zhstreams = hydrology_path + 'zhstreams_pt.shp'
# wbt.merge_vectors(merge_path, pt_zhstreams)

from watershed import watershed_root, watershed_display, forcing

if user == 'Ronan':
    hydrology_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/LASSET/data/" # add hydrographic shapefiles
    
    wbt.vector_lines_to_raster(hydrology_path+'lasset_stream_perennial_update_april23_cut.shp',
                               hydrology_path+'lasset_stream_perennial_update_april23_cut.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    wbt.raster_to_vector_points(hydrology_path+'lasset_stream_perennial_update_april23_cut.tif',
                                hydrology_path+'lasset_stream_perennial_update_april23_cut_topt.shp')
    wbt.vector_polygons_to_raster(hydrology_path+'lasset_wetlands_perennial_cut.shp',
                                  hydrology_path+'lasset_wetlands_perennial_cut.tif',
                                  base = stable_folder+'geographic/'+'watershed_dem.tif')
    wbt.raster_to_vector_points(hydrology_path+'lasset_wetlands_perennial_cut.tif',
                                hydrology_path+'lasset_wetlands_perennial_cut_topt.shp')

    merge_path = hydrology_path+'lasset_stream_perennial_update_april23_cut_topt.shp'+\
                 ';'+\
                 hydrology_path+'lasset_wetlands_perennial_cut_topt.shp'
    wbt.merge_vectors(merge_path, hydrology_path+'lasset_stream_update_april23_wetlands_perennial_cut_topt.shp')
    
    # types_obs = ["lasset_stream_perennial_update_april23"] # shapefile cours d'eau
    # types_obs = ["lasset_stream_wetland_perennial_pt_gpdv2"] # shapefile cours d'eau
    # types_obs = ["lasset_stream_perennialv2"]
    types_obs = ["lasset_stream_update_april23_wetlands_perennial_cut_topt"]
    
if user=='Clement':
    #types_obs = ["lasset_stream_perennialv2"]
    hydrology_path = data_path + 'HYDROLOGY/' # add hydrographic shapefiles
    types_obs = ["lasset_stream_wetland_perennial_pt_gpdv2"] # shapefile cours d'eau

#types_obs = ['streams'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid'] # list of shapefile name columns to translate as a tif
BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
BV.add_forcing()
BV.add_hydrodynamic()
BV.add_oceanic(oceanic_path)

# # Measurements
# BV.add_hydrometry(hydrometry_path)
# BV.add_intermittency(intermittency_path)
# BV.add_piezometry()

# # Zones
# BV.add_subbasin()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

area = BV.geographic.area

if not os.path.exists(stable_folder+'/climatic/_REC_D.csv'):
    BV.add_surfex(surfex_path)
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2019, time_step = 'D',
                                  sim_state='steady') #
R_rea = BV.forcing.recharge

#%% ---- MODELING DICHOTOMY

#%% DICHOTOMY PARAMS

######################
# dicot_name = 'egu1'
# dicot_name = 'oneplot'
dicot_name = 'explor1'
######################

# 12 cases :
    # 1 constant aquifer - homogeneous
    # 1 flat aquifer - homogeneous
    # 10 flat aquifer - exponential decay

# Option
sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = False # run modpath particle tracking if True
run = True

# Input recharge
time_step = 'D' # or 'D'
actual_date = False # False if date is conceptual

# Active of not modules
box = True # if True generate a rectangular model
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process

# Recharge
init_rech = None
recharge = 500 / 1000 / 365
BV.forcing.update_recharge(recharge, sim_state=sim_state) #

# Porosity
Sy = 0.01 # Default

# Vertical
verti_k = None # "k1", or None

# Aquifer thickness
thick = 50 # m

# Discretization
nlay = 25 # vertical diSscrtization
thick_exp = 1.25 # exponential decay of nlay with depth

# HK
KR = 3
K0 = KR * recharge
# print(K0/24/3600)
    
# Aquifer bottom
list_bottom = [None, 0] # aquifer flat or not
list_bottom.extend([0] * 10)

# Hk decay # exponential decay of K with depth : 0.02
# list_cond_decay = [0, 0]
# list_cond_decay.extend(np.geomspace(1/10, 1/300, 10))

list_d_values = [0, 0]
list_d_values.extend(np.geomspace(10, 300, 10).round(0).astype(int))
print(list_d_values)
list_d_values = [0, 0, 10, 15, 20, 30, 45, 65, 100, 140, 205, 300]
list_cond_decay = list(1/np.array(list_d_values))
list_cond_decay[0] = 0
list_cond_decay[1] = 0

### PARAMETER INITIALIZATION DICHOTOMY

BV.hydrodynamic.update_nlay(nlay) # 1
BV.hydrodynamic.update_thick_exp(thick_exp) # 1
BV.hydrodynamic.update_thickness(thick) # 30 / intervient pas si bottom != None
BV.hydrodynamic.update_porosity(Sy)
BV.hydrodynamic.update_hyd_cond(K0)

# params_file = 'calib_dicot_hom_1v_k1'+'/'+dicot_name
params_file = 'calib_dicot_hom_1v_k1'+'_'+dicot_name

#%% DICHOTOMY LAUCNH

cp = 0

for cond_decay, bottom in zip(list_cond_decay[:], list_bottom[:]):
    
    if np.isin(cp, range(10)):
        params_df = pd.DataFrame(columns=['params',
                                          'init_values',
                                          'lower_bounds',
                                          'higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1',
                            '?',
                            1e-9 * 24 * 3600, # 1e-9
                            1e-5 * 24 * 3600,  # 1e-5                  
                            'm/j',
                            'lin']
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
        calib = calib_root.Calibration(params_file, BV, observations = ['streams'])    
    
    if np.isin(cp, [10,11]):
        params_df = pd.DataFrame(columns=['params',
                                          'init_values',
                                          'lower_bounds',
                                          'higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1',
                            '?',
                            1e-10 * 24 * 3600, # 1e-9
                            1e-6 * 24 * 3600,  # 1e-5                  
                            'm/j',
                            'lin']
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
        calib = calib_root.Calibration(params_file, BV, observations = ['streams'])    
    
    print(cp)
    print(cond_decay, bottom)

    BV.hydrodynamic.update_cond_decay(cond_decay) # 0
    BV.hydrodynamic.update_bottom(bottom) # 0

    # BV.hydrodynamic.update_porosity(0.01)
    # BV.hydrodynamic.update_hyd_cond(2)
    # BV.hydrodynamic.update_nlay(1)
    # BV.hydrodynamic.update_thickness(300)
    # BV.hydrodynamic.update_bottom(-100)
    # BV.hydrodynamic.update_cond_decay(0)
    # BV.hydrodynamic.update_thick_exp(1.25)
    
    """
    dicot = calib.dichotomy(gap=1)
    """
    
    cp +=1
    
#%% DICHOTOMY POSTPROCESS

df = pd.DataFrame(np.nan, index=range(1), columns=['cond_decay',
                                                   'bottom',
                                                   'k',
                                                   'kr',
                                                   'ind',
                                                   'Dos',
                                                   'Dso'])
typ_calib = 'streams_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)[:]
compt = 0
for path_value, cond_decay_value, bottom_value in zip(list_path, list_cond_decay, list_bottom):
    print(path_value)
    name_file = path_value.split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    test.display_objective_function(save=None)
    koptim = test.calib['params_values'][-1]
    kr = koptim / test.calib['recharge']
    obj_func = test.calib['objective_function'][-1]
    df.loc[compt,'cond_decay'] = cond_decay_value
    # df.loc[compt,'thick_decay'] = 1/cond_decay_value
    df.loc[compt,'bottom'] = bottom_value
    df.loc[compt,'k'] = koptim #/ 24 / 3600
    df.loc[compt,'kr'] = kr
    df.loc[compt,'ind'] = obj_func
    # (np.log(self.mean_sim_to_obs/self.mean_obs_to_sim))**2
    df.loc[compt,'Dos'] = test.data_obs['streams'][-1]
    df.loc[compt,'Dso'] = test.data_sim['streams'][-1]

    compt += 1
    
df.to_csv(BV.calibration_folder+'/'+dicot_name+'_'+watershed_name+'.csv', sep=';')

#%% ---- MODELING POROSITY

#%% POROSITY PARAMS

# K_cal = df.loc[df['Dabs'].idxmin()].k * 24 * 3600
# cond_decay_cal = df.loc[df['Dabs'].idxmin()].cond_decay

df = pd.read_csv(BV.calibration_folder+'/'+dicot_name+'_'+watershed_name+'.csv', sep=';')

######################
typ = 'explor1'
######################

box=True
modpath_sim = True
zone_partic = 'watershed_box_buff' # watershed or watershed_buff
zone_partic = 'watershed' # watershed or watershed_buff
zone_partic = 'domain' # watershed or watershed_buff
sink_fill=False
verbose=True,
post_process=False,
init_rech=None
verti_k=None

date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
date_today = date_today.replace('/','-')
date_today = date_today.replace(':','-')
date_today = date_today.replace(' ','_')

list_cond_decay = list(df['cond_decay'].values)
list_bottom = list(df['bottom'].values)
list_bottom[0] = None
list_koptim = list(df['k'].values)

# list_porosity = np.logspace(np.log10(0.001), np.log10(0.3), 10)
# list_porosity = np.geomspace((0.001), (0.3), 10)
list_porosity = np.geomspace((0.003), (0.3), 10).round(3)

# Label
list_model_name = []
list_of_success = []
list_flow_model = []

# Update properties
BV.hydrodynamic.update_nlay(25) # 1
BV.hydrodynamic.update_thick_exp(1.25) # 1
BV.hydrodynamic.update_thickness(50) # 30 / intervient pas si bottom != None

#%% POROSITY LAUNCH

typ = 'explor1'

run = True

# list_cond_decay = [0.002]
# list_bottom[0] = 0

# c = 0
compt_model = 0

for cond_decay_cal, bottom_cal, koptim_cal in zip(list_cond_decay[:], list_bottom[:], list_koptim[:]):
# for cond_decay_cal, bottom_cal, koptim_cal in zip([0.0033333333333333, 0.0033333333333333], [0,0], [list_koptim[-1:][0],list_koptim[-1:][0]]):
# for cond_decay_cal, bottom_cal, koptim_cal in zip([1/300], [0], [0.00654704859375]):
    BV.hydrodynamic.update_bottom(bottom_cal) # None
    BV.hydrodynamic.update_cond_decay(cond_decay_cal) # 0
    # BV.hydrodynamic.update_poro_decay(cond_decay_cal/2) # 0
    # if compt_model==0:
    BV.hydrodynamic.update_poro_decay(cond_decay_cal/2) # 0
    BV.hydrodynamic.update_hyd_cond(koptim_cal)
    
    for porosity_value in list_porosity[:]:
    # for porosity_value in [0.03]:
        
        BV.hydrodynamic.update_porosity(porosity_value)
        
        model_name = typ+'_'+str(compt_model)+'_'+\
                     str(bottom_cal)+'_'+\
                     str(round(koptim_cal,4))+'-'+\
                     str(round(porosity_value*100, 2))+'_'+\
                     str(round(1/(BV.hydrodynamic.cond_decay),1))+'-'+\
                     str(round(1/(BV.hydrodynamic.poro_decay),1))
                             
        print('SIM - ' + model_name)

        success, flow_model = BV.run_modflow(run=run,
                                             ident=model_name,
                                             sink_fill=sink_fill,
                                             modpath_sim=modpath_sim,
                                             zone_partic=zone_partic,
                                             box=box,
                                             verbose=verbose,
                                             post_process=post_process, 
                                             init_rech=init_rech,
                                             verti_k=verti_k)
        
        if success == True:
            print(     'Success')
        else:
            print(     'Error')
          
        list_model_name.append(model_name)
        list_of_success.append(success)
        list_flow_model.append(flow_model)
    
    # c += 1
    
    # if c>1:
    compt_model += 1

x = BV.hydrodynamic.porosity
y = flow_model.ps
    
print(list_of_success)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_of_success'] = list_of_success
dictio['list_flow_model'] = list_flow_model
h5file = simulations_folder+'/'+'list_'+typ

dd.io.save(h5file, dictio)

#%% ---- MODELING POSTPROCESS

#%% RELOAD MODELS

typ = 'explor1'

h5file = simulations_folder+'/'+'list_'+typ
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_of_success = d['list_of_success'][:]
list_flow_model = d['list_flow_model'][:]

#%% POSTPROCESS MODELS

sim_state = 'steady' # 'steady' or 'transient'
residence_times = True
time_step = 'D' # or 'D'
actual_date = False # False if date is conceptual

# types_obs = ["lasset_stream_wetland_perennial_pt_gpdv2"]
types_obs = ["lasset_stream_update_april23_wetlands_perennial_cut_topt"]

for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
    print(success)

    BV.matrix_modflow(success,
                      flow_model,
                      first_only = True,
                      watertable_elevation = True,
                      watertable_depth = True, 
                      seepage_areas = True,
                      outflow_drain = True,
                      groundwater_flux = False,
                      specific_discharge = False,
                      accumulation_flux = True,
                      perenn_intermit_shp = False,
                      groundwater_storage = True,
                      residence_times = residence_times,
                      verbose = True,
                      export_tif = True)
    
    # Necessary for results_modflow
    BV.forcing.update_recharge(flow_model.climatic,
                               sim_state=sim_state)
    
    # # Extract results
    print(model_name)
    BV.results_modflow(ident=model_name,
                       actual_date=actual_date,
                       time_step=time_step)
    
    ## Plot maps
    surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
                                          model_name, types_obs,
                                          save_gif=False,
                                          first_only=True,
                                          sim_state=sim_state,
                                          outflow=True,
                                          accflux=True,
                                          intermittency=False,
                                          chronics=False)

#%% ENDPOINT MODELS

# model_name = 'egu1_1_10.0-0.0-0.0857-26.68'
# model_name = 'egu1_0_500.0-0-0.0058-30.0'

# list_selects = ['egu1_4_20.0-0.0-0.1359-10.8', 'egu1_8_100.0-0.0-0.0211-3.9']
list_selects = list_model_name

fig_cross = True

for model_name, flow_model in zip(list_selects[12*5:], list_flow_model[12*5:]):
    print(model_name)
    # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
    # try:
        
    id_model = int(model_name.split('_')[1])
            
    ### MODEL ###
    # list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
    # model_name = list_path[-1].split('\\')[-1]
    mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
    
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    hk_grid = mf.upw.hk
    # sy_grid = mf.upw.sy
    sy_grid = flow_model.ps
    # sr_model = flopy.utils.reference.SpatialReference()
    
    if fig_cross == True:
        
        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
        linecollection = modelxsect.plot_grid()
        hdobj = flopy.utils.HeadFile(fname)
        head_data = hdobj.get_data()
        modelxsect.plot_array(hk_grid.array, ax=axs[0], cmap='YlOrRd_r')
        pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
                                    cmap='Blues', alpha=0.5, ax=axs[1])
        axs[0].set_title('Hydraulic conductivity')
        axs[1].set_title('Watertable and hydraulic gradient')
        fig.suptitle(model_name, y=1.05)
        
        bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
        ext_mod = bv_box.geometry.total_bounds
        
        # axs[0].set_ylim(150, 350)
        # axs[1].set_ylim(150, 350)
        
        fig.savefig(fig_path+'cross_section_h_'+model_name+'.png', dpi=300, bbox_inches='tight')

        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[0])/2)})
        linecollection = modelxsect.plot_grid()
        hdobj = flopy.utils.HeadFile(fname)
        head_data = hdobj.get_data()
        modelxsect.plot_array(sy_grid, ax=axs[0], cmap='YlGn_r')
        pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
                                    cmap='Blues', alpha=0.5, ax=axs[1])
        axs[0].set_title('Porosity')
        axs[1].set_title('Watertable and hydraulic gradient')
        fig.suptitle(model_name, y=1.05)
        
        bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
        ext_mod = bv_box.geometry.total_bounds
        
        # axs[0].set_ylim(150, 350)
        # axs[1].set_ylim(150, 350)
        
        fig.savefig(fig_path+'cross_section_v_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
    crs_code = 2154
    
    """
    def reproj_approx_points(shp_name, crs_code):
        shp = gpd.read_file(simulations_folder+
                            model_name+'/'+'_pathlines/'+
                            shp_name+'.shp')
        ext_shp = shp.geometry.total_bounds
        shp.set_crs(epsg=crs_code, inplace=True, allow_override=True)
        # shp.to_crs(utm_crs)
        print(ext_shp)
        x = (shp.geometry.x) + ext_mod[0] # - ext_shp[0] # 6.39e5 
        y = (shp.geometry.y) + ext_mod[1] # - ext_shp[3] # 1.78e6 
        gdf = gpd.GeoDataFrame(shp, geometry=gpd.points_from_xy(x, y))
        gdf.to_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    shp_name+'.shp')
    """
    
    ### POINTS ###
    print('Create shapefile ending and starting points')
    endobj = flopy.utils.EndpointFile(simulations_folder+
                                      model_name+'/'+model_name+'.mpend')
    e = endobj.get_alldata()
    
    endobj.write_shapefile(endpoint_data=e,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'ending.shp',
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    shp_sim = gpd.read_file(path_pathlines+'ending.shp')
    shp_sim.time = shp_sim.time / 365
    shp_sim.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years.shp') # time in years !
    masked = shp_sim.copy()
    masked = masked[masked.time > 0.1] # ONLY SUP ONE MONTH APPROX
    masked = masked[masked.k == 1] # ONLY OUT FIRST CELL
    masked = masked[masked.zloc != 1] # NOT IN AND OUT SAME CELL
    if not masked[masked.time > 1000].empty:
        print('THERE IS CELL > 1000y')
        if len(masked[masked.time > 1000]) <= (len(masked)*0.05):
            print('DELETE > 1000y', str(len(masked[masked.time > 1000]))+'/'+
                                    str((len(masked))))
            # IF ONLY 5% CELL ARE HIGHER THAN 1000 YEARS : MASKED (OUTLIERS):
            masked = masked[masked.time <= 1000]
        else:
            print('NO CELL > 1000y')
    masked.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years_masked.shp') # time in years !
    keep_particules = masked.particleid
    keep_particules = keep_particules.tolist()
    
    endobj.write_shapefile(endpoint_data=e,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'starting.shp',
                            direction='starting',
                            mg=grid_model, epsg=crs_code, sr=None)
    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    shp_sim = gpd.read_file(path_pathlines+'starting.shp')
    shp_sim.time = shp_sim.time / 365
    shp_sim.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'starting_years.shp') # time in years !
    
    # reproj_approx_points('ending')
    # reproj_approx_points('starting')
    
    #### SELECT PARTICLUES ####
    if not os.path.exists(simulations_folder+'_id_particules_random.data'):
        id_particules_random = random.sample(keep_particules[:-1], 1000)
        with open(simulations_folder+'_id_particules_random.data', 'wb') as f:
            pickle.dump(id_particules_random, f)
    # else:
    #     with open(simulations_folder+'_id_particules_random.data', 'rb') as f:
    #         id_particules_random = pickle.load(f)

    #     print('VALID '+model_name)
    # except:
    #     print('ERROR '+model_name)
    #     pass

#%% EXTRACT RT MODELS

dic_res = {}

for model_name in list_model_name[:]:
    
    # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
        
    print(model_name)

    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    
    path_rtd_obs= path_obs+'age_apparent_obs_C2_corrected.shp'
    shp_obs = gpd.read_file(path_rtd_obs)
    shp_obs['geometry'] = shp_obs.geometry.buffer(100)
    # shp_obs = shp_obs[['ID_station', 'geometry']]
    shp_obs.to_file(path_pathlines+'time_simobs.shp', encoding='utf-8') # mode a
            
    masked = gpd.read_file(path_pathlines+'ending_years_masked.shp')

    intersect = gpd.overlay(masked, shp_obs, how='intersection')
            
    # fig, ax = plt.subplots(1,1)
    # shp_sim.plot(ax=ax, color='darkorange', alpha=0.1)
    # intersect.plot(ax=ax, color='blue')
    # shp_obs.plot(ax=ax, ec='k', facecolor='None', lw=2)

    res_dat = gpd.read_file(path_pathlines+'time_simobs.shp')
    
    res_dat['tobs_CFC11'] = 2021 - res_dat['CFC11']
    res_dat['tobs_CFC12'] = 2021 - res_dat['CFC12']
    res_dat['tobs_CFC113'] = 2021 - res_dat['CFC113']
    res_dat['tobs_mean'] = np.nanmean(res_dat[['tobs_CFC11','tobs_CFC12','tobs_CFC113']], axis=1)
    res_dat['tobs_std'] = np.nanstd(res_dat[['tobs_CFC11','tobs_CFC12','tobs_CFC113']], axis=1)
    
    res_dat['tsim_min'] = np.nan
    res_dat['tsim_q10'] = np.nan
    res_dat['tsim_q25'] = np.nan
    res_dat['tsim_mean'] = np.nan
    res_dat['tsim_media'] = np.nan
    res_dat['tsim_q75'] = np.nan
    res_dat['tsim_q90'] = np.nan
    res_dat['tsim_max'] = np.nan
    res_dat['tsim_std'] = np.nan
    
    uniq = intersect.copy()
    for ID in intersect['id'].unique():
        # threshold = 1 #year
        # threshold = threshold*365
        # threshold = np.log10(threshold)
        uniq['time'] = uniq['time']
        masked_intersect = uniq[uniq['id']==ID]
        if masked_intersect.empty:
            res_dat['tsim_min'][res_dat['id']==ID] = np.nan
            res_dat['tsim_q10'][res_dat['id']==ID] = np.nan
            res_dat['tsim_q25'][res_dat['id']==ID] = np.nan
            res_dat['tsim_media'][res_dat['id']==ID] = np.nan
            res_dat['tsim_mean'][res_dat['id']==ID] = np.nan
            res_dat['tsim_q75'][res_dat['id']==ID] = np.nan
            res_dat['tsim_q90'][res_dat['id']==ID] = np.nan
            res_dat['tsim_max'][res_dat['id']==ID] = np.nan
            res_dat['tsim_std'][res_dat['id']==ID] = np.nan
            
        else:
            res_dat['tsim_min'][res_dat['id']==ID] = np.nanmin(masked_intersect['time'])
            res_dat['tsim_q10'][res_dat['id']==ID] = np.nanquantile(masked_intersect['time'], 0.10)
            res_dat['tsim_q25'][res_dat['id']==ID] = np.nanquantile(masked_intersect['time'], 0.25)
            res_dat['tsim_mean'][res_dat['id']==ID] = np.nanmean(masked_intersect['time'])
            res_dat['tsim_media'][res_dat['id']==ID] = np.nanmedian(masked_intersect['time'])
            res_dat['tsim_q75'][res_dat['id']==ID] = np.nanquantile(masked_intersect['time'], 0.75)
            res_dat['tsim_q90'][res_dat['id']==ID] = np.nanquantile(masked_intersect['time'], 0.90)
            res_dat['tsim_max'][res_dat['id']==ID] = np.nanmax(masked_intersect['time'])
            res_dat['tsim_std'][res_dat['id']==ID] = np.nanstd(masked_intersect['time'])
            
    res_dat.to_file(path_pathlines+'time_simobs.shp')
    
    dic_res[model_name] = res_dat

with open(simulations_folder+'/'+'_dic_res_RT_'+typ, 'wb') as handle:
    pickle.dump(dic_res, handle, protocol=pickle.HIGHEST_PROTOCOL)

# dd.io.save(simulations_folder+'/'+'_dic_res_RT_'+typ, dic_res)

#%% PATHLINES MODELS

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

for model_name in list_selects[:]:

    ### MODEL ###

    mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
    
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    hk_grid = mf.upw.hk
    # sr_model = flopy.utils.reference.SpatialReference()

    bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
    ext_mod = bv_box.geometry.total_bounds
    
    crs_code = 2154 # 32620 # 2154
    
    ### PATHLINES ###
    print('Create shapefile particules and pathlines')
    pthobj = flopy.utils.PathlineFile(simulations_folder+
                                      model_name+'/'+model_name+'.mppth')
    pth_data = pthobj.get_alldata()
    
    for k in range(len(pth_data)):
        pth_data[k].time = pth_data[k].time / 365
    # from operator import itemgetter
    # n = itemgetter(*keep_particules)(pth_data)
    
    with open(simulations_folder+'_id_particules_random.data', 'rb') as f:
        id_particules_random = pickle.load(f)
    
    # pth_data_rand = [pth_data[i] for i in id_particules_random[:-1]]

    # x= list(map(lambda i: pth_data[i], keep_particules))
    # x = pth_data[::2]
        
    # id_particules_random = random.sample(keep_particules[:-1], 1000)
    
    # random.sample(keep_particules[:-1], 1000)
    
    pth_data_save = []
    for o, i in enumerate(id_particules_random):
        print(o, i, len(id_particules_random))
        for j in pth_data:
            if i == j.particleid[0]:
                pth_data_save.append(j)
                    
    # pthobj.write_shapefile(pathline_data=pth_data,
    #                         shpname=simulations_folder+
    #                                 model_name+'/'+'_pathlines/'+
    #                                 'particlues.shp',
    #                         one_per_particle=False, 
    #                         direction='ending',
    #                         mg=grid_model, epsg=crs_code, sr=None)
        
    # pth_data_springs = []
    # for o, i in enumerate(sp_particules):
    #     print(o, i, len(sp_particules))
    #     for j in pth_data_save:
    #         if i == j.particleid[0]:
    #             pth_data_springs.append(j)
    
    """
    ### ALL PATHLINES
    print('ALL PATHLINES')
    pthobj.write_shapefile(pathline_data=pth_data,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'pathlines.shp',
                            one_per_particle=True, 
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    
    ### ALL PARTICULES
    print('ALL PARTICULES')
    pthobj.write_shapefile(pathline_data=pth_data,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'particules.shp',
                            one_per_particle=False, 
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    """
    
    ### 1000 pathlines
    print('1000 pathlines')
    pthobj.write_shapefile(pathline_data=pth_data_save,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'pathlines_1000.shp',
                            one_per_particle=True, 
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    
    ### 1000 particules
    print('1000 particules')
    pthobj.write_shapefile(pathline_data=pth_data_save,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'particules_1000.shp',
                            one_per_particle=False,
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    

    ### FOR SPRINGS
    
    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    
    # path_rtd_obs= path_obs+'age_apparent_obs_C2_corrected.shp'
    # shp_obs = gpd.read_file(path_rtd_obs)
    # shp_obs['geometry'] = shp_obs.geometry.buffer(100)
    # # shp_obs = shp_obs[['ID_station', 'geometry']]
    # shp_obs.to_file(path_pathlines+'time_simobs.shp', encoding='utf-8') # mode a
    
    
    shp_simobs = gpd.read_file(path_pathlines+'time_simobs.shp', encoding='utf-8') # mode a
    masked = gpd.read_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years_masked.shp') # time in years !
    intersect = gpd.overlay(masked, shp_simobs, how='intersection')
    
    sp_particules = intersect.particleid
    sp_particules = sp_particules.tolist()
    
    # pth_data_springs = [pth_data[i] for i in sp_particules[:]]
    
    shp_all_pathlines = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'pathlines_1000.shp')
    keep = np.isin(shp_all_pathlines, sp_particules)
    shp_springs = shp_all_pathlines[keep]
    shp_springs.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'pathlines_1000_springs.shp')

#%% SEPRATE BY LAYERS

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name[:]

for model_name in list_selects[:]:

    shp_starting = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'starting_years.shp')
    
    shp_ending = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'ending_years.shp')
    
    shp_pathlines = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'pathlines_1000.shp')
    
    shp_particules = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'particules_1000.shp')
    
    ###### METHOD 1 : PARTIAL
    particleid = shp_particules['particleid'].unique()
    shalid = []
    # bothid = []
    deepid = []
    
    for pid in particleid :
        print(pid, len(particleid))
        mask = shp_particules.loc[shp_particules['particleid']==pid]
        if all(x < 40 for x in mask.k):
            shalid.append(pid)
        if any(x >= 40 for x in mask.k):
            deepid.append(pid)
            
    indices_layers_rdm = [random.sample(shalid, len(shalid)),
                          random.sample(deepid, len(deepid))]    
    
    ###### METHOD 2 : TOTAL
    pthobj = flopy.utils.PathlineFile(simulations_folder+
                                      model_name+'/'+model_name+'.mppth')
    pth_data = pthobj.get_alldata()
    
    cond_lay = 40 # ==> approx. 40 meters
    compt = 0
    indices_layers = []
    superf_p = []
    superf_id = []
    profon_p = []
    profon_id = []
    for idx, pline in enumerate(pth_data):
        if all(x < cond_lay for x in pline.k):
            compt += 1
            # print(compt)
            superf_p.append(pline)
            superf_id.append(pline['particleid'][0])
        else:
            profon_p.append(pline)
            profon_id.append(pline['particleid'][0])     

    indices_layers = [profon_id, superf_id]
    
    # if not os.path.exists(simulations_folder+
    #                       model_name+'/'+'_id_profon_superf.data'):
    with open(simulations_folder+
                      model_name+'/'+'_id_profon_superf.data', 'wb') as f:
        pickle.dump(indices_layers, f)
            
    shp_starting_shal = shp_starting[np.isin(shp_starting.particleid, superf_id)]
    shp_starting_shal.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_starting_shal.shp') # time in years !
    shp_starting_deep = shp_starting[np.isin(shp_starting.particleid, profon_id)]
    shp_starting_deep.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_starting_deep.shp') # time in years !
    
    shp_ending_shal = shp_ending[np.isin(shp_ending.particleid, superf_id)]
    shp_ending_shal.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    shp_ending_deep = shp_ending[np.isin(shp_ending.particleid, profon_id)]
    shp_ending_deep.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    
    shp_pathlines_shal = shp_pathlines[np.isin(shp_pathlines.particleid, shalid)]
    shp_pathlines_shal.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_pathlines_shal.shp') # time in years !
    shp_pathlines_deep = shp_pathlines[np.isin(shp_pathlines.particleid, deepid)]
    shp_pathlines_deep.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_pathlines_deep.shp') # time in years !
    
    shp_particules_shal = shp_particules[np.isin(shp_particules.particleid, shalid)]
    shp_particules_shal.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_particules_shal.shp') # time in years !
    shp_particules_deep = shp_particules[np.isin(shp_particules.particleid, deepid)]
    shp_particules_deep.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_particules_deep.shp') # time in years !

    """
    if not os.path.exists(simulations_folder+'id_layers_random.data'):
        id_layers_random = [random.sample(shalid, 500),
                            random.sample(deepid, 500)]
        with open(simulations_folder+'id_layers_random.data', 'wb') as f:
            pickle.dump(id_layers_random, f)
    else:
        with open(simulations_folder+'id_layers_random.data', 'rb') as f:
            id_layers_random = pickle.load(f)
    
    shp_starting['time_year'] = shp_starting['time']
    shp_ending['time_year'] = shp_ending['time']
    shp_particules['time_year'] = shp_particules['time']
    shp_pathlines['time_year'] = shp_pathlines['time']
    
    particleid = shp_particules['particleid'].unique()
    
    for pid in particleid[:] :
        mask = shp_particules.loc[shp_particules['particleid']==pid, shp_particules.columns]
        print(pid, len(particleid), len(mask))
        shp_particules.loc[shp_particules['particleid']==pid, 'd'] = ((mask.x.diff())**2 +
                                                                      (mask.y.diff())**2 +
                                                                      (mask.z.diff())**2)**(1/2)
        shp_particules.loc[shp_particules['particleid']==pid, 'dt'] = mask.time_year.diff()
        # mask['d'] = ((mask.x.diff())**2 + (mask.y.diff())**2 + (mask.z.diff())**2)**(1/2)
        # pd.concat([shp_particules, mask])
    
    shp_particules['V'] = shp_particules['d'] / shp_particules['dt']
    
    shp_particules_shal = shp_particules[np.isin(shp_particules.particleid, id_layers_random[0])]
    shp_particules_deep = shp_particules[np.isin(shp_particules.particleid, id_layers_random[1])]
    """

#%% DECREASE NUMBER PATHLINES

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name[:]

for model_name in list_selects[:]:

    shp_1000_particules = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'particules_1000.shp')
    
    shp_100_particules = shp_1000_particules[np.isin(shp_1000_particules.particleid, np.random.choice(shp_1000_particules.particleid, 10))]
    shp_100_particules.to_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'particules_10.shp')
    
    shp_particules_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_particules_shal.shp') # time in years !
    shp_x_particules_shal = shp_particules_shal[np.isin(shp_particules_shal.particleid, np.random.choice(shp_particules_shal.particleid, 50))]
    shp_x_particules_shal.to_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'shp_x_particules_shal.shp')
    shp_particules_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_particules_deep.shp') # time in years !
    shp_x_particules_deep = shp_particules_deep[np.isin(shp_particules_deep.particleid, np.random.choice(shp_particules_deep.particleid, 25))]
    shp_x_particules_deep.to_file(simulations_folder+
                            model_name+'/'+'_pathlines/'+
                            'shp_x_particules_deep.shp')

#%% VISU2D PATHLINES 

fig, ax = plt.subplots(1,1, figsize=(3.8,2.8))

geotx_p = BV.geographic.x_coord
geoty_p = BV.geographic.y_coord
geot_p = BV.geographic.geodata
cols = geotx_p.shape[0]
rows = geoty_p.shape[0]
ext = []
xarr = [0, cols]
yarr = [0, rows]
for px in xarr:
    for py in yarr:
        x = geotx_p[0] + (px * geot_p[1]) + (py * geot_p[2])
        y = geoty_p[0] + (px * geot_p[4]) + (py * geot_p[5])
        ext.append([x, y])
max_time = []
min_time = []
for j in sp_particules:
    max_time.append(np.max(np.log10(pth_data[j].time)))
    min_time.append(np.min(np.log10(pth_data[j].time)))
for j in sp_particules:
    x = pth_data[j].x + ext[1][0]
    y = pth_data[j].y + ext[1][1]
    points = np.array([x, y]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    from matplotlib.collections import LineCollection
    lc = LineCollection(segments, cmap='jet', alpha=0.5)
    # lc.set_array(np.log10(pth_data[j].time/365)) # log(t) in days
    lc.set_array(pth_data[j].time / 365) # t in years
    lc.set_linewidth(2)
    # if color_scale[i][0] == None:
    #     lc.set_clim(1,np.max(max_time))
    # else:
    #     lc.set_clim(color_scale[i][0],color_scale[i][1])
    line = ax.add_collection(lc)
plt.show()
# image.append(line)
# basemap.append(0)
# contour.plot(ax=ax, lw=2, color='k', zorder=4,legend=True, label='Watershed')

#%% ---- LOAD RESULTS

#%% RECAP MODELS

with open(simulations_folder+'/'+'_dic_res_RT_'+typ, 'rb') as f:
    dic_res = pickle.load(f)

try:
    with open(simulations_folder+'_id_particules_random.data', 'rb') as f:
        id_particules_random = pickle.load(f)
except:
    pass

df_explo = pd.DataFrame()

# c=0
cp = 0
compt_model = 0

for cond_decay_cal, bottom_cal, koptim_cal in zip(list_cond_decay[:],
                                                  list_bottom[:],
                                                  list_koptim[:]):
    for porosity_value in list_porosity[:]:
        
        # model_name = typ+'_'+str(compt_model)+'_'+\
        #              str(round(1/cond_decay_cal,1))+'-'+\
        #              str(bottom_cal)+'-'+\
        #              str(round(koptim_cal,4))+'-'+\
        #              str(round(porosity_value*100, 2))
                    
        model_name = typ+'_'+str(compt_model)+'_'+\
                     str(bottom_cal)+'_'+\
                     str(round(koptim_cal,4))+'-'+\
                     str(round(porosity_value*100, 2))+'_'+\
                     str(round(1/cond_decay_cal,1))+'-'+\
                     str(round(1/(cond_decay_cal/2),1))
                     
        print(model_name)
                     
        path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
        res_dat = gpd.read_file(path_pathlines+'time_simobs.shp')
        
        df_explo.loc[cp,'model_name'] = model_name
        df_explo.loc[cp,'compt_model'] = compt_model
        df_explo.loc[cp,'cond_decay_cal'] = cond_decay_cal
        df_explo.loc[cp,'bottom_cal'] = bottom_cal
        df_explo.loc[cp,'koptim_cal'] = koptim_cal
        df_explo.loc[cp,'porosity_value'] = porosity_value
                
        for choice in ['mean','media','max','std']:
            for point in res_dat['id']:
                df_explo.loc[cp, point+'_obs'] =  res_dat[res_dat['id']==point]['tobs_mean'].values[0]
                df_explo.loc[cp, point+'_sim_'+choice] = res_dat[res_dat['id']==point]['tsim_'+choice].values[0]
                df_explo.loc[cp, point+'_comp_'+choice] = df_explo.loc[cp, point+'_sim_'+choice] / df_explo.loc[cp, point+'_obs']
        
            RMSE = np.sqrt(np.nanmean((res_dat['tobs_mean']-res_dat['tsim_'+choice])**2))
            # RMSE = he.evaluator(he.rmse, ysim, yobs)
            # RMSE = mean_squared_error(yobs, ysim, squared=False)
            # print(RMSE)
            df_explo.loc[cp,'RMSE_'+choice] = RMSE

        cp += 1
    # c += 1
    # if c>1:
    compt_model += 1
    # compt_model += 1

df_explo.to_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

#%% ---- MODELING PLOT

#%% CROSS DECAY HEAD 

for model_name in [
                    'egu1_0_inf-None-0.0596-0.3',
                    'egu1_1_inf-0.0-0.0017-0.3',
                    'egu1_2_10.0-0.0-0.3089-0.3',
                    'egu1_11_300.0-0.0-0.0065-0.3'
                    ][:]:

# for model_name in [
#                    'egu1_4_20.0-0.0-0.1359-10.8', 'egu1_8_100.0-0.0-0.0211-3.9'
#                    ]:    

    ### MODEL ###
    # list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
    # model_name = list_path[-1].split('\\')[-1]
    mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
    
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    hk_grid = mf.upw.hk
    # sr_model = flopy.utils.reference.SpatialReference()
    fig, axs = plt.subplots(1, 2, figsize=(10, 2.5))
    # ax = fig.add_subplot(1, 1, 1)
    axs = axs.ravel()
    modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
    linecollection = modelxsect.plot_grid(color='k', alpha=0., lw=0.1)
    hdobj = flopy.utils.HeadFile(fname)
    head_data = hdobj.get_data()
    modelxsect.plot_array(hk_grid.array, ax=axs[0], cmap='plasma', alpha=0.5)
    modelxsect.plot_fill_between(head_data, color='saddlebrown', edgecolor='none',
                                 alpha=0.5)
    pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
                                cmap='Blues', alpha=0.5, ax=axs[1])
    axs[0].set_title('Hydraulic conductivity', fontsize=8)
    axs[1].set_title('Watertable and hydraulic gradient', fontsize=8)
    
    axs[0].set_ylim(1300, 2200)
    axs[1].set_ylim(1300, 2200)
    
    axs[0].set_xticks(np.arange(0,4001, 1000))
    axs[1].set_xticks(np.arange(0,4001, 1000))
    
    axs[0].set_yticks(np.arange(1400,2201, 200))
    axs[1].set_yticks(np.arange(1400,2201, 200))
    
    fig.suptitle(model_name, y=1.1, fontsize=8)
    
    bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
    ext_mod = bv_box.geometry.total_bounds
    
    crs_code = 2154

#%% DICHOTOMY MODELS

# Import K calibrated
df = pd.read_csv(BV.calibration_folder+'/'+dicot_name+'_'+watershed_name+'.csv', sep=';')
# Koptim = float('{:.1e}'.format(df.loc[0][1]))
df['1/cond_decay'] = 1/df['cond_decay']
df['Doptim'] = (df.Dso + df.Dos)/2
df['Dabs'] = abs(df.Dso - df.Dos)

fig, ax = plt.subplots(1,1, figsize=(5,4))
# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
# im = ax.scatter(df.cond_decay, (df.Dso+ df.Dos)/2, c=df.cond_decay, s=100, cmap='jet',
#                 norm=mpl.colors.LogNorm())
im = ax.scatter(df.k, df['1/cond_decay'], c=df.ind, s=100, cmap='jet',
                norm=mpl.colors.LogNorm(vmin=1e-7, vmax=1)
                )
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('K [m/s]')
ax.set_ylabel('1 / Decay ratio [m]')
cb = plt.colorbar(im, ax=ax)
cb.ax.set_ylabel('(log(Dso/Dos))^2', rotation=270, labelpad=25)
ax.axhline(y=60, ls='--', c='k')
ax.axhline(y=50, ls='--', c='k')

fig, ax = plt.subplots(1,1, figsize=(5,4))
# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
# im = ax.scatter(df.cond_decay, (df.Dso+ df.Dos)/2, c=df.cond_decay, s=100, cmap='jet',
#                 norm=mpl.colors.LogNorm())
im = ax.scatter(df.k, df['1/cond_decay'], c=df.Doptim, s=100, cmap='jet',
                # norm=mpl.colors.LogNorm(vmin=10, vmax=100)
                )
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('K [m/s]')
ax.set_ylabel('1 / Decay ratio [m]')
cb = plt.colorbar(im, ax=ax)
cb.ax.set_ylabel('Doptim', rotation=270, labelpad=25)
# ax.axhline(y=60, ls='--', c='k')
# ax.axhline(y=50, ls='--', c='k')

fig, ax = plt.subplots(1,1, figsize=(5,4))
# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
# im = ax.scatter(df.cond_decay, (df.Dso+ df.Dos)/2, c=df.cond_decay, s=100, cmap='jet',
#                 norm=mpl.colors.LogNorm())
im = ax.scatter(df.k, df['1/cond_decay'], c=df['Dabs'], s=100, cmap='jet',
                norm=mpl.colors.LogNorm(),
                )
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('K [m/s]')
ax.set_ylabel('1 / Decay ratio [m]')
cb = plt.colorbar(im, ax=ax)
cb.ax.set_ylabel('Dabs', rotation=270, labelpad=25)
ax.axhline(y=60, ls='--', c='k')
ax.axhline(y=50, ls='--', c='k')

fig, ax = plt.subplots(1,1, figsize=(5,4))
# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
im = ax.scatter(df.k, df['Doptim'], c=df.cond_decay, s=100, cmap='jet',
                norm=mpl.colors.LogNorm())
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('K [m/s]')
ax.set_ylabel('(Dso+Dos)/2')
cb = plt.colorbar(im, ax=ax)
cb.ax.set_ylabel('Decay ratio', rotation=270, labelpad=25)

fig, ax = plt.subplots(1,1, figsize=(5,4))
# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
im = ax.scatter(df.k, df.ind, c=1/df.cond_decay, s=100, cmap='jet',
                norm=mpl.colors.LogNorm()
                )
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('K [m/s]')
ax.set_ylabel('(log(Dso/Dos))^2')
cb = plt.colorbar(im, ax=ax)
cb.ax.set_ylabel('Decay ratio', rotation=270, labelpad=25)

#%% DICHOTOMY FIGURE

# Import K calibrated
df = pd.read_csv(BV.calibration_folder+'/'+dicot_name+'_'+watershed_name+'.csv', sep=';')
df = df[:]
# Koptim = float('{:.1e}'.format(df.loc[0][1]))
df['1/cond_decay'] = 1/df['cond_decay']
df['1/cond_decay'][df['1/cond_decay']==np.inf] = np.nan
df['Doptim'] = (df.Dso + df.Dos)/2
# df['Dabs'] = abs(df.Dso - df.Dos)
# df['Dabs'] = (df.Dso - df.Dos)
df['Dabs'] = (df.Dso + df.Dos)/2
# df['Dabs'] = (df.ind)

# for i in df.index[2:3]:
#     df.loc[df.index==i,'k'] = df.loc[df.index==i,'k']+0.1
# for i in df.index[3:4]:
#     df.loc[df.index==i,'k'] = df.loc[df.index==i,'k']+0.05
# for i in df.index[8:9]:
#     df.loc[df.index==i,'Dabs'] = df.loc[df.index==i,'Dabs']-16

# df = df[1:]

fig, ax = plt.subplots(1,1, figsize=(3.6,2.6))
# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
ax.scatter(df[:1].k/24/3600, df[:1].Dabs, c=df[:1].cond_decay, s=100, 
           marker='s', lw=2,
           cmap=mpl.colors.ListedColormap('k'),
           label=df[:1]['1/cond_decay'].values[0]
                )
ax.scatter(df[1:2].k/24/3600, df[1:2].Dabs, c=df[1:2].cond_decay, s=100, 
           marker='o', lw=2,
           cmap=mpl.colors.ListedColormap('gray'),
           label='0'
                )
im = ax.scatter(df[2:].k/24/3600, df[2:].Dabs, c=1/df[2:].cond_decay, s=100, 
                cmap='jet',
                norm=mpl.colors.LogNorm(vmin=10, vmax=300),
                lw=2,
                label=df['1/cond_decay']
                
                )
# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('K [m/s]')
ax.set_xlim(1e-8, 1e-5)
ax.set_ylim(30, 80)
ax.set_ylabel('I [-]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.20, 0.03, 0.7]))
for t in cb.ax.get_yticklabels():
     t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
cb.ax.set_ylabel('d [m]', rotation=270, labelpad=25)

#%% DICHOTOMY TRANSMISSIVITY

iDb =  'egu1'
iDb =  'explor1'
simul_list = sorted(glob.glob(simulations_folder+iDb+'*'), key=os.path.getmtime)

sel = 0.3
filtered = list(filter(lambda score: score.split('-')[-1] == str(sel), list_model_name))

df = pd.read_csv(BV.calibration_folder+'/'+dicot_name+'_'+watershed_name+'.csv', sep=';')

c = 0
for model_name in filtered:
    # Import K calibrated
    Smod_path = simulations_folder + model_name + '/_watershed/_simulated_results.csv'
    Smod_raw = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    if c == 0:
        df.loc[c, 'sat'] = 50 - Smod_raw['watertable_depth'].values[0]
    else:
        df.loc[c, 'sat'] = Smod_raw['watertable_elevation'].values[0]
    c+=1

df['T'] = (df['k']/24/3600) *  df['sat']

df = df[:]
# Koptim = float('{:.1e}'.format(df.loc[0][1]))
df['1/cond_decay'] = 1/df['cond_decay']
df['1/cond_decay'][df['1/cond_decay']==np.inf] = np.nan
df['Doptim'] = (df.Dso + df.Dos)/2
# df['Dabs'] = abs(df.Dso - df.Dos)
# df['Dabs'] = (df.Dso - df.Dos)
df['Dabs'] = (df.Dso + df.Dos)/2
# df['Dabs'] = (df.ind)

# for i in df.index[2:3]:
#     df.loc[df.index==i,'k'] = df.loc[df.index==i,'k']+0.1
# for i in df.index[3:4]:
#     df.loc[df.index==i,'k'] = df.loc[df.index==i,'k']+0.05
# for i in df.index[8:9]:
#     df.loc[df.index==i,'Dabs'] = df.loc[df.index==i,'Dabs']-16

# df = df[1:]

fig, ax = plt.subplots(1,1, figsize=(3.6,2.6))
# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
ax.scatter(df[:1]['T'], df[:1].Dabs, c=df[:1].cond_decay, s=100, 
           marker='s', lw=2,
           cmap=mpl.colors.ListedColormap('k'),
           label=df[:1]['1/cond_decay'].values[0]
                )
ax.scatter(df[1:2]['T'], df[1:2].Dabs, c=df[1:2].cond_decay, s=100, 
           marker='o', lw=2,
           cmap=mpl.colors.ListedColormap('gray'),
           label='0'
                )
im = ax.scatter(df[2:]['T'], df[2:].Dabs, c=1/df[2:].cond_decay, s=100, 
                cmap='jet',
                norm=mpl.colors.LogNorm(vmin=10, vmax=300),
                lw=2,
                label=df['1/cond_decay']
                
                )
# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('T [m²/s]')
ax.set_xlim(1e-5, 1e-2)
ax.set_ylim(30, 80)
ax.set_ylabel('I [-]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.20, 0.03, 0.7]))
for t in cb.ax.get_yticklabels():
     t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
cb.ax.set_ylabel('d [m]', rotation=270, labelpad=25)

#%% MAPPING MODELS

import hydroeval as he

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

vmin = 0
vmax = 100

sel = 11
filtered = list(filter(lambda score: score.split('_')[1] == str(sel), list_model_name))

for model_name in filtered[-1:]:
    print(model_name)
    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    shp_sim = gpd.read_file(path_pathlines+'ending.shp')
    res_dat = gpd.read_file(path_pathlines+'time_simobs.shp')
    res_dat['tcomp_mean'] = res_dat['tsim_mean'] / res_dat['tobs_mean']

    # fig, axs = plt.subplots(1,2, figsize=(8,4))
    # axs = axs.ravel()
    
    fig, ax = plt.subplots(1,1, figsize=(6,6))
    # ax = axs[0]
    shp_sim.plot(ax=ax, column='time', cmap='cool', alpha=0.1, ec='None', vmin=vmin, vmax=vmax)
    res_dat.plot(ax=ax, alpha=1, lw=2, facecolor='None')
    from matplotlib import colors
    norm = colors.TwoSlopeNorm(vmin=0, vcenter=1, vmax=2)
    res_dat.plot(ax=ax, column='tsim_mean', cmap='RdYlGn_r', alpha=1, lw=2, norm=norm)
    bounds = dem.bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    scalebar = ScaleBar(1, box_alpha=0, scale_loc = 'bottom', location='upper left')
    ax.add_artist(scalebar)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(model_name, fontproperties=fontprop)
    ax.set(aspect='equal')
    sm = plt.cm.ScalarMappable(cmap='cool', norm=plt.Normalize(vmin=vmin, vmax=vmax))
    divider = make_axes_locatable(ax)
    cax = divider.append_axes(size="2%",position='right', pad=0.05)
    fig.add_axes(cax)
    cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
    cbar.ax.get_ymajorticklabels()
    cbar.ax.tick_params(labelsize=10)
    cbar.ax.yaxis.set_ticks_position('right')
    cbar.ax.tick_params(size=2)
    contour = gpd.read_file(BV.geographic.watershed_contour_shp)
    contour.plot(ax=ax, lw=1.5, color='k', zorder=20, legend=False, label='Watershed')
    cbar.set_ticks(list(cbar.get_ticks()))
    # cbar.set_ticklabels(list(cbar.get_ticks())[::-1])
    cbar.set_label('Residence times [years]', rotation=270, labelpad=25)
    res_dat['coords'] = res_dat['geometry'].apply(lambda x: x.representative_point().coords[:])
    res_dat['coords'] = [res_dat[0] for res_dat in res_dat['coords']]
    for idx, row in res_dat.iterrows():
        row['coords'] = (row['coords'][0], row['coords'][1]+100)
        # try:
        ax.annotate(text=row['id'], xy=row['coords'], horizontalalignment='center', size=8)
        # except:
        #     pass

#%% OBSSIM MODELS

choice = 'mean'

vmin = 0
vmax = 100

for s in range(12):
# for s in [7]:

    sel = s
    filtered = list(filter(lambda score: score.split('_')[1] == str(sel), list_model_name))
    
    structure = 'h'
    N = len(filtered)
    if structure == 'v':
        C = int(np.sqrt(N))
        R = int(N/C)+1
    if structure == 'h':
        R = int(np.sqrt(N))
        C = int(N/R)+1
        
    fig, axs = plt.subplots(nrows=2, ncols=5 ,figsize=(15,5), dpi=300)
  
    def trim_axs(axs, N):
        """little helper to massage the axs list to have correct length..."""
        axs = axs.flat
        for ax in axs[N:]:
            ax.remove()
        return axs[:N]
    
    # axs = trim_axs(axs,N)
    axs = axs.ravel()
    
    for i, model_name in enumerate(filtered[:]):
        try:
            ax= axs[i]
            
            path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
            shp_sim = gpd.read_file(path_pathlines+'ending.shp')
            res_dat = gpd.read_file(path_pathlines+'time_simobs.shp')
            
            # fig, ax = plt.subplots(1,1, figsize=(5,4.5))
            # ax = axs[1]
            mean_obs = res_dat[['CFC11', 'CFC12', 'CFC113']].mean(axis=1)
            std_obs = res_dat[['CFC11', 'CFC12', 'CFC113']].std(axis=1)
            x=2021-(mean_obs)
            xerr=std_obs
            mean_sim = res_dat['tsim_'+choice]
            y=mean_sim
            print(mean_sim)
            yerr = res_dat['tsim_std']
            ax.scatter(x, y, c=y, s=50, cmap=mpl.colors.ListedColormap('k'))
            plt.errorbar(x, y , xerr=list(xerr), yerr=yerr, lw=1, fmt="o", color='k')
            # ax.legend()
            ax.set_xlabel('$Age_{obs}$ [years]')
            ax.set_ylabel('$Age_{sim}$ [years]')
            for i, txt in enumerate(res_dat.id):
                ax.annotate(txt, (x[i], y[i]))
            xn=0
            xx=100
            yn=0
            yx=100
            ax.set_xlim(xn, xx)
            ax.set_ylim(yn, yx)
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
            #         linestyle='--', color='grey', linewidth=2, zorder=-1)
            maxx = max(ax.get_xlim()[0],ax.get_xlim()[1])
            maxy = max(ax.get_ylim()[0],ax.get_ylim()[1])
            minx = min(ax.get_xlim()[0],ax.get_xlim()[1])
        
            miny = min(ax.get_ylim()[0],ax.get_ylim()[1])
            maxt = max(maxx,maxy)
            mint = max(minx,miny)
            ax.plot(np.linspace(mint,maxt,50), np.linspace(mint,maxt,50), linestyle='--', color='grey', linewidth=2, zorder=-1)
            RMSE = np.sqrt(np.nanmean((res_dat['tobs_mean']-res_dat['tsim_'+choice])**2))
            ax.annotate('RMSE = '+str(round(RMSE,1)), (10, 90), fontsize=10)    
            ax.set_title(model_name, fontsize=8)
            # ax.get_xaxis().set_visible(False)
            # ax.get_yaxis().set_visible(False)
            fig.tight_layout()
        except:
            pass

#%% MATRIX MODELS

choice = 'max'

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

fig, ax = plt.subplots(1,1, figsize=(5,4.5))
ax.scatter(df_explo['porosity_value'], 
            1/df_explo['cond_decay_cal'],
            c=df_explo['RMSE_'+choice], s=100, marker='s')
ax.set_xlabel('Porosity')
ax.set_ylabel('1/Decay')

fig, ax = plt.subplots(1,1, figsize=(5,5))
x_col = 'porosity_value'
y_col = '1_cond_decay_cal'
z_col = 'RMSE_'+choice
df_explo_filt = df_explo.copy()
df_explo_filt['1_cond_decay_cal'] = 1/df_explo_filt['cond_decay_cal']
# df_explo_filt = df_explo_filt[~df_explo_filt['bottom_cal'].isna()]
# df_explo_filt = df_explo_filt.reset_index()
p1 = df_explo_filt[x_col]
p2 = df_explo_filt[y_col]
p2[p2==np.inf] = 0
p3 = str(p1)+';'+str(p2)
X, Y = np.meshgrid(p1, p2)
Z = np.zeros((len(p1),len(p2)))
compt=0
for i in range(len(p1)):
    for j in range(len(p2)):
        try:
            Z[j][i] = df_explo_filt[(df_explo_filt[x_col]==df_explo_filt.loc[i,x_col])&
                                    (1/df_explo_filt[y_col]==1/df_explo_filt.loc[j,y_col])][z_col]
        except:
            pass
ax.contourf(X,Y,Z, cmap='jet') #figadd.cmap_white_jet() levels=np.arange(0,51,5)
# ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud')
ax.set_xlabel('Porosity')
ax.set_ylabel('1/Decay')
# ax.set_xscale('log')
# ax.set_yscale('log')

#%% RMSE MODELS

choice = 'mean'

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

# df_explo = df_explo[2*10:5*10]
# df_explo = df_explo[:2*10]
# df_explo = df_explo[5*10:8*10]
# df_explo = df_explo[8*10:]

fig, ax = plt.subplots(1,1, figsize=(5,4))
id_compt_model = df_explo['compt_model'].unique()
n = len(id_compt_model)
cmap = cm.get_cmap('jet', n)
colors = pl.cm.jet(np.linspace(0,1,n))
for i, ind in enumerate(id_compt_model):
    mask = df_explo[df_explo['compt_model']==ind]
    label = round(1/mask['cond_decay_cal'].values[0], 1)
    color=colors[i]
    if ind == 0:
        label = 'constant'
        color='k'
    if ind == 1:
        label = 'flat'
        color='dimgray'
    # if i == 11:
    ax.plot(mask['porosity_value']*100, mask['RMSE_'+choice], lw=2,
            color=color, marker='o',
            label=label)
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('Porosity')
ax.set_ylabel('RMSE')
ax.legend(loc='best', ncol=2, )
# ax.set_xlim(0.2,20)
# ax.set_ylim(10,100)

fig, ax = plt.subplots(1,1, figsize=(5,4))
id_compt_model = df_explo['compt_model'].unique()
n = len(id_compt_model)
cmap = cm.get_cmap('jet', n)
colors = pl.cm.jet(np.linspace(0,1,n))
for i, ind in enumerate(id_compt_model):
    mask = df_explo[df_explo['compt_model']==ind]
    label = round(1/mask['cond_decay_cal'].values[0], 1)
    color=colors[i]
    if ind == 0:
        label = 'constant'
        color='k'
    if ind == 1:
        label = 'flat'
        color='dimgray'
    # if i == 11:
    ax.plot(mask['porosity_value']*100, mask['RMSE_'+choice], lw=2,
            color=color, marker='o',
            label=label)
# ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('Porosity')
ax.set_ylabel('RMSE')
ax.legend(loc='best', ncol=2, )
# ax.set_ylim(20, 100)
# ax.set_xlim(0.2,20)
# ax.set_ylim(10,100)

#%% SIM/OBS EACH SPRINGS

choice = 'mean'

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

for point in res_dat['id']:
    
    if (point == 'S03') | (point == 'S27'):

        fig, ax = plt.subplots(1,1, figsize=(3.5,2.5))
        id_compt_model = df_explo['compt_model'].unique()
        n = len(id_compt_model)
        cmap = cm.get_cmap('jet', n)
        colors = pl.cm.jet(np.linspace(0,1,n))
        for i, ind in enumerate(id_compt_model):
            mask = df_explo[df_explo['compt_model']==ind]
            label = round(1/mask['cond_decay_cal'].values[0], 1)
            color=colors[i]
            if i == 0:
                label = 'constant'
                color='k'
            if i == 1:
                label = 'flat'
                color='dimgray'
            ax.plot(mask['porosity_value']*100, mask[point+'_comp_'+choice],
                    color=color, marker='o', ms=4, mec='none',
                    label=label)
        ax.set_xscale('log')
        ax.set_yscale('log')
        # ax.set_xlabel('Porosity')
        # ax.set_ylabel(point+'sim / '+point+'obs')
        # ax.legend(loc='upper left', ncol=2)
        ax.set_xlim(0.3,30)
        ax.set_ylim(1e-2,1e2)
        ax.axhline(y=1, color='k', ls='--', lw=2)

#%% SIM/OBS ALL SPRINGS

choice = 'mean'

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

fig, ax = plt.subplots(1,1, figsize=(3.8,2.8))
id_compt_model = df_explo['compt_model'].unique()
n = len(id_compt_model)
cmap = cm.get_cmap('spring_r', n)
colors = pl.cm.jet(np.linspace(0,1,n))
for i, ind in enumerate(id_compt_model):
    res_mix = pd.DataFrame()
    mask = df_explo[df_explo['compt_model']==ind]
    label = round(1/mask['cond_decay_cal'].values[0], 1)
    color=colors[i]
    if i == 0:
        label = 'constant'
        color='k'
    if i == 1:
        label = 'flat'
        color='dimgray'
    for point in res_dat['id']:
        res_mix['porosity_value'] = list(mask['porosity_value'])
        res_mix[point+'_comp_'+choice] = list(mask[point+'_comp_'+choice])
    res_mix['all_mean'] = res_mix.iloc[:,1:].mean(axis=1)

    ax.plot(res_mix['porosity_value']*100, 
            res_mix['all_mean'], lw=1.5,
            color=color, marker='o', ms=4, mec='none',
            label=label)
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('Porosity')
ax.set_ylabel('tsim / '+'tobs')
# ax.legend(loc='upper left', ncol=2)
ax.set_xlim(0.3,30)
ax.set_ylim(1e-2,1e2)
ax.axhline(y=1, color='k', ls='--', lw=2)

#%% EXTRAC RESIDENCE SEEAPGE

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

choice = 'mean'
shp_catch = gpd.read_file(BV.geographic.watershed_shp)

res_times = pd.DataFrame(columns=['model_name'])
res_times.loc[0] = np.nan
for i, model_name in enumerate(list_model_name):
    path_pathlines = simulations_folder+model_name+'/'+'_pathlines/'
    time_shp = gpd.read_file(path_pathlines+'ending_years_masked.shp')

    time_shp = time_shp.clip(shp_catch)
    
    time_mean = time_shp.time.mean()
    time_media = time_shp.time.median()
    
    print(model_name, time_mean)

    res_times.loc[i,'model_name'] = model_name
    res_times.loc[i,'porosity_value'] = float(model_name.split('-')[-1])
    res_times.loc[i,'compt_model'] = int(model_name.split('_')[1])
    res_times.loc[i,'end_tmean'] = time_mean
    res_times.loc[i,'end_tmedia'] = time_media

#%% SIM/OBS ALL SEEPAGE

fig, ax = plt.subplots(1,1, figsize=(3.8,2.8))
id_compt_model = res_times['compt_model'].unique()
n = len(id_compt_model)
cmap = cm.get_cmap('spring_r', n)
colors = pl.cm.jet(np.linspace(0,1,n))
for i, ind in enumerate(id_compt_model):
    res_mix = pd.DataFrame()
    mask = res_times[res_times['compt_model']==ind]
    # label = round(1/mask['cond_decay_cal'].values[0], 1)
    color=colors[i]
    if i == 0:
        # label = 'constant'
        color='k'
    if i == 1:
        # label = 'flat'
        color='dimgray'
    ax.plot(mask['porosity_value'], 
            mask['end_tmean']/42, lw=1.5,
            color=color, marker='o', ms=4, mec='none')
    
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('Porosity')
ax.set_ylabel('tsim / '+'tobs')
# ax.legend(loc='upper left', ncol=2)
# ax.set_xlim(0.3,30)
# ax.set_ylim(1e-2,1e2)
ax.axhline(y=1, color='k', ls='--', lw=2, alpha=1, zorder=10)

#%% BOXPLOTS BY SPRINGS

# choices = ['min','q10','q25','mean','media','q75','q90','max']
choices = ['mean']

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

with open(simulations_folder+'/'+'_dic_res_RT_'+typ, 'rb') as f:
    dic_res = pickle.load(f)

# for i in range(12):
# mask = list(filter(lambda score: score.split('_')[1] == str(i), dic_res))

# color_dict = dict(zip(sce_list, sce_color))
         
# from mycolorpy import colorlist as mcp
# import numpy as np
# color1=mcp.gen_color(cmap="winter",n=5)

for cs in choices:
    
    print(cs)

    fig, axs = plt.subplots(3,2, figsize=(6.5,7))
    axs = axs.ravel()
    
    n = len(list_porosity)
    cmap = cm.get_cmap('RdYlGn', n)
    colors = pl.cm.jet(np.linspace(0,1,n))
    
    for k, point in enumerate(res_dat['id']):
                
        ax = axs[k]
        
        for model_name in list_model_name[:]:
            # print(model_name)
            
            por = float(model_name.split('_')[-2].split('-')[1])
            mod = int(model_name.split('_')[1])+1
            
            t=dic_res[model_name]
            tp=t[t['id']==point]
            
            ax.scatter(mod, tp['tsim_'+cs], cmap='RdYlGn_r', c=por, lw=0.5,
                       norm=mpl.colors.LogNorm(vmin=0.3, vmax=30))
            ax.set_title(point)
            
            ax.set_xlim(0, 13)
            ax.set_ylim(0.1, 1000)
            ax.set_yscale('log')
            ax.set_xticks([1,2,3,4,5,6,7,8,9,10,11,12])
            ax.set_xticklabels([1,2,3,4,5,6,7,8,9,10,11,12])
            
            ax.axhline(y=40, ls='--', c='k')
            
        fig.suptitle(cs.upper())
        fig.tight_layout()
        
        # fig.savefig(simulations_folder+'/_figures/'+
        #             'boxplot_'+cs+'.png', dpi=300, bbox_inches='tight')
        
#%% BOXPLOTS BY S03/S27

# choices = ['min','q10','q25','mean','media','q75','q90','max']
choices = ['media']

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

with open(simulations_folder+'/'+'_dic_res_RT_'+typ, 'rb') as f:
    dic_res = pickle.load(f)

# for i in range(12):
# mask = list(filter(lambda score: score.split('_')[1] == str(i), dic_res))

# color_dict = dict(zip(sce_list, sce_color))
         
# from mycolorpy import colorlist as mcp
# import numpy as np
# color1=mcp.gen_color(cmap="winter",n=5)

for cs in choices:
    
    print(cs)

    
    n = len(list_porosity)
    cmap = cm.get_cmap('RdYlGn', n)
    colors = pl.cm.jet(np.linspace(0,1,n))
    
    for k, point in enumerate(['S03', 'S27']):
        
        fig, ax = plt.subplots(1,1, figsize=(3.5,2.5))
        
        for model_name in list_model_name[:]:
            # print(model_name)
            
            por = float(model_name.split('-')[-1])
            mod = int(model_name.split('_')[1])+1
            
            t=dic_res[model_name]
            tp=t[t['id']==point]
            
            # if point=='S03':
            #     tobs = 44
            # if point=='S27':
            #     tobs = 42
            
            ax.scatter(mod, tp['tsim_'+cs], cmap='viridis_r', c=por, lw=0.5,
                       marker='s', 
                       norm=mpl.colors.LogNorm(vmin=0.3, vmax=30))
            ax.set_title(point)
            
            ax.set_xlim(0, 13)
            ax.set_ylim(0.1, 1000)
            ax.set_yscale('log')
            ax.set_xticks([1,2,3,4,5,6,7,8,9,10,11,12])
            ax.set_xticklabels([1,2,3,4,5,6,7,8,9,10,11,12])
            
            ax.axhline(y=40, ls='--', c='k', zorder=-1)
            
        # fig.suptitle(cs.upper())
        fig.tight_layout()
        
        # fig.savefig(simulations_folder+'/_figures/'+
        #             'boxplot_'+cs+'.png', dpi=300, bbox_inches='tight')

#%% BOXPLOTS BY MODELS

model_name = 'egu1_4_20.0-0.0-0.1359-10.8'

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

with open(simulations_folder+'/'+'_dic_res_RT_'+typ, 'rb') as f:
    dic_res = pickle.load(f)

# list_selects = ['egu1_3_15.0-0.0-0.1908-10.8', 'egu1_8_100.0-0.0-0.0211-3.9']
list_selects = ['explor1_3_0.0_0.1908-10.8_15.0-30.0', 'explor1_8_0.0_0.0211-3.9_100.0-200.0']

for model_name in list_selects[:]:

    dic_sel = dic_res[model_name]
    
    fig, ax = plt.subplots(1,1, figsize=(4,2))
    
    ax.vlines(dic_sel.id, dic_sel.tsim_min, dic_sel.tsim_q10, lw=1.5, color='grey', 
              zorder=-1,
              )
    ax.vlines(dic_sel.id, dic_sel.tsim_q90, dic_sel.tsim_max, lw=1., color='grey', 
              zorder=-1,
              )
    
    ax.scatter(dic_sel.id, dic_sel.tobs_mean, marker='o', c='w', s=60, lw=1.5)
    
    ax.vlines(dic_sel.id, dic_sel.tsim_q10, dic_sel.tsim_q90, alpha=0.75,
              lw=6, color='grey', zorder=-1)
    
    # ax.scatter(dic_sel.id, dic_sel.tsim_q10, marker='_', c='k', zorder=2, s=50, lw=2)
    # ax.scatter(dic_sel.id, dic_sel.tsim_q90, marker='_', c='k', zorder=2, s=50, lw=2)
    # ax.scatter(dic_sel.id, dic_sel.tsim_media, marker='^', c='darkorange', s=40)
    ax.scatter(dic_sel.id, dic_sel.tsim_mean, marker='^', c='violet', s=70, lw=1.5)
    ax.scatter(dic_sel.id, dic_sel.tsim_min, marker='_', c='grey', s=20)
    ax.scatter(dic_sel.id, dic_sel.tsim_max, marker='_', c='grey', s=20)
    
    ax.set_ylim(0.1, 1000)
    
    ax.set_title(model_name, fontsize=9)
    # ax.set_ylim(0.1,100)
    ax.set_yscale('log')

#%% AGE BY MODELS

choice = 'max'

df_explo = pd.read_csv(simulations_folder+'res_'+typ+'.csv', sep=';')

points = res_dat.id

for i in range(12):

    df_plot = df_explo[df_explo['compt_model']==i]
        
    fig, ax = plt.subplots(1,1, figsize=(5,4.5))

    for point in points:
        print(point)
        ax.plot(df_plot.porosity_value*100, df_plot[point+'_sim_'+choice],
                   # c=df_plot['porosity_value']
                   label=point
                   )
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.legend(loc='upper left', ncol=2)
        ax.set_title(df_plot['model_name'].values[0])
    # ax.set_ylim(0.1, 1000)
    # ax.set_ylim(0.2, 20)
    ax.set_xlabel('Porosity')
    ax.set_ylabel('Age sim [y]')
    
    ax.axhline(40, ls='--', c='k')
    ax.set_ylim(0.1, 1000)

#%% TRY CROSS PATHLINES

model_name = 'egu1_4_20.0-0.0-0.1359-10.8'

# fig, ax = plt.subplots(1,1, figsize=(7, 3))
# modelmap = flopy.plot.PlotMapView(model=mf)
# linecollection = modelmap.plot_grid(linewidth=0.5, color='royalblue')
# line_cross = np.array([(40, 80), (100, 50)])
# xsect = flopy.plot.PlotCrossSection(model=mf, line={'line': line_cross})

mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')

fname = simulations_folder+model_name+'/'+model_name+'.hds'
gridname = simulations_folder+model_name+'/'+model_name+'.dis'
# grid_model = flopy.discretization.grid.Grid(mf)
grid_model = mf.modelgrid
hk_grid = mf.upw.hk

# sr_model = flopy.utils.reference.SpatialReference()
fig, ax = plt.subplots(1, 1, figsize=(10, 5))
# ax = fig.add_subplot(1, 1, 1)

xsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})

# xsect = flopy.plot.PlotCrossSection(model=mf, line={'row': 50})
linecollection = xsect.plot_grid(color='k', alpha=0.25, lw=1)

xsect.get_extent()
# xsect.plot_bc()
hdobj = flopy.utils.HeadFile(fname)
head = hdobj.get_data()
xsect.plot_fill_between(head, color='saddlebrown', edgecolor='none', alpha=0.25)
pc = xsect.plot_array(head,
                      masked_values=[-9999.0], head=head, alpha=0.25,
                      cmap = 'Blues', lw=0,
                      vmin=0, vmax=400)
# patches = xsect.plot_ibound(head=head)
# linecollection = xsect.plot_grid()
cb = plt.colorbar(pc, shrink=0.75)
ax.set_ylim(1000,2400)
xlims = ax.get_xlim()
# ax.set_xlim(150,1000)

# head_profile = pc.get_array()[0:170]

# xsect.plot_pathline(pth_data[3000:3001], method='all', colors='k',
#                     head=pc.get_array())
# xsect.plot_endpoint(e, direction='ending')

for a, b in enumerate(random.sample(pth_data, 1000)):
    b_xmin = b.x.min()/10
    b_xmax = b.x.max()/10
    # head_restr = head_profile[int(b_xmin):int(b_xmax)]
    # if b.particleid[0] in np.random.choice(indices_layers[0], 100):
    # if b.particleid[0] in indices_layers[0]:
    # if b.particleid[0] in id_particules_random:
    if b.particleid[0] in sp_particules:
    # if b.particleid[0] in id_particules_random:
    # if b.particleid[0] in random.sample(pth_data, 5000):
        # if len(head_restr)>0:
        #     head_max = head_restr.max()
        #     if b.z.max()<head_max:
        ax.plot(b.x, b.z, color='red', lw=1)
    # if b.particleid[0] in np.random.choice(indices_layers[1], 100):
    # if b.particleid[0] in indices_layers[1]:
    # if b.particleid[0] in id_layers_random[1]:
    #     # if len(head_restr)>0:
    #     #     head_max = head_restr.max()
    #     #     if b.z.max()<head_max:
    #     ax.plot(b.x, b.z, color='blue', lw=0.5)

#%% ---- DISCHARGE SET

#%% Q DATA

area = BV.geographic.area

if not os.path.exists(stable_folder+'/climatic/_REC_D.csv'):
    BV.add_surfex(surfex_path)
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2019, time_step = 'D',
                                  sim_state='transient') #
BV.forcing.update_runoff_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2019, time_step = 'D',
                                  sim_state='transient') #
R_rea = BV.forcing.recharge * 1000
r_rea = BV.forcing.runoff * 1000

data_path_lasset = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/LASSET/data/"

if not "cdt" in globals():
    cdt = pd.read_csv(data_path_lasset+'data_ctd_lasset.dat',
                      index_col='date',
                      parse_dates=True)
cdt_d = pd.DataFrame()
cdt_d['Q_L/s'] = cdt['discharge_Ls'].resample('D').mean()
cdt_d['Q_L/d'] = cdt_d['Q_L/s'] * 3600 * 24
cdt_d['Q_m3/d'] = cdt_d['Q_L/d'] / 1000
cdt_d['Q_m/d'] = cdt_d['Q_m3/d'] / (area*1e6)
cdt_d['Q_mm/d'] = cdt_d['Q_m/d'] * 1000

cdt_d.to_csv(data_path_lasset+'Q_lasset_units.csv', sep=';')

print(cdt_d.resample('Y').sum())

if not "cms" in globals():
    cms = pd.read_csv(data_path_lasset+'lasset_Q_Day.Cms.txt',
                      sep=';', index_col='date_temp',
                      parse_dates=True)
    # m3/s

cms_d = pd.DataFrame()
cms_d['Q_m3/s'] = cms['Q_cms'].resample('D').mean()
cms_d['Q_m3/d'] = cms_d['Q_m3/s'] * 3600 * 24
cms_d['Q_m/d'] = cms_d['Q_m3/d'] / (area*1e6)
cms_d['Q_mm/d'] = cms_d['Q_m/d'] * 1000

print(cms_d.resample('Y').sum())

def fmt_xaxes(ax,
              loc_years_maj,
              loc_years_min,
              loc_months_maj,
              loc_months_min):
    yearsmaj = mdates.YearLocator(loc_years_maj)   # every year
    yearsmin = mdates.YearLocator(loc_years_min)
    years_fmt = mdates.DateFormatter('%Y')
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_major_formatter(years_fmt)
    
    monthsmaj = mdates.MonthLocator(loc_months_maj)  # every month
    monthsmin = mdates.MonthLocator(loc_months_min)
    months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    ax.xaxis.set_minor_locator(monthsmaj)
    ax.xaxis.set_minor_formatter(months_fmt)

fig, ax = plt.subplots(1,1, figsize=(6,3))
# axb = ax.twinx()

ax.plot(cdt_d['Q_mm/d'])
# ax.set_ylim(0, 1000)
ax.set_yscale('log')
ax.set_xlabel('Date')
ax.set_ylabel('Q [mm/d]')

yearsmaj = mdates.YearLocator(1)   # every year
yearsmin = mdates.YearLocator(1)
years_fmt = mdates.DateFormatter('%Y')
ax.xaxis.set_major_locator(yearsmaj)
ax.xaxis.set_major_formatter(years_fmt)

monthsmaj = mdates.MonthLocator()  # every mont
monthsmin = mdates.MonthLocator()
months_fmt = mdates.DateFormatter('%m') #b = name of month ?
ax.xaxis.set_minor_locator(mdates.MonthLocator())
# ax.xaxis.set_minor_formatter(months_fmt)

# axb.plot(cms['Q_cms'])
# axb.set_yscale('log')

Qobs = R_rea + r_rea

Qobs_mean = Qobs.mean()
cdt_d_mean = cdt_d['Q_mm/d'].mean()
f = cdt_d_mean / Qobs_mean
print(f)

Qobs = Qobs * f

Qobs = Qobs.rename('Q')
Qobs = select_period(Qobs, 1960, 2019)
data_index = Qobs.copy()
mean_mensual = data_index.resample('M').mean() # mensual mean
mean_annual = data_index.resample('Y').mean() # annual mean
Mean = round(data_index.mean(),2)
Mean = data_index.mean()
Min = data_index.resample('Y').min()
Q10 = data_index.resample('Y').quantile(0.10)
Q25 = data_index.resample('Y').quantile(0.25)
Q50 = data_index.resample('Y').quantile(0.50)
Q75 = data_index.resample('Y').quantile(0.75)
Q90 = data_index.resample('Y').quantile(0.90)
print(Q10.min())
print(Q90.mean())
Max = data_index.resample('Y').max()
mean_interan_days = data_index.groupby([data_index.index.month,
                                data_index.index.day], as_index=True).mean().to_frame()
std_interan_days = data_index.groupby([data_index.index.month,
                    data_index.index.day], as_index=True).std()
q10_interan_days = data_index.groupby([data_index.index.month,
                    data_index.index.day], as_index=True).quantile(0.10)
q90_interan_days = data_index.groupby([data_index.index.month,
                    data_index.index.day], as_index=True).quantile(0.90)
q50_interan_days = data_index.groupby([data_index.index.month,
                    data_index.index.day], as_index=True).quantile(0.50)
mean_interan_days['std'] = std_interan_days
mean_interan_days['q10'] = q10_interan_days
mean_interan_days['q90'] = q90_interan_days
mean_interan_days['q50'] = q50_interan_days
mean_interan_days.index.names = ['months','days']
mean_interan_days = mean_interan_days.reset_index()
mean_interan_days = mean_interan_days.sort_values(['months','days'])
mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))

# 2021
c = select_period(cdt_d, 2021, 2021)
Q2021 = c.groupby([c.index.month,
                    c.index.day], as_index=True).mean()
Q2021['counts'] = np.array(range(1,len(Q2021)+1))+c.index[0].timetuple().tm_yday

# 2022
c = select_period(cdt_d, 2022, 2022)
Q2022 = c.groupby([c.index.month,
                    c.index.day], as_index=True).mean()
Q2022['counts'] = np.array(range(1,len(Q2022)+1))+c.index[0].timetuple().tm_yday

# 2023
c = select_period(cdt_d, 2023, 2023)
Q2023 = c.groupby([c.index.month,
                    c.index.day], as_index=True).mean()
Q2023['counts'] = np.array(range(1,len(Q2023)+1))+c.index[0].timetuple().tm_yday

fig, ax = plt.subplots(figsize=(4.5,3.5))
"""
ax.plot(mean_interan_days.counts, mean_interan_days.q50,
        lw=1.5, color='dimgray', label='Median')
yerrmax = mean_interan_days.q90
yerrmin = mean_interan_days.q10
ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax, lw=0.5,
                  color='cyan',edgecolor='grey',
                  alpha = 0.30, label='10-90th')
"""
# ax.plot(Q2021.counts, Q2021['Q_mm/d'],
#         lw=2, color='dodgerblue', label='Median')
ax.plot(Q2022.counts, Q2022['Q_mm/d'],
        lw=2, color='purple', label='Median')
ax.plot(Q2023.counts, Q2023['Q_mm/d'], ls='-',
        lw=2, color='darkorange', label='Median')
ax.plot(Q2023.counts[-1:]+3, Q2023['Q_mm/d'][-1:], marker='>', ms=5,
        lw=2, color='darkorange', label='Median')
plt.yscale('log')
ax.set_xlim(0,366)
ax.set_ylim(0.1,300)
ax.tick_params(axis='both', which='major', pad=10)
x1 = np.linspace(0,366,13)
squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
ax.set_xticks(x1)
ax.set_xticklabels(squad, minor=False, rotation='horizontal')
ax.set_xlabel('Months', labelpad=+10)
ax.set_ylabel('Streamflow [mm/day]',labelpad=+10)
plt.tight_layout()

#%% INTERMITTENCY PARAMS

# K_cal = df.loc[df['Dabs'].idxmin()].k * 24 * 3600
# cond_decay_cal = df.loc[df['Dabs'].idxmin()].cond_decay

df = pd.read_csv(BV.calibration_folder+'/'+dicot_name+'_'+watershed_name+'.csv', sep=';')

list_selects = ['egu1_4_20.0-0.0-0.1359-10.8', 'egu1_8_100.0-0.0-0.0211-3.9']

model_name = 'egu1_4_20.0-0.0-0.1359-10.8'
koptim_cal = 0.1359
porosity_value = 10.8 / 100
cond_decay_cal = 1 / 20
bottom_cal = 0
thickness_value = 50
######################
typ= 'Q1'
######################

model_name = 'egu1_8_100.0-0.0-0.0211-3.9'
koptim_cal = 0.0211
porosity_value = 3.9 / 100
cond_decay_cal = 1 / 100
bottom_cal = 0
thickness_value = 50
#################
typ= 'Q2'
######################

model_name = 'egu1_0_inf-None-0.0596-0.3'
koptim_cal = 0.0596
porosity_value = 0.3 / 100
cond_decay_cal = 0
bottom_cal = None
thickness_value = 50
#################
typ= 'Q3'
######################

model_name = 'egu1_3_15.0-0.0-0.1908-0.3'
koptim_cal = 0.1908
porosity_value = 0.3 / 100
cond_decay_cal = 1 / 15
bottom_cal = 0
thickness_value = 50
#################
typ= 'Q4'
######################

model_name = 'egu1_3_15.0-0.0-0.1908-0.3'
koptim_cal = 0.1908
porosity_value = 0.1 / 100
cond_decay_cal = 1 / 15
bottom_cal = 0
thickness_value = 50
#################
typ= 'Q5'
######################

iD = typ

box=True
modpath_sim=False
zone_partic='domain' # watershed
sink_fill=False
verbose=True,
post_process=False,
init_rech='mean'
verti_k=None

date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
date_today = date_today.replace('/','-')
date_today = date_today.replace(':','-')
date_today = date_today.replace(' ','_')

# Label
list_model_name = []
list_of_success = []
list_flow_model = []

# Update properties
BV.hydrodynamic.update_nlay(25) # 1
BV.hydrodynamic.update_thick_exp(1.25) # 1
BV.hydrodynamic.update_thickness(thickness_value) # 30 / intervient pas si bottom != None

BV.hydrodynamic.update_bottom(bottom_cal) # None
BV.hydrodynamic.update_cond_decay(cond_decay_cal) # 0
BV.hydrodynamic.update_hyd_cond(koptim_cal)
BV.hydrodynamic.update_porosity(porosity_value)

# Recharge
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2019, time_step = 'D',
                                  sim_state='steady') #
porosity_recharge = BV.forcing.recharge
R = pd.read_csv(data_path_lasset+'Q_lasset_units.csv', sep=';',
                       index_col='date',
                       parse_dates=True)
R = select_period(R['Q_m/d'], 2022, 2022).resample('M').mean()
R_mean = R.mean()
R = R * (porosity_recharge/R_mean)
BV.forcing.update_recharge(R, sim_state='transient')

#%% INTERMITTENCY LAUNCH

run = False

compt_model = 0

model_name = typ+'_'+str(compt_model)+'_'+\
             str(round(cond_decay_cal,1))+'-'+\
             str(bottom_cal)+'-'+\
             str(round(koptim_cal,4))+'-'+\
             str(round(porosity_value, 2))

print('SIM - ' + model_name)

success, flow_model = BV.run_modflow(run=run,
                                     ident=model_name,
                                     sink_fill=sink_fill,
                                     modpath_sim=modpath_sim,
                                     zone_partic=zone_partic,
                                     box=box,
                                     verbose=verbose,
                                     post_process=post_process, 
                                     init_rech=init_rech,
                                     verti_k=verti_k)

if success == True:
    print(     'Success')
else:
    print(     'Error')
  
list_model_name.append(model_name)
list_of_success.append(success)
list_flow_model.append(flow_model)

compt_model += 1
    
print(list_of_success)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_of_success'] = list_of_success
dictio['list_flow_model'] = list_flow_model
h5file = simulations_folder+'/'+'list_'+typ

dd.io.save(h5file, dictio)

#%% INTERMITTENCY POSTPROCESS

sim_state = 'transient' # 'steady' or 'transient'
residence_times = False
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual

# types_obs = ["lasset_stream_wetland_perennial_pt_gpdv2"]
types_obs = ["lasset_stream_update_april23_wetlands_perennial_cut_topt"]

for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
    print(success)

    BV.matrix_modflow(success,
                      flow_model,
                      first_only = True,
                      watertable_elevation = True,
                      watertable_depth = True, 
                      seepage_areas = True,
                      outflow_drain = True,
                      groundwater_flux = False,
                      specific_discharge = False,
                      accumulation_flux = True,
                      perenn_intermit_shp = False, # True
                      groundwater_storage = True,
                      residence_times = residence_times,
                      verbose = True,
                      export_tif = True)
    
    # Necessary for results_modflow
    BV.forcing.update_recharge(flow_model.climatic,
                               sim_state=sim_state)
    
    # # Extract results
    print(model_name)
    BV.results_modflow(ident=model_name,
                       actual_date=actual_date,
                       time_step=time_step)
    
    ## Plot maps
    surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
                                          model_name, types_obs,
                                          save_gif=False,
                                          first_only=True,
                                          sim_state=sim_state,
                                          outflow=True,
                                          accflux=True,
                                          intermittency=False,
                                          chronics=False)

#%% MAPANIM

typ_intermit = 'monthly' # yearly or persistency or monthly
# typ_intermit = 'yearly' # yearly or persistency or monthly

gif = True

for watershed_name in watershed_names[:]:
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    years = np.arange(2022,2022+1,1)
        
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'),
                       key=os.path.getmtime)
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
        
    for simul in simul_list:
    
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'),
                          allow_pickle=True).item()
        
        for key in acc_npy:
            # print(key)
            mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
            # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
            acc_npy[key] = np.ma.masked_array(acc_npy[key], mask=(mask<0))
        zero = acc_npy[0] * 0
        for l in range(len(acc_npy)):
            tempo = acc_npy[l].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy() # / len(acc_npy)
                
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        inf = 0
        sup = 12
        compt = 0
        step = int(round(len(acc_npy)/12))
        
        for i in range(step):
            print(str(i)+'/'+str(step))
            interv = list(acc_npy.items())[inf:sup]
            # print(interv)
            for key in range(len(interv)):
                # key = tupl[0]
                # print(key)
                interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                
            zero = acc_npy[0] * 0
            for j in range(len(interv)):
                tempo = interv[j].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy()
            days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
            days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
            
            if typ_intermit == 'monthly':
                if i >= 0:
                    for k in range(len(interv)):
                        to = interv[k].copy()
                        
                        to[(to>0) & (days_flux==12)] = 2
                        to[(to>0) & (days_flux<12)] = 1
                        
                        to = np.ma.masked_array(to, mask=(mask<0))
                        to = np.ma.masked_array(to, mask=(to<=0))
                        
                        fig, ax = plt.subplots(1,1, figsize=(7,6))
                        ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                        ax.imshow(np.ma.masked_where(to==1, to),
                                  cmap = mpl.colors.ListedColormap(['navy']))
                        ax.imshow(np.ma.masked_where(to==2, to),
                                  cmap = mpl.colors.ListedColormap(['dodgerblue']))
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        ax.get_xaxis().set_visible(False)
                        ax.get_yaxis().set_visible(False)
                        
                        month_print = "{:02d}".format(k+1)

                        ax.set_title(str(years[i])+'-'+(month_print))
                        
                        # path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                        # wbt.vector_lines_to_raster(path_sub,
                        #                            glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                        #                            base = stable_folder+'geographic/'+'watershed_dem.tif')
                        # line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                        # line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                        # ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('k'))
                        
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        
                        # ax.axhline(y=140, ls='--', c='k')
                        
                        # if watershed_name=='Canut':
                        #     ax.axvline(x=65, color='k', lw=1, ls='--')
                        # if watershed_name=='Nancon':
                        #     ax.axhline(y=40, color='k', lw=1, ls='--')
                        
                        # fig.savefig(simul+'/_figures/png/'+'_map_intermittent_monthly_'+str(compt)+'.png', dpi=300, bbox_inches='tight')
                        
                        compt_print = "{:02d}".format(compt)
                        print(compt_print)

                        base_name = simulations_folder+'_figures/'+'map_intermittency/'
                        spec_name = 'map_interm_'+str(compt_print)
                        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
                        
                        plt.axis('off')
                        plt.close()
                        
                        compt += 1
                        
                    inf+=12
                    sup+=12

    if gif == True:
        begin_by = simulations_folder+'_figures/'+'map_intermittency/'+'map_interm_'
        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
        images = []
        for filename in filenames:
            images.append(imageio.imread(filename))
        gif_name = '_map_interm'
        imageio.mimsave(base_name+gif_name+'.gif', images,
                        duration=0.5, loop=0)

#%% CROSSANIM

watershed_name = 'Lasset_egu'

gif = True

dates = pd.date_range(start='01/01/2022', end='31/12/2022', freq='M')

sens = 'horiz'
# sens = 'verti'
res = 25

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data

list_path = sorted(glob.glob(simulations_folder+iD+'*'),
                    key=os.path.getmtime, reverse=True)
model_name = list_path[-1].split('\\')[-1]

mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')

import itertools            

watertable_elevation = np.load(simulations_folder+model_name+'/_watershed/'+'watertable_elevation'+'.npy', allow_pickle=True).item()

c = 0
cp = 0
dict_min_wt = {}
dict_res_both = {}
for key in dict(itertools.islice(watertable_elevation.items(),
                                 len(watertable_elevation)-12*1, # ONDE 8 years
                                 len(watertable_elevation))):
    print(key)
    dem_data = imageio.imread(BV.geographic.watershed_dem)
    # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
    wt_data = watertable_elevation[key]
    wt_data = np.ma.masked_where(wt_data < 0, wt_data)
    # river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
    # print(key)
    # print(c)
    dict_min_wt[c] = wt_data.mean()
    c+=1
    if c == 12:
        print('YES')
        c=0
        minval = min(dict_min_wt.values())
        res = [k for k, v in dict_min_wt.items() if v==minval]
        res = list(filter(lambda x: dict_min_wt[x]==minval, dict_min_wt))
        res_both = min(dict_min_wt.items(), key=lambda x: x[1])
        # print(res_both)
        dict_res_both[cp] = res_both
        cp+=1
        
cb = 0
cpb = 0
cpy = 0

compt_print = 0

for key in dict(itertools.islice(watertable_elevation.items(),
                                 len(watertable_elevation)-12*1, # ONDE 8 years
                                 len(watertable_elevation))):

    dem_data = imageio.imread(BV.geographic.watershed_dem)
    # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
    wt_data = watertable_elevation[key]
    wt_data = np.ma.masked_where(wt_data < 0, wt_data)
    # river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
    
    # print(cpb)
    cb+=1
    if cpb == 12:
        cb=0
        cpb=0
        # print(cpy)
        cpy+=1
    res_both = dict_res_both[cpy]
    print(cpb, cpy, res_both)
    cpb+=1

    xvalues = np.linspace(-1,1,dem_data.shape[1])
    yvalues = np.linspace(-1,1,dem_data.shape[0])
    xx, yy = np.meshgrid(xvalues,yvalues)
    
    cur_x = int(dem_data.shape[1] /2)
    cur_x = 135
    cur_y = int(dem_data.shape[0] /2)
    # cur_y = 100
    
    dem_max = dem_data.max()
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    
    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    
    if sens == 'horiz':
        dem_h_plot = dem_prof[int(cur_y),:]
        dem_h_plot[dem_h_plot == 0] = np.nan
        wt_h_plot = wt_prof[int(cur_y),:]
        wt_h_plot[wt_h_plot == 0] = np.nan

        wt_prof_min = watertable_elevation[res_both[0]].astype(float)
        wt_prof_min[wt_prof_min<0] = np.nan
        wt_h_plot_min = wt_prof_min[int(cur_y),:]
        wt_h_plot_min[wt_h_plot_min == 0] = np.nan
            
    if sens == 'verti':
        dem_v_plot = dem_prof[:,int(cur_x)]
        dem_v_plot[dem_v_plot == 0] = np.nan
        wt_v_plot = wt_prof[:,int(cur_x)]
        wt_v_plot[wt_v_plot == 0] = np.nan

        wt_prof_min = watertable_elevation[res_both[0]].astype(float)
        wt_prof_min[wt_prof_min<0] = np.nan
        wt_v_plot_min = wt_prof_min[:,int(cur_x)]
        wt_v_plot_min[wt_v_plot_min == 0] = np.nan
             
    dem_max = dem_data.max()
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))

    fig, ax = plt.subplots(1, 1, figsize=(5,3.5), dpi=300)

    if sens == 'horiz':
        wt_v_fill = ax.fill_between(np.arange(xx.shape[1])*res, dem_h_plot-3000, wt_h_plot_min,
                                            color='navy', alpha=0.5, lw=0)
        store_w_c_plot = wt_h_plot_min.copy()
        # store_w_c_plot = wt_h_plot.copy()
        
        wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*res, dem_h_plot-3000, wt_h_plot,
                                        color='dodgerblue', alpha=0.5, lw=0)
        w_prof = ax.plot(np.arange(xx.shape[1])*res, wt_h_plot, color='dodgerblue', lw=1)
        w_prof = ax.plot(np.arange(xx.shape[1])*res, wt_h_plot_min, color='navy', lw=1)
        wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*res, wt_h_plot, dem_h_plot,
                                        color='saddlebrown', alpha=0.5, lw=0)
        d_prof = ax.plot(np.arange(xx.shape[1])*res, dem_h_plot, 'saddlebrown', lw=1.5)
        ax.fill_between(np.arange(xx.shape[1])*res, 0, dem_h_plot-3000,
                                        color='lightgrey', alpha=0.5, lw=0)
        ax.plot(np.arange(xx.shape[1])*res, dem_h_plot-3000, color='dimgray', lw=1.5)
        
        ax.set_xlim(800, 1200)
        ax.set_ylim(1550, 1750)
        ax.set_yticks([1600, 1650, 1700])
        ax.set_xticks([1200, 1000, 800])
        ax.set_xticklabels(['','',''])
        
        ax.invert_xaxis()
               
    if sens == 'verti':
        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*res, dem_v_plot-3000, wt_v_plot_min,
                                            color='navy', alpha=0.5, lw=0)
        w_prof = ax.plot(np.arange(xx.shape[0])*res, wt_v_plot_min, color='navy', lw=1)
        store_w_c_plot = wt_v_plot_min.copy()
        # store_w_c_plot = wt_v_plot.copy()
        
        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*res, dem_v_plot-3000, wt_v_plot,
                                            color='dodgerblue', alpha=0.5, lw=0)
        w_prof = ax.plot(np.arange(xx.shape[0])*res, wt_v_plot, color='dodgerblue', lw=1)
        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*res, wt_v_plot, dem_v_plot,
                                        color='saddlebrown', alpha=0.5, lw=0)
        d_prof = ax.plot(np.arange(xx.shape[0])*res, dem_v_plot, 'saddlebrown', lw=1.5)
        ax.fill_between(np.arange(xx.shape[0])*res, 0, dem_v_plot-3000,
                                        color='lightgrey', alpha=0.5, lw=0)
        ax.plot(np.arange(xx.shape[0])*res, dem_v_plot-3000, color='dimgray', lw=1.5)
        
        ax.set_ylim(1500, 2200)
        ax.set_xlim(500, 1500)
        # ax.set_ylim(1600, 2400)
        # ax.set_yticks([90,100,110,120,130])
                      
    ax.set_title(str(dates[key])[:7])
    
    plt.tight_layout()

    base_name = simulations_folder+'_figures/'+'cross_intermittency/'
    spec_name = 'cross_interm_'+str(compt_print)
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
    
    compt_print += 1
    
    # plt.close()

if gif == True:
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    list_path = sorted(glob.glob(simulations_folder+iD+'*'),
                        key=os.path.getmtime)
    model_name = list_path[-1].split('\\')[-1]
    begin_by = simulations_folder+'_figures/'+'cross_intermittency/'+'cross_interm_'
    filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    gif_name = '_cross_interm'
    imageio.mimsave(base_name+gif_name+'.gif', images,
                    duration=0.5, loop=0)

#%% SATURATION GRAPH

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

BV.add_forcing()

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots

simul_list = sorted(glob.glob(simulations_folder+iD+'*'), key=os.path.getmtime)

for simul in simul_list:
    model_name = simul.split('\\')[-1]

    Smod_path = simul+'/_watershed/_simulated_results.csv'
    Smod_raw = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    
    Smod_raw.index = R.index
    Smod_raw['R'] = R
    Smod_raw['mois'] = Smod_raw.index.month
    
    Smod = Smod_raw.copy()
    
    for i in np.arange(1, 13, 1):
        print(i)
        
        # Smod = Smod_raw[:i]
        
        fig, ax = plt.subplots(1,1, figsize=(5,3))
        axb = ax.twinx()
        
        step = 'pre'
        step = 'mid'
        
        axb.bar(Smod.mois, Smod.R*1000*30, color='orchid', edgecolor='purple', lw=0, alpha= 0.5,
                width=1)
        axb.bar(Smod.mois, Smod.R*1000*30, facecolor="None", edgecolor='purple', lw=2, alpha= 1,
                width=1)
        axb.set_ylim(0, 600)
        axb.invert_yaxis()
        axb.set_yticks([0,200, 400, 600])
        axb.set_yticklabels([0, 200, ' ', ' '])
        
        ax.fill_between(Smod.mois, 0, Smod['perenn_areas'],
                        interpolate=False, color='navy', alpha=0.5,
                        step=step)
        ax.fill_between(Smod.mois, 0, Smod['surflow_areas'],
                        interpolate=False, color='dodgerblue', alpha=0.5,
                        step=step)
        ax.step(Smod.mois, Smod['surflow_areas'], color='dodgerblue',
                marker=None, markeredgecolor='none',
                markersize=5, lw=2, label='upstream',
                where=step)
        ax.step(Smod.mois, Smod['perenn_areas'], color='navy',
                marker=None, markeredgecolor='none',
                markersize=5, lw=2, label='upstream',
                where=step)
        
        # ax.fill_between(Smod.mois, 0, Smod['surflow_areas'],
        #                 interpolate=False, color='dodgerblue', alpha=0.5,
        #                 step=step
        #                 )
        # ax.fill_between(Smod.mois, 0, Smod['perenn_areas'],
        #                 interpolate=False, color='navy', alpha=0.5,
        #                 step=step
        #                 )
    
        # ax.grid('grey', axis='x')
        ax.set_ylim(5, 20)
        ax.set_yticks([5, 10, 15, 20])
        ax.set_yticklabels([5, 10, 15, 20])
        
        # ax.set_yticks(np.arange(0,15.05,2.5))
        ax.set_ylabel('Months')
        ax.set_ylabel('$A_{sat}$ [%]')
        # ax.set_xlim(pd.to_datetime('2022'), pd.to_datetime('2022'))
    
        # yearsmaj = mdates.YearLocator(1)   # every year
        # yearsmin = mdates.YearLocator(1)
        # years_fmt = mdates.DateFormatter('%Y')
        # ax.xaxis.set_major_locator(yearsmaj)
        # ax.xaxis.set_major_formatter(years_fmt)
    
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        # ax.xaxis.set_major_locator(mdates.MonthLocator())
        # ax.xaxis.set_major_formatter(months_fmt)
        
        ax.set_xticks(np.arange(1,13,1))
        ax.set_xticklabels(np.arange(1,13,1))
        ax.set_xlim(1,12)
        
        ax.axvline(x=i, ls='--', lw=1.5, c='k', zorder=10)
    
        ax.set_title(i)
    
        plt.tight_layout()
        
        base_name = simulations_folder+'_figures/'+'graph_intermittency/'
        spec_name = 'graph_interm_'+str(i)
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
if gif == True:
    begin_by = simulations_folder+'_figures/'+'graph_intermittency/'+'graph_interm_'
    filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    gif_name = '_graph_interm'
    imageio.mimsave(base_name+gif_name+'.gif', images,
                    duration=0.5, loop=0)

#%% ---- VRAC : PATHLINES

#%% TESTS

#['nlay', 'thickness', 'bottom', 'cond_decay', 'thick_exp']
['thickness', 'bottom', 'cond_decay']

thick_exp = 1.25

dc = np.logspace(np.log10(1/20),np.log10(1/200),3)

case_list = ['case1', 'case2', 'case3', 'case4', 'case5']

prop_list = [[50, None, 0], [50, 1000, 0], [50, 1000, dc[0]], [50, 1000, dc[1]],  [50, 1000, dc[2]]]

porosity_list = np.linspace(0.1, 0.3, 9)

#case_list = ['caseg']
#prop_list = [[50, 1000, 1/20]]

#porosity_list = [0.15]

#%% INIT CALIB DICHOTOMY STREAMS

# names_params_dict = dict(zip(names_list, params_list))

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

watershed_names = ['Lasset']

for watershed_name in watershed_names[:] :
    
    # types_obs = ['zhstreams'] # list of shapefile name layers for clip hydrology
    types_obs = ["lasset_stream_wetland_perennial_pt_gpdv2"] # list of shapefile name layers for clip hydrology
    #types_obs = ["lasset_stream_perennialv2"]
    fields_obs = ['fid']
    
    for case, prop in zip(case_list[:], prop_list[:]):
    
        # df = pd.DataFrame(np.nan, index=range(1), columns=case_list)
        
        for type_obs, field_obs in zip(types_obs, fields_obs):
            
            print('')
            print('##### '+watershed_name.upper()+' #####')
            print(case)
            print(prop)
            print('###################################')
            print('')
            
            BV = watershed_root.Watershed(watershed_name=watershed_name,
                                          dem_path=dem_path, 
                                          out_path=out_path,
                                          load=True,
                                          modflow_path=modflow_path)
            BV.add_forcing()
            BV.add_hydrodynamic()
            BV.add_oceanic(oceanic_path)
            area = BV.geographic.area
            
            stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
                
            # BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])

            BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                              first_year = 1960, last_year=2019, time_step = 'D',
                                              sim_state='steady') #
            
            # BV.hydrodynamic.update_porosity(0.1)
            # BV.hydrodynamic.update_hyd_cond(2)
            
            # update the number of layers 
            nlay = 5
            if prop[2]>0:
                length_K_decay = prop[2]**-1
                # length_K_decay = prop[2]
                thick = 10*length_K_decay
                layer_min_thick = 5
                nlay = int(np.log(1-thick*(1-thick_exp)/layer_min_thick) / np.log(thick_exp))
                print('')
                print('changed nlay = ' + str(nlay))
                print('')

            BV.hydrodynamic.update_nlay(nlay)
            BV.hydrodynamic.update_thickness(prop[0])
            BV.hydrodynamic.update_bottom(prop[1])
            BV.hydrodynamic.update_cond_decay(prop[2])
            BV.hydrodynamic.update_thick_exp(thick_exp)
            
            params_df = pd.DataFrame(columns=['params',
                                              'init_values','lower_bounds','higher_bounds',
                                              'units','scale'])
            #params_df.loc[0] = ['k1',8.64e-01,8.64e-05,8.64e-1,'m/j','lin']
            params_df.loc[0] = ['k1',5e-02,1e-06,1e-1,'m/j','lin']
            
            params_file = 'calib_dicot_hom_1v_k1'
            
            params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
    
            # params_file = 'calib_dicot_het_2v_k1-k2'
            # params_file = 'calib_dicot_hom_2v_k1-n1'
        
# RUN CALIB DICHOTOMY STREAMS
            
            calib = calib_root.Calibration(params_file, BV,
                                           observations = ['streams'])
            # dicot = calib.dichotomy(gap=1)

#%% PLOT CALIB DICHOTOMY STREAMS

# Search by date

typ_calib = 'streams_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)
df=pd.DataFrame()

compt = 0
for case, prop in zip(case_list[:], prop_list[:]):
    
    name_file = list_path[compt].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    test.display_objective_function(save=None)
    
    koptim = test.calib['params_values'][-1]
    kr = koptim / test.calib['recharge']
    obj_func = test.calib['objective_function'][-1]
    
    # df.loc[0,watershed_name] = koptim / 24 / 3600
    # df.loc[1,watershed_name] = kr
    # df.loc[2,watershed_name] = obj_func
    
    df.loc[0,case] = koptim
    df.loc[1,case] = kr
    df.loc[2,case] = obj_func
    indicator = np.sqrt(obj_func)
    indicator = 10**indicator 
    df.loc[3,case] = indicator
    
    compt+=1
    
df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

df = df[["case1", "case2", "case3", "case4", "case5"]]


fig, ax = plt.subplots(1,1, figsize=(5,5))
x = pd.DataFrame([1, 2, 3, 4, 5])
# x = df.loc[1]
y = df.loc[2]

ax.scatter(x, y, c='b', s=150)
ax.set_yscale("log")
ax.set_xticks(x)
ax.set_xlim([0,6])

plt.xlabel('cases', fontsize = 20)
plt.yticks(fontsize = 20)
plt.xticks(fontsize = 20)

plt.ylabel(r'$log(\overline{D_{so}}/\overline{D_{os}})^2$', fontsize = 20)

# fig.savefig(figsim_folder+watershed_name+'_cases_calibration_results'+'.png', dpi=300, bbox_inches='tight')

#%% RUN PARTCILE TRACKING

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2019, time_step = 'D',
                                  sim_state='steady') #

df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

for case, prop in zip(case_list[:], prop_list[:]):

#% MODEL with K from dichotomy and explore on RTD
    # K_R = 79.2174 # Find path to dichotomy results
    K_R = df.loc[1,case]

    K_dic = K_R*BV.forcing.recharge # UNITS OF RECHARGE ?
    
    BV.hydrodynamic.update_hyd_cond(K_dic) # m/d
    
    nlay = 5
    if prop[2]>0:
        length_K_decay = prop[2]**-1
        thick = 10*length_K_decay
        layer_min_thick = 5
        nlay = int(np.log(1-thick*(1-thick_exp)/layer_min_thick) / np.log(thick_exp))
        print('###########!!!!!!!!!!!!!!!!!############')
        print('nlay = ' + str(nlay))
        print('###########!!!!!!!!!!!!!!!!!############')
                
    BV.hydrodynamic.update_nlay(nlay)
    BV.hydrodynamic.update_thickness(prop[0])
    BV.hydrodynamic.update_bottom(prop[1])
    BV.hydrodynamic.update_cond_decay(prop[2])
    BV.hydrodynamic.update_thick_exp(thick_exp)
    
    for porosity in porosity_list:
    
        BV.hydrodynamic.update_porosity(porosity)
        # print(BV.hydrodynamic.porosity)
        
        # Name of model
        model_name = case+'_'+str(porosity)
        # Launch model
        
        # Launch a model
        # BV.run_modflow(ident=model_name, modpath_sim=True, first_only=True, sink_fill=False, box=False,
        #                 lay_number=1, bottom=None, thick_exp=1., cond_decay=0., 
        #                 verbose=True)
        success, flow_model = BV.run_modflow(ident=model_name,
                                             modpath_sim=True)
        BV.matrix_modflow(success,
                          flow_model,
                          first_only = False,
                          watertable_elevation = True,
                          watertable_depth = True, 
                          seepage_areas = True,
                          outflow_drain = True,
                          groundwater_flux = True,
                          specific_discharge = False,
                          accumulation_flux = True,
                          perenn_intermit_shp = False,
                          groundwater_storage = True,
                          residence_times = True,
                          verbose = True,
                          export_tif = True)
        
        BV.results_modflow(ident=model_name,
                           actual_date=True,
                           start='1960-01-01',
                           time_step='M')
        


        visu = visualization.Visualization(BV, model_name)
        visu.visual2D(object_list = ['pathlines'],
                      color_scale = [(0,2)], lines=None)

        # visu = visualization.Visualization(BV, model_name)
        # visu.visual2D(object_list = ['pathlines'],
        #               color_scale = [(0,2)], lines=10000)
        
        print('####################################')
        print('####### simulation completed #######')
        print('####################################')

#%% EXTRACT RESIDENCE TIMES

df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

wateshed_name = 'Lasset'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
figsim_folder = simulations_folder + '_figures/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

case_list = ['case3']

prop_list = [[50, 1000, dc[0]]]

compt=0
for case, prop in zip(case_list[:], prop_list[:]):
    
    for porosity in porosity_list[:]:
    
        model_name = case+'_'+str(porosity)
        folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'
        
        path_res = folder_results+'residence_times_t(0).tif'
        path_obs = stable_folder+'/add_data/'+'age_apparent_obs_C2.shp'
        path_shp = simulations_folder + '/' + model_name + '/' + '_watershed/_shp/'
        toolbox.create_folder(path_shp)
        path_dat = path_shp+'residence_times_data.shp'
        
        res_time = rasterio.open(path_res)
        res_time_data = res_time.read(1)
        res_time_data = res_time_data
        
        shp_obs = gpd.read_file(path_obs)
        shp_obs['geometry'] = shp_obs.geometry.buffer(125)
        # shp_obs = shp_obs[['ID_station', 'geometry']]
        shp_obs.to_file(path_dat, encoding='utf-8') # mode a
        
        # wbt.extract_raster_values_at_points(
        #                 path_res, 
        #                 path_dat, 
        #                 out_text=False)
        
        # Mathod 1
        wbt.raster_to_vector_polygons(
                path_res, 
                path_shp+'raster_polygonized.shp')
        raster_polyg = gpd.read_file(path_shp+'raster_polygonized.shp')
        intersect = gpd.overlay(shp_obs, raster_polyg, how='intersection')
        intersect[intersect['VALUE']==-np.inf] = np.nan
        res_dat = gpd.read_file(path_dat)
        res_dat['RES_TIME'] = np.nan
        res_dat['STD_TIME'] = np.nan
        
        for ID in intersect['id'].unique():
            # threshold = 1 #year
            # threshold = threshold*365
            # threshold = np.log10(threshold)
            
            mask = (intersect[intersect['id']==ID]['VALUE'] !=0)
            
            mean_ID = np.nanmean(intersect[intersect['id']==ID]['VALUE'][mask])
            res_dat['RES_TIME'][res_dat['id']==ID] = mean_ID
            
            std_ID = np.nanstd(intersect[intersect['id']==ID]['VALUE'][mask])
            res_dat['STD_TIME'][res_dat['id']==ID] = std_ID
            
        
        # Method 2
        '''
        from rasterstats import zonal_stats
        stats = zonal_stats(path_dat, path_res)
        # print(stats[0].keys())
        # print(stats)
        means = [f['mean'] for f in stats]
        res_dat = gpd.read_file(path_dat)
        res_dat['RES_TIME'] = means
        '''
        
        res_dat['RES_TIME'][res_dat['RES_TIME']==-np.inf] = np.nan
        res_dat['STD_TIME'][res_dat['STD_TIME']==-np.inf] = np.nan
        res_dat.to_file(path_shp + 'extract_RTD.shp', encoding = 'utf-8')
        
        res_dat['RES_TIME'] = (10**(res_dat['RES_TIME']))/365
        res_dat['STD_TIME'] = (10**(res_dat['STD_TIME']))/365
        
        vmin = 10
        vmax = 50
        
        fig, ax = plt.subplots(1,1, figsize=(5,5))
        # plt.imshow(res_time_data)
        # plt.colorbar()
        
        ## Modif res_time_data en annees + vmin et vmax
        
        
        #show(np.ma.masked_where(dem_data < -0, res_time_data), ax=ax, transform=dem.transform, 
        show(np.ma.masked_where(dem_data < -0, (10**res_time_data)/365), ax=ax, transform=dem.transform, 
             cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=vmin, vmax=vmax)
        shp_obs.plot(ax=ax, color=None, marker='o', markersize=10,
                     edgecolor='k', lw=1, zorder=30)
        # res = res_dat.plot(ax=ax, cmap='jet',  marker='o', markersize=10,
        #              edgecolor='k', lw=1, column='RES_TIME', zorder=30,
        #              vmin=vmin, vmax=vmax)
        bounds = dem.bounds
        xlim = ([bounds[0], bounds[2]])
        ylim = ([bounds[1], bounds[3]])
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'bottom', location='upper left')
        ax.add_artist(scalebar)
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        ax.set_title(model_name, fontproperties=fontprop)
        ax.set(aspect='equal')
        sm = plt.cm.ScalarMappable(cmap='jet', norm=plt.Normalize(vmin=vmin, vmax=vmax))
        divider = make_axes_locatable(ax)
        cax = divider.append_axes(size="2%",position='right', pad=0.05)
        fig.add_axes(cax)
        cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
        cbar.ax.get_ymajorticklabels()
        cbar.ax.tick_params(labelsize=10)
        cbar.ax.yaxis.set_ticks_position('right')
        cbar.ax.tick_params(size=2)
        contour = gpd.read_file(BV.geographic.watershed_contour_shp)
        contour.plot(ax=ax, lw=1.5, color='k', zorder=20, legend=False, label='Watershed')
        cbar.set_ticks(list(cbar.get_ticks()))
        # cbar.set_ticklabels(list(cbar.get_ticks())[::-1])
        cbar.set_label('Residence times [years]', rotation=270, labelpad=25)

        res_dat['coords'] = res_dat['geometry'].apply(lambda x: x.representative_point().coords[:])
        res_dat['coords'] = [res_dat[0] for res_dat in res_dat['coords']]
        for idx, row in res_dat.iterrows():
            row['coords'] = (row['coords'][0], row['coords'][1]+100)
            ax.annotate(s=row['id'], xy=row['coords'],
                         horizontalalignment='center')

        fig.savefig(figsim_folder+model_name+'.png', dpi=300, bbox_inches='tight')

        fig, ax = plt.subplots(1,1, figsize=(4,4))
        mean_obs = res_dat[['CFC11', 'CFC12', 'CFC113']].mean(axis=1)
        std_obs = res_dat[['CFC11', 'CFC12', 'CFC113']].std(axis=1)
        x=2021-(mean_obs)
        xerr=std_obs
        mean_sim = res_dat['RES_TIME']
        y=mean_sim
        yerr = res_dat['STD_TIME']
        ax.scatter(x, y, c=y, s=50, cmap=mpl.colors.ListedColormap('k'))
        plt.errorbar(x, y , xerr=list(xerr), yerr=yerr, lw=1, fmt="o", color='k')
        # ax.legend()
        ax.set_xlabel('$Age_{obs}$ [years]')
        ax.set_ylabel('$Age_{sim}$ [years]')
        ax.set_title(model_name, fontproperties=fontprop)
        for i, txt in enumerate(res_dat.id):
            ax.annotate(txt, (x[i], y[i]))
        xn=20
        xx=80
        yn=20
        yx=80
        ax.set_xlim(xn, xx)
        # ax.set_ylim(yn, yx)
        # ax.set_xscale('log')
        # ax.set_yscale('log')
        # ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
        #         linestyle='--', color='grey', linewidth=2, zorder=-1)
        maxx = max(ax.get_xlim()[0],ax.get_xlim()[1])
        maxy = max(ax.get_ylim()[0],ax.get_ylim()[1])
        minx = min(ax.get_xlim()[0],ax.get_xlim()[1])
        miny = min(ax.get_ylim()[0],ax.get_ylim()[1])
        maxt = max(maxx,maxy)
        mint = max(minx,miny)
        ax.plot(np.linspace(mint,maxt,50),
                np.linspace(mint,maxt,50), 
                linestyle='--', color='grey', linewidth=2, zorder=-1)
        
        fig.savefig(figsim_folder+'obs_vs_sim_'+model_name+'.png', dpi=300, bbox_inches='tight')
        
        if compt==0:
            all_dat = res_dat.copy()
        all_dat[model_name] = res_dat['RES_TIME']
        
        compt+=1

all_dat['coords'] = np.nan
all_dat.to_file(simulations_folder+'residence_times_all.shp', sep=';', encoding='utf-8')

#%% COMPUTE THE RMSE ON RTD

from matplotlib.cm import get_cmap

from matplotlib.pyplot import cm
from cycler import cycler
import matplotlib.dates as mdates

lines = ["-","-",":","-","--","-.","--","-"]#     # axs[1].set_prop_cycle(color=colors)

n = len(lines)
colors = cm.Dark2(np.linspace(0,1,n)) #['r', 'g', 'b', 'y']  # type: list
plt.rc('lines', linewidth=4)
plt.rc('axes', prop_cycle=(cycler('color', colors) +
                           cycler('linestyle', lines)))


from sklearn.metrics import mean_squared_error


rmse_all = []
phi_optim = []
# cc=cm.Dark2(np.linspace(0,1,10))
# lines = ["-.",":","--","-"]
# linecycler = cycle(lines)

fig, ax = plt.subplots(1, 1, figsize=(4, 4))

ci = 0

for case, prop in zip(case_list[:], prop_list[:]):
    
    RTDfile_to_open = simulations_folder+case+'_RTD.shp'
    
    RTD_dat = gpd.read_file(RTDfile_to_open)

    
    # RTD_obs_me = RTD_dat[['CFC11', 'CFC12', 'CFC113']].mean(axis=1)
    # RTD_obs_me = 2021 - RTD_obs_me
    # RTD_obs_std = RTD_dat[['CFC11', 'CFC12', 'CFC113']].std(axis=1)
    
    RTD_obs_me = RTD_dat[['CFC12']].mean(axis=1)
    RTD_obs_me = 2021 - RTD_obs_me
    
    RTD_obs_std = RTD_dat[['CFC12']].std(axis=1)
    
    cp = 0 
    
    rms_case = []
    acs_case = []
    
    for porosity in porosity_list[:]:
        cp = cp + 1
        model_name = case+'_'+str(porosity)
        name_col = case + str(cp)
           
        RTD_sim = RTD_dat[name_col]
        RTD_rmse = pd.concat([RTD_obs_me, RTD_sim], axis=1)
        RTD_rmse = RTD_rmse.rename(columns={0: "obs", name_col: "sim"})
        N = len(RTD_rmse.dropna())
        
        #RTD_rmse=RTD_rmse.fillna(0)
        RTD_rmse = RTD_rmse.dropna()
        
        yobs = np.array(RTD_rmse["obs"])
        ysim = np.array(RTD_rmse["sim"])
        
        rms = mean_squared_error(yobs, ysim, squared=False)
        
        #ratio = N/(len(RTD_obs_me)-2)
        #rms = rms/ratio
        

        rms_case.append(rms)
        
        
        

        # acs = balanced_accuracy_score(yobs, ysim)
        
        #print(model_name + ', rmse = ' + str(rms))
    
    rmse_all.append(rms_case)
    if N<6:
        trans = 0.25
    else:
        trans = 1
        
    ax.plot(porosity_list, rms_case, lw = 3, label = case, alpha = trans)
    ci = ci+1
    print(str(ci) + ', N=' + str(N) + '/' + str(len(RTD_obs_me)))
    
    phi = porosity_list[rms_case.index(np.min(rms_case))]
    phi_optim.append(phi)
    print('porosity =' + str(phi))
    
    del(rms_case)
    
#plt.legend(loc = 'best')
plt.yscale('log')
fs = 16
ax.set_ylabel(r'$rmse ~[y]$', fontsize = fs)
ax.set_xlabel(r'$Porosity, ~ \phi ~ [-]$', fontsize = fs)
ax.set_xlim([0, 0.3])
ax.set_ylim([20, 100])
plt.show()

fig.savefig(figsim_folder+watershed_name+'_RTD_results'+'.png', dpi=300, bbox_inches='tight')
phi_optim = pd.DataFrame(phi_optim,index=case_list)
phi_optim.to_csv(simulations_folder+'phi_optim.csv',
                 sep=';')

#%% EXTRACT PATHLINES TIMES

df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

wateshed_name = 'Lasset'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
figsim_folder = simulations_folder + '_figures/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

compt=0
for case, prop in zip(case_list[:], prop_list[:]):
    
    for porosity in porosity_list:
    
        model_name = case+'_'+str(porosity)
        folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'
        
        ##### LOOOP 2D #####
        visu = visualization.Visualization(BV, model_name)
        # visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
                      # color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
        visu.visual2D(object_list = ['pathlines'],
                      color_scale = [(None,None)], lines=100)
   
#%% EXTRACT PATHLINES SINGLE

df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

wateshed_name = 'Lasset'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
figsim_folder = simulations_folder + '_figures/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

compt=0
case = case_list[2]
prop = prop_list[2]
porosity = porosity_list[2]
    
model_name = case+'_'+str(porosity)
folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'

##### LOOOP 2D #####
visu = visualization.Visualization(BV, model_name)
# visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
              # color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
visu.visual2D(object_list = ['pathlines'],
               color_scale = [(-1,2)], lines=100)

# from tools import toolbox, vtk
# vtk.VTK(BV, model_name)
# visu = visualization.Visualization(BV, model_name)
# visu.visual3D(interactive=False,
#               object_list=['pathlines'], z_scale=1,
#               view='custom', lines=200, cloc=(0,2))

#%% STATISTCIS

import hydroeval as he
import scipy

stats = pd.DataFrame()

all_dat = gpd.read_file(simulations_folder+'residence_times_all.shp', sep=';', encoding='utf-8')

for case, prop in zip(case_list[:], prop_list[:]):
    
    for porosity in porosity_list:
    
        model_name = case+'_'+str(porosity)
        
        y0 = 2021 - (all_dat[['CFC12','CFC11','CFC113']].mean(axis=1))
        y1 = all_dat[model_name]
                
        ER = np.nansum(y0-y1)  # error 
        ABSER = np.nansum(np.abs(y0-y1))  # absolute error 
        RELER = np.nansum(np.abs(y0-y1)/y0) # relative error 
        PERER = np.nansum(np.abs(y0-y1)/y0*100) # percentage error 
        MAE = np.nanmean(np.abs(y0-y1)) # mean absolute error 
        BAL = (np.sum(y1)/np.sum(y0))*100 # balance
        MSE = np.nanmean((y0-y1)**2) # mean square error 
        RMSE = np.sqrt(np.nanmean((y0-y1)**2)) # root mean square error 
        NSE = 1-( np.sum((y1-y0)**2) / np.sum((y0-np.mean(y0))**2) ) # nash–sutcliffe efficiency                               
        MARE = he.evaluator(he.mare, y1, y0)[0] # mean absolute relative error 
        KGE = he.evaluator(he.kge, y1, y0)[0][0] # kling-gupta efficiency (r, α, β)
        PBIAS  = he.evaluator(he.pbias, y1, y0)[0] # percent bias
        NSElog = he.evaluator(he.nse, y1, y0, transform='log')[0] # nash–sutcliffe efficiency log

        stats.loc['ER', model_name] = ER
        stats.loc['ABSER', model_name] = ABSER
        stats.loc['RELER', model_name] = RELER
        stats.loc['PERER', model_name] = PERER
        stats.loc['MAE', model_name] = MAE
        stats.loc['BAL', model_name] = BAL
        stats.loc['MSE', model_name] = MSE
        stats.loc['RMSE', model_name] = RMSE
        stats.loc['NSE', model_name] = NSE                        
        stats.loc['MARE', model_name] = MARE
        stats.loc['KGE', model_name] = KGE
        stats.loc['PBIAS', model_name]  = PBIAS
        stats.loc['NSElog', model_name] = NSElog

        # y0 = np.ma.masked_invalid(y0)
        # y1 = np.ma.masked_invalid(y1)
        y0 = y0[np.logical_not(np.isnan(y1))]
        y1 = y1[np.logical_not(np.isnan(y1))]

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(y0, y1)
        res = scipy.stats.linregress(y0.values, y1.values)
        
        # plt.plot(y0, y1, 'o', c='k')
        # plt.plot(y0, res.intercept + res.slope*y0, 'r', label='fitted line')
        # plt.xlim(0,100)
        # plt.ylim(0,100)
        
        stats.loc['SLOPE', model_name]  = slope
        stats.loc['INTERC', model_name] = intercept
        stats.loc['RVAL', model_name]  = r_value
        stats.loc['PVAL', model_name] = p_value
        stats.loc['STDERR', model_name]  = std_err
        
stats
stats.to_csv(simulations_folder+'statistics_residence_times.csv',
             sep=';')
        
#%% CROSS SECTION

typ = 'caseg_0.15'

watershed_names = ['Lasset']

for watershed_name in watershed_names[:]:
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    
    for model in list_path[:]:
    
        model_name = model.split('\\')[-1]
            
        wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                                   stable_folder+'geographic/'+'watershed_contour.tif',
                                   base = stable_folder+'geographic/'+'watershed_dem.tif')
        line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
        line = np.ma.masked_where(line <= 0, line)
            
        mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
        
        import itertools            
        
        watertable_elevation = np.load(simulations_folder+model_name+'/_watershed/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
    
        for key in watertable_elevation:
        # for key in watertable_elevation:
            print(key)
    
            dem_data = imageio.imread(BV.geographic.watershed_dem)
            wt_data = watertable_elevation[key]
            # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0)'+'.tif')
    
            xvalues = np.linspace(-1,1,dem_data.shape[1])
            yvalues = np.linspace(-1,1,dem_data.shape[0])
            xx, yy = np.meshgrid(xvalues,yvalues)
            
            cur_x = dem_data.shape[1] /2
            cur_y = dem_data.shape[0] /2
            
            dem_max = dem_data.max()
            dem_prof = dem_data.astype(float)
            dem_prof[dem_prof<0] = np.nan
            wt_prof = wt_data.astype(float)
            wt_prof[wt_prof<0] = np.nan
            
            cur_y = 80
            dem_h_plot = dem_prof[int(cur_y),:]
            dem_h_plot[dem_h_plot == 0] = np.nan
            wt_h_plot = wt_prof[int(cur_y),:]
            wt_h_plot[wt_h_plot == 0] = np.nan
            
            cur_x = 25  
            dem_v_plot = dem_prof[:,int(cur_x)]
            dem_v_plot[dem_v_plot == 0] = np.nan
            wt_v_plot = wt_prof[:,int(cur_x)]
            wt_v_plot[wt_v_plot == 0] = np.nan
                
            dem_max = dem_data.max()
            dem_prof = dem_data.astype(float)
            dem_prof[dem_prof<0] = np.nan
            dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
            
            wt_prof = wt_data.astype(float)
            wt_prof[wt_prof<0] = np.nan
                    
            fig, ax = plt.subplots(1, 1, figsize=(5,5))
            ax.imshow(dem_plot, origin='lower', cmap='Greys', aspect="equal",)
            ax.set_ylim(ax.get_ylim()[::-1])
            v_line = ax.axvline(cur_x, color='k', lw=2)
            h_line = ax.axhline(cur_y, color='k', lw=2)
    
            fig, ax = plt.subplots(1, 1, figsize=(5.5,4), dpi=300)
            ax.set_title(model_name)
            
            if model_name.split('_')[0] == 'case1':
                dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
                wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
                wt_h_fill = plt.fill_between(np.arange(xx.shape[1])*75, dem_h_plot-50, wt_h_plot,
                                                color='deepskyblue', alpha=0.5, lw=0)
                wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
            
            else:
                dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
                wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
                wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, 0, wt_h_plot,
                                                color='deepskyblue', alpha=0.5, lw=0)
                wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
            
            # wt_v_fill = ax.fill_between(np.arange(xx.shape[0]), 0, wt_v_plot,
            #                                     color='deepskyblue', alpha=0.5, lw=0)
            # wt_v_fill = ax.fill_between(np.arange(xx.shape[0]), wt_v_plot, dem_v_plot,
            #                                     color='saddlebrown', alpha=0.5, lw=0)
            
            ax.set_xlim(1200, 4000)
            ax.set_ylim(1000, 2500)
            # ax.set_yticks([140,160])
            ax.set_xlabel('Distance [m]')
            ax.set_ylabel('Elevation [m]')
        
            plt.tight_layout()
            
            fig.savefig(simulations_folder+'/_figures/'+'cross_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% 2D VISUALIZATION

save_name = model_name + '_KR_'+ str(K_R)  
visu = visualization.Visualization(BV, model_name)
# visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
              # color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
visu.visual2D(object_list = ['surface_flow','residence_times'],
              color_scale = [(None,None),(None,None)], lines=10000)

#%% INIT CALIB EXPLORATION DISCHARGE

# CHANGER LA CHRONIQUE ALL_D de surfex, colonne REA

watershed_names = ['Lasset']

# modflow_path = data_path + 'SOFTWARE/MODFLOW/'

from watershed import watershed_root, watershed_display, forcing
from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis, calib_params

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    sim_state = 'transient'
    
    #### STAY IN D TO GENERATE RECHARGE ####
    # If necessary, you resample in month before to update the last recharge (integrated in the model)
    time_step = 'D'
    
    var = 'REC'
    wr = True
    wish = 0
    mod = 'REA'
    
    raw_path = stable_folder+'/'+'hydrometry/'
    
    ### AJOUTER LA CHRONIQUE DE DEBIT OBSERVE DANS LE DOSSIER HYDROMETRY 
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = BV.geographic.area
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    # Qobs = Qobs.resample('D').mean()
    fqobs = Qobs.first_valid_index().year+1
    lqobs = Qobs.last_valid_index().year-1
    
    # Ces dates permettent de normalizer et calibrer sur des périodes différentes, à voir ci-dessous
    # fhist = 2021
    # lhist = 2021
    
    # fcalib = 2021
    # lcalib = 2021
    
    # year_min = 2021
    # year_max = 2021
    
    ############ METHOD 1 : BUILT RECHARGE ALONE ############
    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                              first_year = 1960, last_year = 2019,
                                              time_step = time_step, sim_state=sim_state)
    Rech = BV.forcing.recharge
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                          first_year = 1960, last_year=2019,
                                          time_step = time_step, sim_state=sim_state)
    Runof = BV.forcing.runoff # m/month
    
    dates = pd.date_range(start='1/1/2021', end='31/12/2022', freq='D', closed=None)
    
    Rech_averag = Rech.groupby([Rech.index.month,
                                Rech.index.day], as_index=True).mean().reset_index().iloc[:,-1:].iloc[:-1]
    Rech_averag = Rech_averag.append(Rech_averag, ignore_index=True)
    Rech_averag.index = dates
    Runof_averag = Runof.groupby([Runof.index.month, 
                                  Runof.index.day], as_index=True).mean().reset_index().iloc[:,-1:].iloc[:-1]
    Runof_averag = Runof_averag.append(Runof_averag, ignore_index=True)
    Runof_averag.index = dates
    
    # Normalized 
    norm_Runof = select_period(Runof_averag, 2021, 2022)
    norm_Rech = select_period(Rech_averag, 2021, 2022)
    norm_Qobs = select_period(Qobs, 2021, 2022)
    Rt_Rech_Qobs = (norm_Qobs.mean() / norm_Rech.mean())
    print(Rt_Rech_Qobs.round(2))
    Nt = (norm_Rech * Rt_Rech_Qobs)
    
    ##### TO CHANGE IN MENSUALLY MODEL BECAUSE THE CALIBRATION ON Q IS NOW MENSUALLY #####
    Rech_mens = Nt.resample('M').mean().squeeze() # to transform in pandas series
    Runof_mens = norm_Runof.resample('M').mean().squeeze() # to transform in pandas series
    
    BV.forcing.update_recharge(Rech_mens, sim_state=sim_state)
    BV.forcing.update_runoff(Runof_mens, sim_state=sim_state)
    
    plt.plot(Nt, c='red')
    plt.plot(Qobs, c='blue')
    plt.plot(BV.forcing.recharge, c='darkorange')
    plt.plot(Qobs.resample('M').mean(), c='forestgreen')
    plt.yscale('log')

    cond_decay = 1/20
    thickness = 50
    bottom = 1000    
    thick_exp = 1.25

    length_K_decay = cond_decay**-1
    thick = 10*length_K_decay
    layer_min_thick = 5
    nlay = int(np.log(1-thick*(1-thick_exp)/layer_min_thick) / np.log(thick_exp))

    BV.hydrodynamic.update_nlay(nlay) # 1
    BV.hydrodynamic.update_bottom(bottom) # None
    BV.hydrodynamic.update_cond_decay(cond_decay) # 0
    BV.hydrodynamic.update_thick_exp(thick_exp) # 1
    BV.hydrodynamic.update_thickness(thickness) # 30 / intervient pas si bottom != None
    
    # BV.hydrodynamic.update_porosity(0.001)
    # BV.hydrodynamic.update_hyd_cond(0.08640) # 1e-6 m/s
    
    params_df = pd.DataFrame(columns=['params',
                                      'init_values','lower_bounds','higher_bounds',
                                      'units','scale'])
    
    params_df.loc[0] = ['k1',8.64e-01,8.64e-04,8.64e+01,'m/j','lin']
    params_df.loc[1] = ['n1',0.01,0.001,0.20,'m/j','lin']

    params_file = 'calib_explo_hom_2v_k1-n1'
    
    list_npy = glob.glob(BV.calibration_folder+'/'+params_file+'/hydrometry_calibration/_watershed/'+'*'+'.npy')
    for npy in list_npy:
        os.remove(npy)
    
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

# x= pd.read_csv('C:/Users/ronan/Downloads/_ALL_D.csv',
#                sep=';', parse_dates=True, index_col=0)
# plt.plot(select_period(x,2015,2025)['REC_REA_historic'])

#%% RUN CALIB EXPLORATION DISCHARGE

calib = calib_root.Calibration(params_file, BV, observations = ['hydrometry'])
calib.exploration(resolution=100)

#%% PLOT CALIB EXPLORATION DISCHARGE

def fmt_xaxes(ax, years_maj, years_min):
    yearsmaj = mdates.YearLocator(years_maj)   # every year
    yearsmin = mdates.YearLocator(years_min)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

watershed_names = ['Lasset']

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'surflow_areas'

min_nse = 60
min_sat = 0
max_sat = 50

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
        
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    typ_calib = 'hydrometry_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                        key=os.path.getmtime, reverse=True)
    name_file = list_path[wish].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    
    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    sim_res=test.sim_results
    
    typ_name = typ_calib.split('_')[0]
    
    obs = test.data_obs
    sim = test.data_sim
    ind = test.data_ind
    obj = test.calib['objective_function']
    xyz = test.params_xyz
    
    synt = test.params_synt
        
    p1 = []
    for p in synt:
        p1.append(p.split(';')[0])
    p2 = []
    for p in synt:
        p2.append(p.split(';')[1])
    rout = []
    for r in sim[typ_name]:
        rout.append((r*1000*30).mean()[0])
    rsat = []
    for t in range(len(synt)):     
        sat = test.sim_results[synt[t]][sat_typ]
        sat = pd.to_numeric(sat, errors='coerce').isnull()
        rsat.append(sat.mean())
    
    nse_good = []
    sat_good = []
    
    fig, axs = plt.subplots(2,2, figsize=(9,5))
    axs = axs.ravel()
    fig.suptitle(watershed_name.upper())
    
    numb = 0
    for i in range(len(obs[typ_name])):
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        sat = test.sim_results[synt[i]][sat_typ]
        sat = pd.to_numeric(sat, errors='coerce')
        
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_sat:
                if sat.max() > min_sat:
                    numb += 1
                # c = []
                # for h in range(len(ind[typ_name])):
                #     d = ind[typ_name][h][0]
                #     c.append(d)
                c = np.linspace(0,1,len(obs[typ_name]))

        cmap = mpl.cm.get_cmap('jet_r')
        color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
        
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_sat:
                if sat.max() > min_sat:    
                
                    ax = axs[0]
                    fmt_xaxes(axs[0], 6, 1)                 
                    ax.plot(s, color=color_gradients[i], lw=1, label=label)
                    ax.set_title(title)
                    ax.plot(o, color='grey', lw=3, ls='-', zorder=0)
                    # ax.set_xlim(pd.to_datetime('2021'), pd.to_datetime('2022'))
                    del(ax)
                
                    ax = axs[1]
                    fmt_xaxes(axs[1], 6, 1)
                    ax.set_title('Log discharge [mm/month]')
                    ax.plot(select_period(o.copy(),2021,2022), color='grey', lw=3, ls='-', zorder=0)
                    ax.set_yscale('log')
                    ax.plot(select_period(s.copy(),2021,2022), color=color_gradients[i], lw=1, label=label)

                    ax = axs[2]
                    fmt_xaxes(axs[2], 6, 1)
                    sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
                    ax.plot(select_period(sat.copy(),2021,2022), color=color_gradients[i], lw=1, label=label)
                    ax.set_ylim(-2,50)
                    title = 'Saturation [%]'
                    ax.set_title(title)
                    # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
                                
    plt.tight_layout()
    ncol = 2
    ax.legend(bbox_to_anchor=(1.2,0.5), prop={'size': 5}, loc="center left", 
              borderaxespad=0, ncol=ncol)
    ax = axs[3]
    plt.axis('off')
        
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='1.25%', pad=0.1)
    # fig.add_axes(cax)
    # norm = Normalize(vmin=vmin, vmax=vmax)
    # n_cmap = cm.ScalarMappable(norm=norm, cmap=cmap)
    # n_cmap.set_array([])
    # ax.get_figure().colorbar(n_cmap, cax=cax, orientation="vertical")

    fig, axs = plt.subplots(1,3, figsize=(10,3.5))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    
    for k in range(3):
        ax = axs[k]
        ax.axes.tick_params(which='both', direction='out', zorder=10)
        X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
        Z = np.empty((3,3,))
        Z[:] = np.nan
        p1 = test.params_values[0]
        p2= test.params_values[1]
        sim_sat = np.zeros((len(p1),len(p2)))
        compt=0
        for i in range(len(p1)):
            for j in range(len(p2)):
                temp = [p1[i],p2[j]]
                string = str(p1[i])+';'+str(+p2[j])
                if k == 0:
                    try:
                        ax.set_title('SAT MIN [%]')
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
                    except:
                        pass
                if k == 1:
                    try:
                        ax.set_title('SAT MEAN [%]')
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).mean()
                    except:
                        pass
                if k == 2:
                    try:
                        ax.set_title('SAT MAX [%]')
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
                    except:
                        pass
                compt += 1
        Z=sim_sat
        pc = ax.contourf(X,Y,Z,cmap='jet', levels=np.arange(0,51,5)) #figadd.cmap_white_jet()
        ax.set_xscale('log')
        ax.set_ylabel('Sy [-]')
        ax.set_xlabel('K [m/j]')
   
    position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    fig.colorbar(pc,cax=position)
    plt.tight_layout()

    fig, axs = plt.subplots(1,3, figsize=(15,4))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    
    ax = axs[0]
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    pc = ax.imshow(Z, vmin = 0, vmax = 1, aspect='auto') #figadd.cmap_white_jet() , shading='gouraud'
    # ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb=fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)

    ax = axs[1]
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    Z[Z == inf] = 0
    pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)

    ax = axs[2]
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    pc = ax.contourf(X, Y, Z, levels=np.arange(0,1.1,0.1))    
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    
    plt.tight_layout()

#%% PLOT TO SUPERPOSE SATURATION AND DISCHARGE

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

watershed_names = ['lasset']

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'surflow_areas'

min_nse = 70
mean_meansat = 3 # sup
min_maxsat = 8
max_maxsat = 25
        
for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    typ_calib = 'hydrometry_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                        key=os.path.getmtime, reverse=True)
    name_file = list_path[wish].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    
    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    sim_res=test.sim_results
    
    typ_name = typ_calib.split('_')[0]
    
    obs = test.data_obs
    sim = test.data_sim
    ind = test.data_ind
    obj = test.calib['objective_function']
    xyz = test.params_xyz
    
    synt = test.params_synt
        
    p1 = []
    for p in synt:
        p1.append(p.split(';')[0])
    p2 = []
    for p in synt:
        p2.append(p.split(';')[1])
    rout = []
    for r in sim[typ_name]:
        rout.append((r*1000*30).mean()[0])
    rsat = []
    for t in range(len(synt)):     
        sat = test.sim_results[synt[t]][sat_typ]
        sat = pd.to_numeric(sat, errors='coerce').isnull()
        rsat.append(sat.mean())
    
    nse_good = []
    sat_good = []
    
    numb = 0
    for i in range(len(obs[typ_name])):
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        sat = test.sim_results[synt[i]][sat_typ]
        sat = pd.to_numeric(sat, errors='coerce')
        
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_sat:
                if sat.max() > min_sat:
                    numb += 1
                # c = []
                # for h in range(len(ind[typ_name])):
                #     d = ind[typ_name][h][0]
                #     c.append(d)
                c = np.linspace(0,1,len(obs[typ_name]))

        cmap = mpl.cm.get_cmap('viridis_r')
        color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    # pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    pc = ax.contourf(X/3600/24, Y*100, Z, levels=np.arange(0,1.1,0.1))    
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='5%', pad=0.05)
    # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    # cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,1.1,0.2)) 
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    ax.set_xscale('log')
    ax.set_ylabel('Φ [%]')
    ax.set_xlabel('K [m/s]')
    # ax.set_yticks(np.arange(0,11,2))
    # ax.set_yticklabels(np.arange(0,11,2))
    # ax.tick_params(direction='in')
    ax.tick_params(top=False,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    plt.tight_layout()

    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z = np.empty((3,3,))
    Z[:] = np.nan
    p1 = test.params_values[0]
    p2= test.params_values[1]
    sim_sat = np.zeros((len(p1),len(p2)))
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
            except:
                sim_sat[j][i] = np.nan
                pass
            compt += 1
    Zmin = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).mean()
            except:
                sim_sat[j][i] = np.nan
                pass 
            compt += 1
    Zmean = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).median()
            except:
                sim_sat[j][i] = np.nan
                pass 
            compt += 1
    Zmed = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
            except:
                sim_sat[j][i] = np.nan
                pass
            compt += 1
    Zmax = sim_sat
    
    Z = Zmax.copy()
    Z[Zmax<min_maxsat] = np.nan
    Z[Zmax>max_maxsat] = np.nan
    Z[Zmean<mean_meansat] = np.nan
    
    Xclip = np.ma.masked_array(X, mask=np.isnan(Z)) /3600/24 # y = y.compress() # y without nan where x has nan's
    Yclip = np.ma.masked_array(Y, mask=np.isnan(Z)) *100    
    ax.scatter(Xclip, Yclip, c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    
    # pc = ax.pcolormesh(X/3600/24, Y*100, Z,
    #                   cmap = mpl.colors.ListedColormap('Grey'),
    #                   alpha=0.5, linewidths=1)
    # pc = ax.contour(X/3600/24, Y*100, Z, levels=np.arange(0,100,5),
    #                   cmap =  mpl.colors.ListedColormap('Grey'),
    #                   alpha=0.75, linewidths=1)
    
    # fig2, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    # pc = ax.contourf(X/3600/24, Y*100, Zmax, cmap='seismic',
    #                   levels=np.arange(0,100,5), alpha=0.75) # mpl.colors.ListedColormap('Grey')
    # ax.set_xscale('log')
    # ax.set_ylabel('Φ [%]')
    # ax.set_xlabel('K [m/s]')
    # ax.tick_params(top=True,
    #            bottom=True,
    #            left=True,
    #            right=False,
    #            labelleft=True,
    #            labelbottom=True)
    # # ax.tick_params(direction='out', axis='both', which='both')
    # # position=fig2.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    # # fig2.colorbar(pc,cax=position)
    
    plt.tight_layout()
    
    # fig.savefig(figsim_folder+watershed_name+'_calib2D_map'+'.png', dpi=300, bbox_inches='tight')

#%% ---- VRAC : FUTURE

#%% PARAM RUN MODEL

watershed_names = ['Lasset']
types_obs = ['streams'] # list of shapefile name layers for clip hydrology

typ = 'proj' # sinu / hist / proj

for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # BV.add_hydrometry(hydrometry_path)
    # BV.add_intermittency(intermittency_path) 
    # BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    # BV.add_subbasin()
    
    # Input recharge
    bzh_rech = False
    var = 'REC'
    wr = True
    
    ##### MODEL CHOICE ==> LOOP ####
    
    # for mod in ['NOR1']:
    #     for sce in ['RCP2.6','RCP8.5']:
        
    for gcm, rcm in zip(['CNR'],['ALA']):
        for sce in ['RCP2.6','RCP8.5']:
            mod = gcm
            
    # for mod in ['REA']:
    #     for sce in ['historic']:
            
            # Choice temporal of the simulation
            sim_state = 'transient' # 'steady' or 'transient'
            init_rech = None # 'first'
            
            if mod == 'REA':
                period_hist = [2012,2019]
            else:
                period_hist = [1960,2005] # recharge period
            period = [1960,2099] # recharge period               
            
            first_hist = period_hist[0]
            last_hist = period_hist[1]
            first = period[0]
            last = period[1]
            time_step = 'M' # or 'D'
            actual_date = True # False if date is conceptual
            start = str(period[0])+'-01-01' # necessary to specify the first time_step date
            
            raw_path = stable_folder+'/'+'hydrometry/'
            Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
            Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
            area = BV.geographic.area
            # area = float(Qobs_path.split('_')[-3])
            # print(area)
            Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
            Qobs = Qobs.squeeze()
            Qobs = Qobs.resample('M').mean()
            
            # # Normalize discharge historic
            # BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
            #                                   first_year = first_hist, last_year = last_hist,
            #                                   time_step = time_step, sim_state = sim_state)
            # Rech_hist = BV.forcing.recharge
            # BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
            #                                 first_year = first_hist, last_year = last_hist,
            #                                 time_step = time_step, sim_state = sim_state)
            # Runof_hist = BV.forcing.runoff # m/month
            
            # Rech_hist_select = select_period(Rech_hist, first_hist, last_hist)
            # Q_hist_select = select_period(Qobs, first_hist, last_hist)
            # Ratio_hist = (Q_hist_select.mean() / Rech_hist_select.mean())
            # print(Ratio_hist.round(2))
            
            # Rech_hist_norm = (Rech_hist_select * Ratio_hist)    

            # if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            #     BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
            #                                       first_year = first, last_year = last,
            #                                       time_step = time_step, sim_state = sim_state)
            #     Rech_fut = BV.forcing.recharge
            #     BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce=sce,
            #                                     first_year = first, last_year = last,
            #                                     time_step = time_step, sim_state = sim_state)
            #     Runof_fut = BV.forcing.runoff # m/month
                                
            #     Rech_fut_norm = (Rech_fut * Ratio_hist)
            
            #     Rech_concat = pd.concat((Rech_fut_norm, Rech_hist_norm), axis=1).mean(axis=1)
            #     Runof_concat = pd.concat((Runof_fut, Runof_hist), axis=1).mean(axis=1)
            
            #     BV.forcing.update_recharge(Rech_concat, sim_state = sim_state)
            #     BV.forcing.update_runoff(Runof_concat, sim_state = sim_state)
                
            #     fig = plt.subplots(1,1)
            #     plt.plot(Rech_concat)
            #     plt.yscale('log')
                
            # else:
            #     BV.forcing.update_recharge(Rech_hist_norm, sim_state = sim_state)
            #     BV.forcing.update_runoff(Runof_hist, sim_state = sim_state)
            
            #     # fig = plt.subplots(1,1)
            #     plt.plot(Rech_hist_norm)
            #     plt.yscale('log')
            
            if mod == 'REA':
                BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                  first_year = first_hist, last_year = last_hist,
                                                  time_step = time_step, sim_state = sim_state)
                Rech_hist = BV.forcing.recharge
                BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce = 'historic',
                                                first_year = first_hist, last_year = last_hist,
                                                time_step = time_step, sim_state = sim_state)
                Runof_hist = BV.forcing.runoff # m/month
            
            if mod != 'REA':
                BV.forcing.update_recharge_drias(gcm_mod=gcm, rcm_mod=rcm, sce_mod = 'historic',
                                                  first_year = first_hist, last_year = last_hist,
                                                  sim_state = sim_state)
                Rech_hist = BV.forcing.recharge
                BV.forcing.update_runoff_drias(gcm_mod=gcm, rcm_mod=rcm, sce_mod = 'historic',
                                                  first_year = first_hist, last_year = last_hist,
                                                  sim_state = sim_state)
                Runof_hist = BV.forcing.runoff # m/month
                
                BV.forcing.update_recharge_drias(gcm_mod=gcm, rcm_mod=rcm, sce_mod = sce,
                                                  first_year = first, last_year = last,
                                                  sim_state = sim_state)
                Rech = BV.forcing.recharge.resample('M').mean()
                BV.forcing.update_runoff_drias(gcm_mod=gcm, rcm_mod=rcm, sce_mod = sce,
                                                first_year = first, last_year = last,
                                                sim_state = sim_state)
                Runof = BV.forcing.runoff.resample('M').mean() # m/month
                
                Rech = pd.concat((Rech, Rech_hist), axis=1).mean(axis=1)
                Runof = pd.concat((Runof, Runof_hist), axis=1).mean(axis=1)
                BV.forcing.update_recharge(Rech.resample('M').mean(), sim_state=sim_state)
                BV.forcing.update_runoff(Runof.resample('M').mean(), sim_state=sim_state)
                # plt.plot(Rech)
                # plt.yscale('log')

            # Active of not modules
            box = False # if True generate a rectangular model
            sink_fill = False # permit to fill sinks
            modpath_sim = False # run modpath particle tracking if True
            verbose = True # add print of MODFLOW in console
            post_process = False # necessary to decompose post process of process
            
            # Strcture of the model
            cond_decay = 1/20
            thickness = 50
            bottom = 1000    
            thick_exp = 1.25
        
            length_K_decay = cond_decay**-1
            thick = 10*length_K_decay
            layer_min_thick = 5
            nlay = int(np.log(1-thick*(1-thick_exp)/layer_min_thick) / np.log(thick_exp))
        
            BV.hydrodynamic.update_nlay(nlay) # 1
            BV.hydrodynamic.update_bottom(bottom) # None
            BV.hydrodynamic.update_cond_decay(cond_decay) # 0
            BV.hydrodynamic.update_thick_exp(thick_exp) # 1
            BV.hydrodynamic.update_thickness(thickness) # 30 / intervient pas si bottom != None
            
            # Hydraulic properties
            # Koptim = 0.057 # 
            # Sy = 0.15
            Koptim = 0.062 # 
            Sy = 0.25
                
            Ks = [Koptim] # m/day
            Sys = [Sy]
            
        # RUN MODEL
        
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
                    BV.hydrodynamic.update_hyd_cond(K) 
                    BV.hydrodynamic.update_porosity(Sy)
                      
                    date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
                    date_today = date_today.replace('/','-')
                    date_today = date_today.replace(':','-')
                    date_today = date_today.replace(' ','_')
                    
                    model_name = typ+'_'+str(compt)+'_'+\
                                 var+'-'+mod+'-'+sce+'_'+\
                                 str(Sy*100)+'-'+str(round(K,2))+'-'+str(thick)+'_'+\
                                 str(first)+'-'+str(last)

                    # Run model
                    try:
                        print('SIM - ' + model_name)
                        success, flow_model = BV.run_modflow(ident=model_name,
                                                             modpath_sim=modpath_sim,
                                                             sink_fill=sink_fill,
                                                             box=box,
                                                             verbose=verbose,
                                                             post_process=post_process, 
                                                             init_rech=init_rech)
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
            
            dictio = {}
            dictio['list_model_name'] = list_model_name
            dictio['list_of_success'] = list_of_success
            dictio['list_flow_model'] = list_flow_model
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            # dictio.to_hdf(h5file)
            dd.io.save(h5file, dictio)
            
            # import pickle
            # with open(h5file, 'wb') as handle:
            #     pickle.dump(dictio, handle, protocol=pickle.HIGHEST_PROTOCOL)
        
            # BV.list_flow_model = list_flow_model
            # BV.list_of_success = list_success
            # BV.save_object()
    
#%% POSTPROCESS MODEL

# typ = 'good'
# typ = 'identname'
typ = 'proj'

watershed_names = ['Lasset']
types_obs = ['streams'] # list of shapefile name layers for clip hydrology

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    for mod in ['CNR']:
        for sce in ['RCP2.6','RCP8.5']:
    
    # for mod in ['REA']:
    #     for sce in ['historic']:
    
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_of_success = d['list_of_success'][:]
            list_flow_model = d['list_flow_model'][:]
            
            for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
                    
                if success==True:
                        print(success)
                        
                        BV.matrix_modflow(success,
                                          flow_model,
                                          first_only = False,
                                          watertable_elevation = True,
                                          watertable_depth = True, 
                                          seepage_areas = True,
                                          outflow_drain = True,
                                          groundwater_flux = True,
                                          specific_discharge = False,
                                          accumulation_flux = True,
                                          perenn_intermit_shp = False,
                                          groundwater_storage = True,
                                          verbose = True,
                                          export_tif = True)
                        
                        # Necessary for results_modflow
                        BV.forcing.update_recharge(flow_model.climatic,
                                                   sim_state=sim_state)
                        
                        # # Extract results
                        BV.results_modflow(ident=model_name,
                                           actual_date=actual_date,
                                           start=start,
                                           time_step=time_step)
                        
                        ## Plot maps
                        save_gif = False # save a gif after plots
                        Rech = flow_model.climatic
                        surf = modflow_display.SurfaceOutputs(Rech, simulations_folder, stable_folder, model_name, 
                                                              types_obs, save_gif=save_gif, first_only=True,
                                                              outflow=True, accflux=True, intermittency=False,
                                                              chronics=True, sim_state=sim_state)

#%% ---- VRAC : PLOT

#%% PLOT CHRONICS MODEL

typ = 'good'
mod = 'REA'
first = 1912
last = 2019
time_step = 'M'
sim_state = 'transient'

watershed_names = ['Lasset']

types_obs = ['streams'] # list of shapefile name layers for clip hydrology

for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
     
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                    first_year = first, last_year = last, time_step = 'M',
                                    sim_state='transient')
    Runof = BV.forcing.runoff # m/month
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        Cmod = Smod['recharge'] * 1000 * 30 # mm/months
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        raw_path = stable_folder+'/'+'hydrometry/'
        Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
        Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
        # area = float(Qobs_path.split('_')[-3])
        area = BV.geographic.area
        Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
        Qobs = Qobs.squeeze()
        Qobs = select_period(Qobs, 2012, 2019)
        Qobs = Qobs.resample('M').mean()
        
        '''
        import hydroeval as he
        nse = he.evaluator(he.nse, Qmod, Qobs, transform='log')[0]
        print(round(nse,2))
        '''
        
        # plt.plot(Cmod)
        # plt.plot(Qobs)
        # plt.plot(Qmod)
        
        fig, axs = plt.subplots(2,1, figsize=(7,6))
        # axs = axs.ravel()
        
        yearsmaj = mdates.YearLocator(2)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
        
        o = Qobs # m/j to mm/month
        s = Qmod # m/j to mm/month
        # nd = 
        sat = Smod['surflow_areas']
        
        k = '{:.1e}'.format(K)
        sy = Sy
        title = watershed_name
        # nselog = round(((nd[0]))*100,1)
        # label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
        #         '$NSE_{log}$ = '+str(nselog)+'%'
        # nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        
        '''
        ax = axs[0]
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.plot(s, color='red', lw=2, label='modeled')
        # ax.plot(s, lw=1, label=label)   
        ax.set_title(title)
        ax.plot(o, color='grey', lw=2, ls='-', zorder=0, label='observed')
        ax.grid('grey')
        ax.set_ylim(-2,200)
        # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
        ax.legend(loc='upper left')
        '''
        
        ax = axs[0]
        ax.set_ylabel('Q / A [mm/month]')
        axb = ax.twinx()
        axb.set_ylabel('R [mm/month]', rotation=270, labelpad=25)
        axb.bar(Cmod.index, Cmod,
                color='blue', edgecolor='blue', lw=2.5)
        axb.set_ylim(0,999)
        axb.invert_yaxis()
        # axb.xaxis.set_major_formatter_locator(yearsmaj)
        # axb.xaxis.set_minor_locator(yearsmin)
        # axb.xaxis.set_major_formatter(years_fmt)
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        ax.plot(o, color='k', lw=2, ls='-', zorder=0, label='observed')
        ax.set_yscale('log')
        ax.plot(s, color='red', lw=2, label='modeled')
        ax.set_ylim(0.11,999)
        # ax.grid('grey')
        # ax.set_title('Discharge')
        # ax.set_xlim(pd.to_datetime('1986'))
        ax.set_xlim(pd.to_datetime('2013'), pd.to_datetime('2019'))
        
        # fig, axs = plt.subplots(1,2, figsize=(7,4))
        ax = axs[1]
        ax.set_ylabel('$A_{sat}$ [%]')
        # axb = ax.twinx()
        # axb.set_ylim(0,1000)
        # axb.invert_yaxis()
        # ax.axhline(y=20, color='k', ls= '--', lw=2)
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)    
        # sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
        ax.plot(Smod['surflow_areas'], color='darkorange', ls='-', lw=2, label='catchment')
        ax.fill_between(Smod.index, Smod['perenn_areas'], Smod['surflow_areas'],
                        interpolate=False, color='darkorange', alpha=0.75)
        # ax.plot(Smod['intermit_areas'], color='darkorange', lw=2, label='upstream')
        ax.plot(Smod['perenn_areas'], color='dodgerblue',
                marker=None, markeredgecolor='none', markerfacecolor='dodgerblue',
                markersize=5, lw=2, label='upstream')
        ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                        interpolate=False, color='dodgerblue', alpha=0.75)
        # ax.plot(sat, lw=1, label=label) 
        ax.set_ylim(0,50)
        # title = 'Saturation'
        # ax.set_title(title)
        ax.set_xlim(pd.to_datetime('2013'), pd.to_datetime('2019'))
        # ax.grid('grey')
        # ax.set_xlim(pd.to_datetime(str(first)), pd.to_datetime(str(last)))
        
        '''
        fig, ax = plt.subplots(1,1, figsize=(6,3))
        Sub_path = glob.glob(simul+'/_subbasins/intermittency_*')[0]+'/_simulated_results.csv'
        Sub = pd.read_csv(Sub_path, sep=';', index_col=0, parse_dates=True)
        # ax.axhline(y=20, color='grey', ls='--', lw = 1, label='approxim. observed')
        # ax.plot(Sub['perenn_areas'], color='dodgerblue', lw=2)
        # ax.plot(Sub['intermit_areas'], color='darkorange', lw=2)
        # ax.legend(loc='upper left')
        d = BV.intermittency.flowing
        assec = d[d==1].dropna()
        invi = d[d==2].dropna()
        low = d[d==3].dropna()
        accep = d[d==4].dropna()
        visib = d[d==5].dropna()
        
        # for u in range(len(noflow)):
        #     ax.axvline(noflow.index[u], color='salmon', linewidth = 5, alpha=1)
        # for u in range(len(flow)):
        #     ax.axvline(flow.index[u], color='lightskyblue', linewidth = 5, alpha=1)
            
        for u in range(len(assec)):
            ax.axvline(assec.index[u], color='salmon', linewidth = 5, alpha=1) # assec
        for u in range(len(invi)):
            ax.axvline(invi.index[u], color='gold', linewidth = 5, alpha=1) # pond
        for u in range(len(low)):
            ax.axvline(low.index[u], color='lightskyblue', linewidth = 5, alpha=1) # bio mal
        for u in range(len(accep)):
            ax.axvline(accep.index[u], color='lightskyblue', linewidth = 5, alpha=1) # bio ok
        for u in range(len(visib)):
            ax.axvline(visib.index[u], color='lightskyblue', linewidth = 5, alpha=1) # ecoul
        
        ax.axhline(y=0, color='dimgray', lw= 1)

        ax.set_xlim(pd.to_datetime('2012'), pd.to_datetime('2020'))
        seep = Sub['seepage_areas']
        seep = seep.fillna(0)
        ax.plot(seep, color='k', ls=(0, (1, 1)), lw=1.5, label='upstream')
        tp = Sub['surflow_areas']
        tp = tp.fillna(0)
        ax.plot(tp, color='k', lw=1.5, label='upstream')
        # cond_coul = 0
        # flow_mod = tp.copy()
        # flow_mod[flow_mod<=cond_coul] = np.nan
        # ax.plot(flow_mod, color='navy', marker='o', markersize=3,
        #         markeredgecolor='none',
        #         lw=2, label='upstream')
        # noflow_mod = tp.copy()
        # noflow_mod[noflow_mod>cond_coul] = np.nan
        # ax.plot(noflow_mod, color='darkred', marker='o', markersize=3,
        #         markeredgecolor='none',
        #         lw=2, label='upstream')
        ax.grid('grey', axis='x')
        ax.set_ylim(-0.6,20)
        ax.set_ylabel('$A_{sat}$ [%]')
        
        months_maj = MonthLocator(7)  # every x month
        ax.xaxis.set_minor_locator(months_maj)
        '''
        
        plt.tight_layout()
        
        # ax.legend(bbox_to_anchor=(1.5, 3), ncol=1)
        # fig.savefig(path_fig+'/'+'_chronic_'+name_file+'.png', dpi=300, bbox_inches='tight')
        # fig.savefig(simul+'/_figures/png/'+'quickly_plot_results'+'.png', dpi=300, bbox_inches='tight')

#%% PLOT INTERMITTENTCY MAP

typ = 'good'

typ_intermit = 'monthly' # yearly or persistency or monthly
gif = True

watershed_names = ['Lasset']

types_obs = ['streams'] # list of shapefile name layers for clip hydrology

first = 2012
last = 2019

for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    years = np.arange(first,last+1,1)
    
    simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
    # simuls = fnmatch.filter(os.listdir(simulations_folder), typ+'*')
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
        
    for simul in simul_list:
    
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        for key in acc_npy:
            # print(key)
            mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
            # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
            acc_npy[key] = np.ma.masked_array(acc_npy[key], mask=(mask<0))
        zero = acc_npy[0] * 0
        for l in range(len(acc_npy)):
            tempo = acc_npy[l].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy() # / len(acc_npy)
        
        if typ_intermit == 'persistency':
            fig, ax = plt.subplots(1,1, figsize=(7,6))
            
            days_flux = days_flux / len(acc_npy)
            im = ax.imshow(np.ma.masked_where(days_flux <= 0, days_flux),
                            cmap = 'coolwarm_r', vmin=0, vmax=1, alpha=1)
            ax.imshow(np.ma.masked_where(days_flux < 1, days_flux),
                      cmap = mpl.colors.ListedColormap('navy'), alpha=1)
            ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            
            divider = make_axes_locatable(ax)
            cax = divider.append_axes('right', size='5%', pad=0.05)
    
            fig.colorbar(im, cax=cax, orientation='vertical',)
    
            ax.set_title(str(years[0])+' to '+str(years[-1]))
            fig.savefig(simul+'/_figures/png/'+'map_intermittent_persistency'+'.png', dpi=300, bbox_inches='tight')
            
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        inf = 0
        sup = 12
        compt = 0
        step = int(round(len(acc_npy)/12))
        
        for i in range(step):
            print(str(i)+'/'+str(step))
            interv = list(acc_npy.items())[inf:sup]
            # print(interv)
            for key in range(len(interv)):
                # key = tupl[0]
                # print(key)
                interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                
            zero = acc_npy[0] * 0
            for j in range(len(interv)):
                tempo = interv[j].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy()
            days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
            days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
            
            if typ_intermit == 'monthly':
                if i > 0:
                    for k in range(len(interv)):
                        to = interv[k].copy()
                        
                        # fig, ax = plt.subplots(1,1, figsize=(7,6))
                        # ax.imshow(to)
                        
                        to[(to>0) & (days_flux==12)] = 2
                        to[(to>0) & (days_flux<12)] = 1
                        
                        to = np.ma.masked_array(to, mask=(mask<0))
                        to = np.ma.masked_array(to, mask=(to<=0))
                        
                        fig, ax = plt.subplots(1,1, figsize=(7,6))
                        # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                        ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                        ax.imshow(np.ma.masked_where(to==1, to), cmap = mpl.colors.ListedColormap(['dodgerblue']))
                        ax.imshow(np.ma.masked_where(to==2, to), cmap = mpl.colors.ListedColormap(['darkorange']))
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        ax.get_xaxis().set_visible(False)
                        ax.get_yaxis().set_visible(False)
                        
                        ax.set_title(str(years[i])+'-'+(str(k+1)))
                        
                        # path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                        # wbt.vector_lines_to_raster(path_sub,
                        #                            glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                        #                            base = stable_folder+'geographic/'+'watershed_dem.tif')
                        # line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                        # line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                        # ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('dimgray'))
                        
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        
                        fig.savefig(simul+'/_figures/png/'+'map_intermittent_monthly_'+str(compt)+'.png', dpi=300, bbox_inches='tight')
        
                        plt.close()
                        
                        compt += 1
                        
                    inf+=12
                    sup+=12
      
                    if gif == True:
                        begin_by = simul+'/_figures/png/'+'map_intermittent_monthly'
                        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
                        images = []
                        for filename in filenames:
                            images.append(imageio.imread(filename))
                        imageio.mimsave(simul+'/_figures/gif/'+'map_intermittent_monthly'+'.gif', images, duration=0.5, loop=0)
                
            if typ_intermit == 'yearly':
                fig, ax = plt.subplots(1,1, figsize=(7,6))
                # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                ax.imshow(np.ma.masked_where(days_flux<12, days_flux), cmap = mpl.colors.ListedColormap(['dodgerblue']))
                ax.imshow(np.ma.masked_where(days_flux==12, days_flux), cmap = mpl.colors.ListedColormap(['darkorange']))
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
    
                ax.set_title(years[i])
            
                # divider = make_axes_locatable(ax)
                # cax = divider.append_axes("right", size="1%", pad=0.05)
                # fig.add_axes(cax)
                # cbar = fig.colorbar(image_hidden, cax=cax, orientation="vertical")
                # val = np.ma.masked_where(mask < 0, mask)
                # minVal =  int(round(np.min(val[np.nonzero(val)],0)))
                # maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
                # meanVal = int(round(minVal+((maxVal-minVal)/2),0))
                # cbar.set_ticks([minVal, meanVal, maxVal])
                # cbar.set_ticklabels([minVal, meanVal, maxVal])
                # cbar.mappable.set_clim(minVal, maxVal)
                # cbar.ax.tick_params(labelsize=10)
            
                fig.savefig(simul+'/_figures/png/'+'map_intermittent_yearly_'+str(i)+'.png', dpi=300, bbox_inches='tight')
                plt.close()
                
                inf+=12
                sup+=12
                
            if gif == True:
                begin_by = simul+'/_figures/png/'+'map_intermittent_yearly'
                filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
                images = []
                for filename in filenames:
                    images.append(imageio.imread(filename))
                imageio.mimsave(simul+'/_figures/gif/'+'map_intermittent_yearly'+'.gif', images, duration=0.5, loop=0)
        
#%% PLOT CROSS SECTION 2D

watershed_name = 'Lasset'

interactive = True
dem_data = BV.geographic.dem_data # dem data
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif') # watertable data
river_data = imageio.imread(stable_folder+'/hydrology/'+'streams.tif') # river data

modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% PLOT STEADY STATE CATCHMENT

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, model_name)
visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth','drain_flow',
                              'surface_flow'],
              color_scale = [(None,None),(None,None),(None,None),(0,10),
                              (None,None),(None,None)])
# visu.visual2D(object_list = ['pathlines', 'residence_times'],
#               color_scale = [(None,None),(None,None)], 
#               lines=100)

#%% PLOT BINS DISTRIBUTIONS

from scipy.stats import binned_statistic

x = Smod.recharge * 30 * 1000
y = Smod.outflow_drain * 30 * 1000

x = np.log(x)
y = np.log(y)

# Method 1
fig, ax = plt.subplots()
ax.scatter(x,y, s=9)
s, edges, _ = binned_statistic(x,y, statistic='mean', bins=np.logspace(min(x),max(x),100))
ys = np.repeat(s,2)
xs = np.repeat(edges,2)[1:-1]
ax.hlines(s,edges[:-1],edges[1:], color="crimson", )
for e in edges:
    ax.axvline(e, color="grey", linestyle="--")
ax.scatter(edges[:-1]+np.diff(edges)/2, s, c="limegreen", zorder=3)
ax.set_xscale("log")
ax.set_yscale("log")
plt.show()

# Method 2
import numpy as np
import matplotlib.pyplot as plt
nbins = 10
n, _ = np.histogram(x, bins=nbins)
sy, _ = np.histogram(x, bins=nbins, weights=y)
sy2, _ = np.histogram(x, bins=nbins, weights=y*y)
mean = sy / n
std = np.sqrt(sy2/n - mean*mean)
fig, ax = plt.subplots()
plt.plot(x, y, 'bo')
plt.errorbar((_[1:] + _[:-1])/2, mean, yerr=std, fmt='r-')
plt.show()

#%% ---- VRAC : INTERMITTENCY

#%% FIG - Map of persistency index

typ = 'good'

watershed_names = ['Lasset']

var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic']

fig2, axs2 = plt.subplots(1,1, figsize=(5,4),
                        sharex=True, sharey=True)

y_name = 'surflow_areas'

for watershed_name in watershed_names:

    color = 'k'

    fig1, axs1 = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)
    # axs1 = axs1.ravel()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

    for ix in np.arange(1,1+1,1):
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
        
        ax = axs1
            
        for sce in sce_list:
            # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
            
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+sce+'*')[0]
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            
            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
            acc_npy = list(acc_npy.items())[-360:]
            # acc_npy = list(acc_npy.items())[360:720]
            
            for key in range(len(acc_npy)):
                # print(key)
                mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
            
            
            toolbox.export_tif(BV.geographic.watershed_dem,
                               days_flux, -9999, simulations_folder+'persistency_tif.tif')

                    
            # ax = ax1
            vmin = 0
            vmax = 1
            
            cmap = plt.cm.jet_r  # define the colormap
            # cmap = parula_map
            cmaplist = [cmap(i) for i in range(cmap.N)]
            # cmaplist[0] = (.5, .5, .5, 1.0)
            cmap = mpl.colors.LinearSegmentedColormap.from_list(
                'Custom cmap', cmaplist, cmap.N)
            bounds = np.arange(0, 1.1, 0.1)
            norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                    
            # pc = ax.imshow(np.ma.masked_where(days_flux <= 0, days_flux),
            #                cmap=cmap, norm=norm, alpha=1)
            
            pc = ax.imshow(np.ma.masked_where(days_flux < 1, days_flux),
                           cmap=mpl.colors.ListedColormap('dodgerblue'), norm=norm, alpha=1)
            pc = ax.imshow(np.ma.masked_where((days_flux == 1) | (days_flux <= 0), days_flux),
                           cmap=mpl.colors.ListedColormap('darkorange'), norm=norm, alpha=1)
            
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            ax.axis('off')
            
            wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                                       stable_folder+'geographic/'+'watershed_contour.tif',
                                       base = stable_folder+'geographic/'+'watershed_dem.tif')
            line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
            line = np.ma.masked_where(line <= 0, line)
            import matplotlib as mpl
            ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
            # ax.set_title(params, fontsize=8)
            plt.subplots_adjust(hspace = -0.6)
            
            ax = axs2
            
            ### Classic histogram
            # masked = days_flux[days_flux >= 0]
            # Z = masked.flatten()
            # from scipy.stats import norm
            # pdf = norm.pdf(Z, Z.mean(), Z.std())
            # ax.hist(Z, bins = 100, density=True,
            #         color = color, edgecolor = 'none', alpha = 0.5)
            # ax.set_yscale('log')
        
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            ### Normalized cumulative evolution of areas in time
            X2 = np.sort(Smod[y_name])
            N = len(Smod[y_name])
            # ax.plot((1-np.arange(0,N,1)/N)*100, (X2-X2.min())/(X2.max()-X2.min()) * 100,
            #         color=color, lw=2)
            ax.plot((1-np.arange(0,N,1)/N)*100, (X2),
                    color=color, lw=2)
            ax.set_xlabel('percent_time [%]')
            ax.set_ylabel(y_name)
            # ax.set_xlim(-5,100)
            # ax.set_ylim(-5,100)
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            
    position=fig1.add_axes([0.93,0.35,0.01,0.30])  ## the parameters are the specified position you set 
    fig1.colorbar(pc,cax=position, orientation="vertical")
    position.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)
    
    # fig1.savefig(figsim_folder+watershed_name+'_persistency_map_historic'+'.png', dpi=300, bbox_inches='tight')

#%% PLOT SATURATION EVOLUTION

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj'
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['CNR-ALA']
sce_list = ['RCP2.6','RCP8.5']
sce_cmap = ["Greens","Reds"]
sce_color = ["dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
scan_list = ['intermit_areas','perenn_areas']

temporal = True
space = 0
norm = False

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    for mod in mod_list:
                
        fig, ax = plt.subplots(1,1, figsize=(8,3))
    
        for sce in sce_list:
            
            print(watershed_name + ' + ' + mod + ' + ' + sce)
            
            simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')
        
            compt = 0
            
            list_max = []
            list_max_per = []
            list_max_int = []
                    
            for it, simul in enumerate(simul_list[:]):
                    
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                if not os.path.exists(Smod_path):
                    compt += 1
                    continue
                
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
                # Smod = Smod.set_index(idx)
                years = Smod.index.year.unique()
                
                Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
                Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
                
                Smod['year'] = Smod.index.year.values # group by month and year, get the average
                Smod['month'] = Smod.index.month.values # group by month and year, get the average
                Smod = Smod.pivot('month','year')
                
                max_per = Smod['perenn_areas'].max().max()
                max_int = Smod['intermit_areas'].max().max()
                max_tot = max(max_per,max_int)
            
                list_max.append(max_tot)
                list_max_per.append(max_per)
                list_max_int.append(max_int)
                
            for it, simul in enumerate(simul_list[:]):
                                
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                if not os.path.exists(Smod_path):
                    compt += 1
                    continue
                
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
                # Smod = Smod.set_index(idx)
                years = Smod.index.year.unique()
                
                Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
                Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
                
                to_see = Smod['intermit_areas'] / Smod['perenn_areas']
                # to_see = Smod['outflow_drain']
                ax.plot(to_see, color = color_dict[sce])
                ax.plot(select_period(to_see, 1960, 2020), color = 'k')
                # ax.set_yscale('log')
                
#%% FIG - Map of persistency index anomaly historic vs future

import matplotlib as mpl

watershed_names = ['Lasset']

typ = 'projec' # name of your identname for future simulations

var = 'REC'
scan = 'outflow_drain'

wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                           stable_folder+'geographic/'+'watershed_contour.tif',
                           base = stable_folder+'geographic/'+'watershed_dem.tif')
line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
line = np.ma.masked_where(line < 0, line)

for watershed_name in watershed_names:

    color = 'k'

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    for mod in ['CNR']:
        
        for sce in ['RCP2.6','RCP8.5']:
    
            ix = 1
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
        
            for simul in simul_list:
                
                fig1, axs1 = plt.subplots(1,1, figsize=(10,10))
            
                ax = axs1
                ax.set_title(mod+' / '+sce)
                
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                
                acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
                
                # Historic
                h = 30 * 12
                acc_npy_h = list(acc_npy.items())[0:h]
                for key in range(len(acc_npy_h)):
                    # print(key)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                    acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<0))
                zero = acc_npy_h[0] * 0
                for i in range(len(acc_npy_h)):
                    tempo = acc_npy_h[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux_h = zero.copy() / len(acc_npy_h)
                # ax.imshow(days_flux_h)
            
                # To look
                acc_npy = list(acc_npy.items())[-h:]
                # acc_npy = list(acc_npy.items())[h:]
                for key in range(len(acc_npy)):
                    # print(key)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                    acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
                zero = acc_npy[0] * 0
                for i in range(len(acc_npy)):
                    tempo = acc_npy[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux = zero.copy() / len(acc_npy)
                
                # Anomaly
                days_flux_ano = ( (days_flux - days_flux_h) ) * 100
                
                masked = days_flux_ano
                Z = masked.flatten()
                from scipy.stats import norm
                pdf = norm.pdf(Z, Z.mean(), Z.std())
            
                print(days_flux_ano.min(), days_flux_ano.max())
                
                cmap = plt.cm.Oranges_r
                cmaplist = [cmap(i) for i in range(cmap.N)]
                cmaplist = ['darkred','orange']
                # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                minn = -20
                maxn = 0.1
                intn = 2.5
                bounds = np.arange(minn, maxn, intn)
                norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                pcn = ax.imshow(np.ma.masked_where(days_flux_ano >= 0, days_flux_ano),
                                cmap = cmap,
                                norm=norm, alpha=1)
                # plt.imshow(days_flux_ano)
                # plt.colorbar()
                
                cmap = plt.cm.Blues
                # cmap = plt.cm.winter_r
                cmaplist = [cmap(i) for i in range(cmap.N)]
                cmaplist = ['deepskyblue','navy']
                # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                minp = 0
                maxp = 2.1
                intp = 0.25
                bounds = np.arange(minp, maxp, intp)
                norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                pcp = ax.imshow(np.ma.masked_where(days_flux_ano <= 0, days_flux_ano),
                                cmap = cmap,
                                norm=norm, alpha=1)
                # plt.imshow(np.ma.masked_where(days_flux_ano <= 0, days_flux_ano))
                # plt.colorbar()
                
                pc = ax.imshow(np.ma.masked_where((days_flux_ano!=0)|(days_flux_h==0),
                                                  days_flux_ano),
                                            cmap = mpl.colors.ListedColormap('forestgreen'))
                
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                ax.axis('off')
    
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                # ax.set_title(params, fontsize=8)
                plt.subplots_adjust(hspace = -0.6)
            
            position=fig1.add_axes([1,0.3,0.015,0.32])  ## the parameters are the specified position you set 
            cb = fig1.colorbar(pcp,cax=position) ##
            cb.set_ticks(np.arange(minp, maxp, intp))
            cb.set_ticklabels(np.arange(minp, maxp, intp).round(1))
            # cb.ax.invert_xaxis()
            
            position=fig1.add_axes([1.10,0.3,0.015,0.32])  ## the parameters are the specified position you set 
            cb = fig1.colorbar(pcn,cax=position) ##   
            cb.set_ticks(np.arange(minn, maxn, intn))
            cb.set_ticklabels(np.arange(minn, maxn, intn))
            
            # fig1.savefig(figsim_folder+
            #              watershed_name+'_'+mod+'_'+sce+'_'+
            #              '_anamaly'+'.png', dpi=300, bbox_inches='tight')

#%% FIG - Histogramm disribution of anomaly persistency index historic vs future

import matplotlib as mpl

watershed_names = ['Lasset']

typ = 'projec'

var = 'REC'
scan = 'outflow_drain'

for watershed_name in watershed_names:

    color = 'k'
        
    rcp26 = pd.DataFrame()
    rcp85 = pd.DataFrame()
        
    fig2, ax2 = plt.subplots(1,1, figsize=(5,4),
                            sharex=True, sharey=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line < 0, line)
    
    for mod in ['CNR']:
        
        for sce in ['RCP2.6','RCP8.5']:
    
            ix = 1
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
        
            for simul in simul_list:
                
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                
                acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
                
                # Historic
                acc_npy_h = list(acc_npy.items())[0:30*12]
                for key in range(len(acc_npy_h)):
                    # print(key)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                    acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<0))
                zero = acc_npy_h[0] * 0
                for i in range(len(acc_npy_h)):
                    tempo = acc_npy_h[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux_h = zero.copy() / len(acc_npy_h)
                # ax.imshow(days_flux_h)
            
                # To look
                acc_npy = list(acc_npy.items())[-30*12:] # -80*12:-50*12
                # acc_npy = list(acc_npy.items())[h:]
                for key in range(len(acc_npy)):
                    # print(key)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                    acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
                zero = acc_npy[0] * 0
                for i in range(len(acc_npy)):
                    tempo = acc_npy[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux = zero.copy() / len(acc_npy)
                
                # Anomaly
                days_flux_ano = ( (days_flux - days_flux_h) ) * 100
                data = days_flux_ano[~days_flux_ano.mask]
                
                masked = data
                # masked = days_flux_ano
                Z = masked.flatten()
                from scipy.stats import norm
                pdf = norm.pdf(Z, Z.mean(), Z.std())
                                
                if sce == 'RCP2.6':
                    color = 'dodgerblue'
                    rcp26[mod] = Z
                if sce == 'RCP8.5':
                    color = 'red'
                    rcp85[mod] = Z
    
                # import seaborn as sns
                # sns.distplot(Z, bins=100, rug = False, hist = True, kde = False, norm_hist = True,
                #       kde_kws = {'shade': True, 'linewidth': 0.5},
                #       rug_kws={"color": "k"},
                #       hist_kws={"histtype": "step", "linewidth": 1, "alpha": 1},
                #       color=color)
                
                # ax2.hist(Z, bins = 100, density=True,
                #         color = color, edgecolor = 'none')
                
                heights, edges = np.histogram(Z, bins=100, density=True)
                left_edges = edges[:-1]
                # width = 0.85*(left_edges[1] - left_edges[0])
                ax2.bar(left_edges, heights, align='edge', width=1/5,
                        lw=0, color=color, alpha=0.5)
    
    # hist26, edg26  = np.histogram(rcp26.mean(axis=1), bins=100, density=True)
    # ax2.plot(edg26[:-1], hist26, lw=1, color='dodgerblue')
    # hist85, edg85  = np.histogram(rcp85.mean(axis=1), bins=100, density=True)
    # ax2.plot(edg85[:-1], hist26, lw=1, color='red')
    
    ax2.set_xlim(-30,10)
    ax2.set_ylim(1e-3,1)
    ax2.set_title(watershed_name)
    ax2.set_yscale('log')
    ax2.set_xlabel('Persistency index anomaly [%]')
    ax2.set_ylabel('Density')
    
    # fig1.savefig(figsim_folder+
    #               watershed_name+'_'+mod+'_'+sce+'_'+
    #               '_anamaly'+'.png', dpi=300, bbox_inches='tight')
                    
#%% ---- VRAC : RELATIONSHIPS

#%% FIG : Hysteresis of discharge

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['historic','RCP2.6','RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
    xn = 0.1
    xx = 100
    yn = 0.1
    yx = 100
    ax = axs1
    ax.set_title(mod_list)
    ax.set_aspect('equal', adjustable='box')
    from mpl_toolkits.axes_grid1.inset_locator import inset_axes
    axz = inset_axes(ax, width="40%", height="40%", loc='upper left',
                     bbox_to_anchor=(0.0,0,1,1), bbox_transform=ax.transAxes)
    axz.set_aspect('equal', adjustable='box')
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')
        # from mpl_toolkits.axes_grid1.inset_locator import inset_axes
        # axz = inset_axes(ax, width="40%", # width = 30% of parent_bbox
        #                   height=1., # height : 1 inch
        #                   loc=2)
        # axz.set_aspect('equal', adjustable='box')
            
        for sce in sce_list:
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            Qmod = (Smod[scan] * 1000 * 30).squeeze()   # mm/months            
            Cmod = Smod['recharge'] * 1000 * 30 # mm/months

            if sce == 'historic' :
                Qmod = select_period(Qmod, 1990, 2019)
                Cmod = select_period(Cmod, 1990, 2019)
            if sce != 'historic':
                Qmod = select_period(Qmod, 2070, 2099)
                Cmod = select_period(Cmod, 2070, 2099)
            
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
            
            hyst = Hysteresis(DFmod, simul)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            
            color = color_dict[sce]
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            dfmean = hyst.dfmet.iloc[-1]
            
            for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
                data = pd.DataFrame()
                data['inx'] = hyst.xrecapl[colx]
                data['iny'] = hyst.yrecapl[coly]
                # ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i], alpha=0.75, zorder=0)
            ax.plot(data.inx, data.iny, linestyle = '-', lw=2, color=color, zorder=1)

            # ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap=cmap_dict[sce], marker=".", 
            #            s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=0)
            # ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
            #         markerfacecolor='white', linestyle = 'None') 
            # for k in hyst.wyi:
            #     ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
            #                 color='black', weight="bold", ha='center', va='center')
            
            for k in hyst.wyi:
                # if (k == 10) | (k == 11) | (k == 12) | (k == 1) | (k == 2) | (k == 3) | (k == 4) :
                if (k == 12) :
                    ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=0, lw=0,
                              markeredgecolor='k', markerfacecolor=color,
                              mew=0, linestyle = '-')
                    # ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=7,
                    #           markeredgecolor=color, markerfacecolor='white',
                    #           mew=1,
                    #           linestyle = 'None', zorder=csce+cp+cont)
                    # ax.annotate(k,(hyst.xi[k],hyst.yi[k]),
                    #               family='sans-serif', fontsize=5, 
                    #               color=color, weight="bold", ha='center', va='center',
                    #               zorder=csce+cp+cont)
                    
            # ax.xaxis.set_ticks(np.arange(xn, xx+1, 25))
            # ax.yaxis.set_ticks(np.arange(yn, xx+1, 25))
            # ax.errorbar(hyst.xi, hyst.yi,
            #             yerr=np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi]),
            #             xerr=np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi]),
            #             ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
            #             capthick=0.5, zorder=1)
            
            polyg_loop = Polygon(tuple(hyst.data.itertuples(index=False, name=None)))
            xpolyg, ypolyg = polyg_loop.exterior.xy
            maxi = 1.5
            mini = -0.1
            line_oneone = SG.LineString([(mini,mini), (maxi,maxi)])
            areas = cut_polygon_by_line(polyg_loop, line_oneone)
            from descartes import PolygonPatch
            for i in range(len(areas)):
                ring_patch = PolygonPatch(areas[i], color=color, alpha=0.6, lw=0, ec="k", zorder=1000)
                # ax.add_patch(ring_patch)
            
            # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
            ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
                    linestyle='--', color='grey', linewidth=1.5, zorder=-1)

            ax.grid(color='grey',alpha=0.2)
            ax.set_ylabel('Q [mm/month]')
            ax.set_xlabel('R [mm/month]')
            
            # AX ZOOM
            axz.plot(data.inx, data.iny, linestyle = '-', lw=1, color=color, zorder=1)
            xmin, xmax = axz.get_xlim()
            ymin, ymax = axz.get_ylim()
            axz.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
                    linestyle='--', color='grey', linewidth=1, zorder=-1)
            axz.set_xlim(xn,xx)
            axz.set_ylim(yn,yx)
            axz.get_xaxis().set_visible(False)
            axz.get_yaxis().set_visible(False)
            axz.set_xscale('log')
            axz.set_yscale('log')
            # axz.axis('off')
            for axis in ['top','bottom','left','right']:
                axz.spines[axis].set_linewidth(1)

    plt.tight_layout()
                        
    # fig1.savefig(figsim_folder+'hysteresis_loop'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Evolution of saturation and proportion intermittency

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
mod_list = ['NOR1']
sce_list = ['RCP2.6','RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
scan_list = ['intermit_areas','perenn_areas']

temporal = True
space = 0
norm = False

watershed_names = ['Canut','Nancon']
watershed_names = ['Canut']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    for mod in mod_list:
                
        fig, axs = plt.subplots(1,2, figsize=(8,3))
        axs = axs.ravel()
    
        for sce in sce_list:
            
            print(watershed_name + ' + ' + mod + ' + ' + sce)
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*')
        
            compt = 0
            
            list_max = []
            list_max_per = []
            list_max_int = []
                    
            for it, simul in enumerate(simul_list[:]):
                    
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                if not os.path.exists(Smod_path):
                    compt += 1
                    continue
                
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
                # Smod = Smod.set_index(idx)
                years = Smod.index.year.unique()
                
                Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
                Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
                
                Smod['year'] = Smod.index.year.values # group by month and year, get the average
                Smod['month'] = Smod.index.month.values # group by month and year, get the average
                Smod = Smod.pivot('month','year')
                
                max_per = Smod['perenn_areas'].max().max()
                max_int = Smod['intermit_areas'].max().max()
                max_tot = max(max_per,max_int)
            
                list_max.append(max_tot)
                list_max_per.append(max_per)
                list_max_int.append(max_int)
                
            for it, simul in enumerate(simul_list[:]):
                
                ax = axs[it]
                
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                if not os.path.exists(Smod_path):
                    compt += 1
                    continue
                
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
                # Smod = Smod.set_index(idx)
                years = Smod.index.year.unique()
                
                Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
                Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
                
                Smod['year'] = Smod.index.year.values # group by month and year, get the average
                Smod['month'] = Smod.index.month.values # group by month and year, get the average
                Smod = Smod.pivot('month','year')
                
                max_per = Smod['perenn_areas'].max().max()
                max_int = Smod['intermit_areas'].max().max()
                max_tot_per = max(list_max_per)
                max_tot_per = 5
                max_tot_int = max(list_max_int) 
                max_tot_int = 20
                max_tot = max(list_max)
                max_tot = 20
                
                # fig, ax = plt.subplots(1,1, figsize=(8,5))
                from matplotlib import colors
                import matplotlib.cm as cmx
                
                for year in years[:]:
                    p = Smod[['prop_perenn','perenn_areas']]
                    i = Smod[['prop_intermit','intermit_areas']]
                                        
                    p = p.droplevel(level=0, axis=1)
                    p = p[year]
                    p.columns = ['prop_perenn','perenn_areas']
                    p = p.sort_values('prop_perenn', ascending=False)
                    p['prop_perenn'] = p.prop_perenn.cumsum() / 12
                        
                    p1 = p.prop_perenn.shift(+1)
                    p1.iloc[0] = 0
                    x1 = p1.values
                    x2 = p.prop_perenn.values
                    values = p.perenn_areas.values
                    # jet = cm = plt.get_cmap('winter_r')
                    cmaplist = ['c','deepskyblue','dodgerblue','blue','navy']
                    cmaplist = ['lightgreen','seagreen']
                    import colorcet as cc
                    # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                    cmap = mpl.colors.LinearSegmentedColormap.from_list(
                        'Custom cmap', cmaplist)
                    cmap = cc.cm.kbc_r
                    # cmap = 'cool_r'
                    jet = cm = plt.get_cmap(cmap)
                    cNorm  = colors.Normalize(vmin=0, vmax=max_tot_per)
                    scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
                    if year == 2020:
                        if it==1:
                            position=fig.add_axes([1.1,0.3,0.02,0.35])  ## the parameters are the specified position you set 
                            cb = fig.colorbar(scalarMap,cax=position) ##
                            cb.set_label('Saturation [%]', rotation=270, labelpad=30)
                        
                    for idx, x, y in zip(values, x1, x2):          
                        colorVal = scalarMap.to_rgba(idx)  
                        start = x
                        endp = y
                        width = endp-start
                        ax.bar(x = year, height=width, bottom=start, width=1,
                                label = str(idx), color=colorVal, lw=0)
                    
                    i = i.droplevel(level=0, axis=1)
                    i = i[year]
                    i.columns = ['prop_intermit','intermit_areas']
                    i = i.sort_values('prop_intermit', ascending=True)
                    i['prop_intermit'] = i.prop_intermit.cumsum() / 12
                    
                    i1 = i.prop_intermit.shift(+1)
                    i1.iloc[0] = 0
                    i1 = i1 + endp
                    x1 = i1.values
                    x2 = i.prop_intermit.values + endp
                    values = i.intermit_areas.values
                    # jet = cm = plt.get_cmap('autumn_r')
                    cmaplist = ['darkred','red','orangered','orange']
                    cmaplist = ['saddlebrown','moccasin']
                    import colorcet as cc
                    # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                    cmap = mpl.colors.LinearSegmentedColormap.from_list(
                        'Custom cmap', cmaplist)
                    cmap = cc.cm.fire_r
                    # cmap = 'Wistia'
                    jet = cm = plt.get_cmap(cmap) 
                    cNorm  = colors.Normalize(vmin=0, vmax=max_tot_int)
                    scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
                    if year == 2020:
                        if it==1:
                            position=fig.add_axes([1,0.3,0.02,0.35])  ## the parameters are the specified position you set 
                            cb = fig.colorbar(scalarMap,cax=position) ## 
            
                    for idx, x, y in zip(values, x1, x2):          
                        colorVal = scalarMap.to_rgba(idx)
                        start = x
                        endi = y
                        width = endi-start
                        ax.bar(x = year, height = width, bottom=start, width = 1,
                                label = str(idx), color=colorVal, lw=0)
                    
                    ax.set_ylim(0,1)
                    bal = ((i.prop_intermit.sum()) + (p.prop_perenn.sum())).sum()
                    min_max = [2020, 2099]
                    ax.set_xlim(min_max)
                    ax.set_xticks(np.arange(min_max[0], min_max[1]+2, 20.0))
                    tox = np.arange(min_max[0], min_max[1]+2, 20.0).astype(int)
                    ax.set_xticklabels(tox)
                    
                    if ((it) == 0) | ((it) == 3) | ((it) == 6):
                        ax.set_ylabel('Proportion of network')
                                 # ax.set_ylabel('$Eccent_{ratio}$ [-]')
                    if ((it) == 6) | ((it) == 7) | ((it) == 8):
                        ax.set_xlabel('Date')
                        
                    x_ticks = ax.xaxis.get_major_ticks()
                    x_ticks[0].label1.set_visible(False) ## set first x tick label invisible
                    x_ticks[-1].label1.set_visible(False)
                    
            # plt.tight_layout()
            
            # fig1.savefig(figsim_folder+'matrix_evol_'+sce+'.png',
            #               dpi=300, bbox_inches='tight', transparent=True)

#%% FIG : Boxplot of discharge

sim_state='transient'
time_step = 'M'
mod = 'NOR1'
typ = 'projnor'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic','RCP2.6','RCP8.5']
# sce_list = ['historic']
sce_cmap = ["Blues","Reds"]
sce_color = ['grey',"dodgerblue","red"]

cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

scan_list = ['surflow_areas','perenn_areas','intermit_areas']
bxlim = (0.5,3.5)
sce_pos = ["1","2","3"]
pos_dict = dict(zip(sce_list, sce_pos))

temporal = True
space = -10
norm = False

fig1, axs = plt.subplots(3,3, figsize=(9,9))
axs = axs.ravel()
xmin = []
xmax = []
ymin = []
ymax = []
            
compt = 1

f = 2020
l = 2099

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
ord_min = []
ord_max = []

metric = 'qmean'

for ix in np.arange(1,9+1,1):
    # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
    
    ax = axs[ix-1]
    # ax.set_aspect('equal', adjustable='box')
    
    csce = 20
    for sce in sce_list:
        if sce == 'historic':
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+'RCP8.5'+'*')[0]
        
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        else:
            simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
        print(simul)
        
        print(sce)

        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                 first_year = 1960, last_year = 2010,
                                                 time_step = time_step, sim_state=sim_state)
        Hist = BV.forcing.recharge
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = 1960, last_year = 2099, 
                                          time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
            BV.forcing.update_recharge(Rech, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            
        # idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        # Smod = Smod.set_index(idx)
        if sce == 'historic':
            Smod = select_period(Smod, 1960, 2010)
        else:
            Smod = select_period(Smod, f, l)
        
        Smod.recharge = Rech
        
        Qmod = Smod[scan]
        if scan == 'outflow_drain':
            Qmod = Qmod * 1000 # mm/months
            Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        # hyst = Hysteresis(DFmod, simul)
        # hyst.prepare_xy_raw()
        # hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
        # columns_x = hyst.xrecapl.columns
        # columns_y = hyst.yrecapl.columns
        
        color = color_dict[sce]
        print(color)
        
        # dfevol = hyst.dfmet.iloc[:-1]
        # dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        # dfmean = hyst.dfmet.iloc[-1]

        ################ FIG 2 ################
        # ax.set_title(params, fontsize=8)
        # fig3.suptitle(metric.upper(), y=0.98)
        boxprops = dict(linestyle='-', linewidth=1, color='black',
                        facecolor=color)
        medianprops = dict(linestyle='-', linewidth=1, color='black')
        meanpointprops = dict(markersize=3, marker='o', markeredgecolor='black',
                              markerfacecolor='black', linestyle='-')
        
        if sce !='historic':
            bp = ax.boxplot(Qmod[(Qmod.index.year>=2020)&(Qmod.index.year<2060)],
                            positions=[int(pos_dict[sce])-0.1],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
            for element in bp['whiskers']:
                element.set_color('k')
                element.set_linestyle('-')
            bp = ax.boxplot(Qmod[(Qmod.index.year>=2060)&(Qmod.index.year<2100)],
                            positions=[int(pos_dict[sce])+0.1],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
            for element in bp['whiskers']:
                element.set_color('k')
                element.set_linestyle('-')
        else:
            bp = ax.boxplot(Qmod, positions=[int(pos_dict[sce])],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
        for element in bp['whiskers']:
            element.set_color('k')
            element.set_linestyle('-')

        # ax.scatter(int(pos_dict[sce]), Qmod.min(), marker='.',color='dimgrey',s = 3)
        # ax.scatter(int(pos_dict[sce]), Qmod.max(), marker='.',color='dimgrey',s = 3)
        # ax.scatter(int(pos_dict[sce]),
        #             Qmod.mean()-Qmod.std(),
        #             marker='_',color='dimgrey',s = 7, zorder=2)
        # ax.scatter(int(pos_dict[sce]),
        #             Qmod.mean()+Qmod.std(),
        #             marker='_',color='dimgrey',s = 7, zorder=2)
        
        ax.set_xticks(np.arange(1,len(sce_list)+1,1))
        # ax.set_xticklabels([x.upper() for x in sce_list], fontsize=10)
        # bmin.append(Qmod.min())
        # bmax.append(Qmod.max())
        # plt.setp(axs3, ylim=(min(bmin),max(bmax)))
        ax.set_ylim(-0.1,2.5)
        # ax.set_xlim(bxlim)
        plt.tight_layout()

        # if ((ix-1) == 6) | ((ix-1) == 7) | ((ix-1) == 8):
        #     ax.set_xlabel('Date')
        
        # ord_min.append(q25.min())
        # ord_max.append(q75.max())
        # plt.setp(axs, ylim=(min(ord_min),max(ord_max)))
        # plt.setp(axs, ylim=(0.05,3))
        

plt.tight_layout()

fig1.savefig(figsim_folder+'boxplot_discharge'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Intermensual of discharge

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

sim_state='transient'
time_step = 'M'
mod = 'NOR1'
typ = 'projnor'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic','RCP2.6','RCP8.5']
# sce_list = ['historic']
sce_cmap = ["Blues","Reds"]
sce_color = ['k',"dodgerblue","red"]

cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

temporal = True
space = -10
norm = False

fig1, axs = plt.subplots(3,3, figsize=(10,9))
axs = axs.ravel()
xmin = []
xmax = []
ymin = []
ymax = []
            
compt = 1

f = 2020
l = 2099

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
ord_min = []
ord_max = []

for ix in np.arange(1,9+1,1):
    # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
    
    ax = axs[ix-1]
    # ax.set_aspect('equal', adjustable='box')
    
    csce = 20
    for sce in sce_list:
        if sce == 'historic':
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+'RCP8.5'+'*')[0]
        
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        else:
            simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
        print(simul)
        
        print(sce)

        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                 first_year = 1960, last_year = 2010,
                                                 time_step = time_step, sim_state=sim_state)
        Hist = BV.forcing.recharge
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = 1960, last_year = 2099, 
                                          time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
            BV.forcing.update_recharge(Rech, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            
        # idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        # Smod = Smod.set_index(idx)
        if sce == 'historic':
            Smod = select_period(Smod, 1960, 2005)
        else:
            Smod = select_period(Smod, f, l)
        
        Smod.recharge = Rech
        
        Qmod = Smod[scan] 
        Qmod = Qmod * 1000 # mm/months
        Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        hyst = Hysteresis(DFmod, simul)
        hyst.prepare_xy_raw()
        hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
        columns_x = hyst.xrecapl.columns
        columns_y = hyst.yrecapl.columns
        
        color = color_dict[sce]
        print(color)
        
        dfevol = hyst.dfmet.iloc[:-1]
        dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        dfmean = hyst.dfmet.iloc[-1]

        ################ FIG 2 ################
                       
        # ax = axs2
        # ax.set_title(params, fontsize=8)
        # fig2.suptitle(metric.upper(), y=0.98)
        # ax.plot(dfevol[metric], dfevol.index, linestyle = '-', lw=2, color=color,
        #         zorder=1)
        
        mean = hyst.y.groupby([lambda x: x.month]).mean()
        mean = mean.append(mean.iloc[[0]])
        mean.index = np.arange(1,14,1)
        q25 = hyst.y.groupby([lambda x: x.month]).quantile(0.25)
        q25 = q25.append(q25.iloc[[0]])
        q25.index = np.arange(1,14,1)
        q75 = hyst.y.groupby([lambda x: x.month]).quantile(0.75)
        q75 = q75.append(q75.iloc[[0]])
        q75.index = np.arange(1,14,1)
        
        # if scan == 'perenn_areas':
        #     alpha=0.5
        ax.plot(mean, color=color, lw=2)
        ax.fill_between(mean.index, q25, q75, alpha=0.2, color=color,
                          linewidth=0)
        xticks = np.arange(1,13+1,1)
        mois = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
        ax.set_xticks(xticks)
        ax.set_xticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
        ax.set_xlim(1,13)
        
        ax.set_yscale('log')
        # ax.fill_between(dfevol.index, dfevol.q10, dfevol.q90, linestyle = '-',
        #                  lw=0, color=color, alpha=0.25)
        # ax.plot(dfevol.qmean, linestyle = '-', lw=2, color=color,
        #         zorder=1)

        # ax.plot(dfevol[dfevol.index.year<=2021][metric], linestyle = '-', lw=3, color='k',
        #         zorder=40)
        
        # metric = 'excent'
        # ax.plot(dfevol[metric], dfevol.index, linestyle = '-', lw=2, color=color,
        #         zorder=1)
        # metric1 = 'slope'
        # metric2 = 'slope_abs'
        # ax.plot(dfevol[metric1]/dfevol[metric2], dfevol.index, linestyle = '-', lw=2, color='pink',
        #         zorder=1)
        
        # ax.set_xscale('log') 
        # ax.axhline(1, linestyle = '--', lw=2, color='grey', zorder=0)
        # ax.set_xlim(-10,100)
        # ax.set_ylim(1,8)
        
        
        # years_maj = YearLocator(40)   # every x year
        # # years_min = YearLocator(1)
        # years_maj_fmt = DateFormatter('%Y')
        # # months_maj = MonthLocator(6)  # every x month
        # # months_min = MonthLocator(3)
        # # months_maj_fmt = DateFormatter('%m') #b = name of month ?
        # ax.xaxis.set_major_locator(years_maj)
        # # ax.xaxis.set_minor_locator(years_min)
        # ax.xaxis.set_major_formatter(years_maj_fmt)
        # # ax.set_ylim(0,40)
        # ymin.append(dfevol.index.year.min())
        # ymax.append(dfevol.index.year.max())
        # xmin.append(dfevol[metric].min())
        # xmax.append(dfevol[metric].max())
        # ax.set_xlim(pd.to_datetime(str(1960-space)),pd.to_datetime(str(2100+1)))
        
        
        # ax.set_ylim(0.5,4)
        # ax.set_ylim(0,25)
        plt.tight_layout()
        # ax.set_yticks(np.arange(1,4+1,1))
        # ax.set_yticklabels(np.arange(1,4+1,1))
        # ax.set_yticks(np.arange(5,25+1,5))
        # ax.set_yticklabels(np.arange(5,25+1,5))
        # ax.invert_yaxis()
        # ax.grid('grey')
        
        if ((ix-1) == 0) | ((ix-1) == 3) | ((ix-1) == 6):
            ax.set_ylabel('Q [mm/month]')
            # ax.set_ylabel('$Eccent_{ratio}$ [-]')
        if ((ix-1) == 6) | ((ix-1) == 7) | ((ix-1) == 8):
            ax.set_xlabel('Date')
        
        ord_min.append(q25.min())
        ord_max.append(q75.max())
        plt.setp(axs, ylim=(min(ord_min),max(ord_max)))
        plt.setp(axs, ylim=(0.05,3))

plt.tight_layout()

fig1.savefig(figsim_folder+'intermensual_discharge'+'.svg', dpi=300, bbox_inches='tight')
fig1.savefig(figsim_folder+'intermensual_discharge'+'.png', dpi=300, bbox_inches='tight')

#%% FIG : Time anomaly evolution historic vs future 

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['historic','RCP2.6','RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = True
space = -10
norm = False

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig1, axs1 = plt.subplots(1,1, figsize=(8,3))
    ax = axs1
    
    for mod in mod_list:
            
        for sce in sce_list:
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            
            idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
            # Smod = Smod.set_index(idx)
            years = Smod.index.year.unique()
            
            Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
            Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
            Smod['prop_ratio'] = Smod['prop_intermit'] / Smod['prop_perenn']
            
            Smod['year'] = Smod.index.year.values # group by month and year, get the average
            Smod['month'] = Smod.index.month.values # group by month and year, get the average
            # Smod = Smod.pivot('month','year')
            
            # ax.plot(Smod.surflow_areas)
            
            max_per = Smod['perenn_areas'].max().max()
            max_int = Smod['intermit_areas'].max().max()
            max_tot = max(max_per,max_int)
        
            intm = select_period(Smod, 1960,2021)
            intm = intm.groupby([lambda x: x.month]).mean()
            
            list_max.append(max_tot)
            
            for i in intm.month.values:
                Smod.loc[Smod.index.month==i, 'ano_prop_ratio'] = Smod.loc[Smod.index.month==i,'prop_ratio'] \
                                                                  - intm.loc[intm.month==i,'prop_ratio'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_intermit_areas'] = Smod.loc[Smod.index.month==i,'intermit_areas'] \
                                                                  - intm.loc[intm.month==i,'intermit_areas'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_perenn_areas'] = Smod.loc[Smod.index.month==i,'perenn_areas'] \
                                                                  - intm.loc[intm.month==i,'perenn_areas'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_surflow_areas'] = Smod.loc[Smod.index.month==i,'surflow_areas'] \
                                                                  - intm.loc[intm.month==i,'surflow_areas'].values[0]                   
            col = 'ano_prop_ratio'
            ax.set_ylim(-1,1)
            ax.set_ylabel('Anomaly')
            ax.set_xlabel('Date')
    
            plus = Smod[col][Smod[col] >= 0]
            minus = Smod[col][Smod[col] < 0]
            
            color = color_dict[sce]
            
            if sce == 'historic':
                zorder = 10
                Smod = select_period(Smod, 1990, 2021)
                Smod = Smod.resample('Y').mean()
                Smod = Smod.rolling(window=10).mean()#.shift(-10)
            else:
                zorder = 0
                Smod = select_period(Smod, 2021, 2099)
                Smod = Smod.resample('Y').mean()
                Smod = Smod.rolling(window=10).mean()#.shift(-10)
            
            ax.plot(Smod[col], color=color, zorder=zorder)
            ax.axhline(y=0, c='k')
            ax.set_xlim(pd.to_datetime(str(1990)),pd.to_datetime(str(2100)))
            plt.xticks(rotation='horizontal')
            plt.xlabel('Date')
            ax.axvspan(pd.to_datetime(str(1990)), pd.to_datetime(str(2021)), color='lightgrey', alpha=0.1, zorder=0)

            years = mdates.YearLocator(20)   # every year
            yearsmin = mdates.YearLocator(1)
            years_fmt = mdates.DateFormatter('%Y')
            months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            ax.xaxis.set_major_locator(years)
            ax.xaxis.set_minor_locator(yearsmin)
            ax.xaxis.set_major_formatter(years_fmt)
            
plt.tight_layout()

# fig1.savefig(figsim_folder+'evolution_intermitperenn'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Relation between recharge/discharge and intermittency 

from scipy.stats import binned_statistic

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['RCP2.6','RCP8.5']
sce_list = ['RCP8.5']
sce_cmap = ["Greens","Reds"]
sce_color = ["dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# x_name = 'outflow_drain'
x_name = 'recharge'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
xmin = []
xmax = []
ymin = []
ymax = []

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
    xn = 1e-6
    xx = 1e-2
    yn = 1e-3
    yx = 1e1
    ax = axs1
    ax.set_title(mod_list)
    # ax.set_aspect('equal', adjustable='box')
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            if sce == 'historic':
                Smod = select_period(Smod, 1960, 2005)
            else:
                Smod = select_period(Smod, 2020, 2099)
            
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
            
            ax = axs1
            # ax.set_aspect('equal', adjustable='box')
            # ax.scatter(Qmod, Smod.seepage_areas, color='grey', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.surflow_areas, color='k', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.perenn_areas, color='dodgerblue', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.intermit_areas, color='darkorange', ec='none',
            #            s=30, alpha=0.5)
            
            if sce == 'RCP2.6':
                color = 'dodgerblue'
            if sce == 'RCP8.5':
                color = 'red'
            
            ax.scatter(Smod[x_name],
                       (Smod[y_name]),
                       c=Smod.index.month, ec='none',
                        s=30, alpha=0.5)
            
            if y_name == 'outflow_drain':
                ax.set_yscale('log')
                x = Smod[x_name]
                y = Smod[y_name]
                y[y==0] = 0.001
                x = np.log10(x)
                y = np.log10(y)
                maxim = max(max(x),max(y))
                minim = min(min(x),np.nanmin(y[y != -np.inf]))
                s, edges, _ = binned_statistic(x, y, statistic='mean',
                                               bins=np.geomspace(minim,maxim,25))
                the_x = edges[:-1]+np.diff(edges)/2
                the_y = s.copy()
                ax.scatter(10**the_x, 10**the_y, c="white", zorder=3)       
            
            if y_name == 'prop_ratio':
                ax.set_yscale('log')
                
                x = Smod[x_name]
                y = Smod[y_name]
                y[y==0] = 0.001
                # x = np.log(x)
                # y = np.log(y)
                maxim = max(max(x),max(y))
                minim = min(min(x),np.nanmin(y[y != -np.inf]))
                s, edges, _ = binned_statistic(x, y, statistic='mean',
                                               bins=np.geomspace(minim,maxim,25))
                the_x = edges[:-1]+np.diff(edges)/2
                the_y = s.copy()
                ax.scatter(the_x, the_y, c="white", zorder=3)  
            
            # ax.scatter(Qmod, Smod.surflow_areas, color=color, ec='none',
            #            s=30, alpha=0.5)
                        
            ax.grid(color='grey',alpha=0.2)
                
            plt.tight_layout()
            
            ax.set_xlabel(x_name)
            ax.set_ylabel(y_name)
            
            ax.set_xscale('log')
            
            xmin.append(Smod[x_name].min())
            xmax.append(Smod[x_name].max())
            ymin.append(Smod[y_name].min())
            ymax.append(Smod[y_name].max())
            
            if xn == []:
                plt.setp(ax,
                         xlim=(min(xmin),max(xmax)),
                         ylim=(min(ymin),max(ymax)))
            else:
                ax.set_xlim(xn,xx)
                ax.set_ylim(yn,yx)
            
    fig1.tight_layout()
    # fig1.savefig(figsim_folder+'relation_qall'+'.png', dpi=300, bbox_inches='tight')

#%% FIG : Pdf proportion of intermittency vers perennial part

from scipy.stats import binned_statistic

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['RCP2.6','RCP8.5']
# sce_list = ['RCP8.5']
sce_cmap = ["Greens","Reds"]
sce_color = ["dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# y_name = 'seepage_areas'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
# y_name = 'groundwater_storage'
xmin = []
xmax = []
ymin = []
ymax = []

fig1, axs1 = plt.subplots(1,1, figsize=(5,4))
xn = [] #1e-6
xx = 1e-2
yn = 1e-3
yx = 1e1
ax = axs1
# ax.set_aspect('equal', adjustable='box')

# fig2, ax2 = plt.subplots(1,1, figsize=(5,4))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
    # xn = [] #1e-6
    # xx = 1e-2
    # yn = 1e-3
    # yx = 1e1
    # ax = axs1
    # ax.set_title(watershed_name+' '+' + '.join(mod_list))
    # # ax.set_aspect('equal', adjustable='box')
    
    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            # if sce == 'RCP2.6':
            #     color = 'dodgerblue'
            # if sce == 'RCP8.5':
            #     color = 'red'
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            if sce == 'historic':
                Smod = select_period(Smod, 1960, 2005)
            else:
                Smod = select_period(Smod, 2020, 2099)
            
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
                        
            ax = axs1
            # ax.set_aspect('equal', adjustable='box')
            # ax.scatter(Qmod, Smod.seepage_areas, color='grey', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.surflow_areas, color='k', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.perenn_areas, color='dodgerblue', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.intermit_areas, color='darkorange', ec='none',
            #            s=30, alpha=0.5)
                        
            Z = Smod[y_name]
            from scipy.stats import norm
            pdf = norm.pdf(Z, Z.mean(), Z.std())
            # ax.scatter(Z, pdf, s=1, color=color)
            
            import seaborn as sns
            sns.distplot(Z, hist = False, kde = True, norm_hist = True,
                  kde_kws = {'shade': False, 'linewidth': 2},
                  color=color)
            
            # ax.hist(Z, bins = 100, density=True,
            #         color = color, edgecolor = 'none')
                        
            ax.grid(color='grey',alpha=0.2)
                
            plt.tight_layout()
            
            ax.set_xlabel(y_name)
            ax.set_ylabel('PDF')
            
            # ax.set_xscale('log')
            
            xmin.append(Z.min())
            xmax.append(Z.max())
            ymin.append(pdf.min())
            ymax.append(pdf.max())
                        
            # if xn == []:
            #     plt.setp(ax,
            #              xlim=(min(xmin),max(xmax)),
            #              ylim=(min(ymin),max(ymax)))
            # else:
            #     ax.set_xlim(xn,xx)
            #     ax.set_ylim(yn,yx)
            
    fig1.tight_layout()
    # fig1.savefig(figsim_folder+'relation_qall'+'.png', dpi=300, bbox_inches='tight')

#%% ---- NOTES

'''
############ METHOD 2 : TAKE RECHARGE SURFEX AFTER MODIFY _ALL_D FILE ############

# Method 1 is applied for the runoff

BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                          first_year = 1960, last_year = 2019,
                                          time_step = time_step, sim_state=sim_state)
Rech = BV.forcing.recharge
BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                      first_year = 1960, last_year=2019,
                                      time_step = time_step, sim_state=sim_state)
Runof = BV.forcing.runoff # m/month

norm_Rech = select_period(Rech_averag, 2021, 2022)
norm_Qobs = select_period(Qobs, 2021, 2022)

Rt_Rech_Qobs = (norm_Qobs.mean() / norm_Rech.mean())
print(Rt_Rech_Qobs.round(2))
Nt = (norm_Rech * Rt_Rech_Qobs)
BV.forcing.update_recharge(Nt, sim_state=sim_state)
plt.plot(BV.forcing.recharge, c='r')
plt.plot(Qobs, c='b')
plt.yscale('log')

BV.forcing.update_recharge(select_period(BV.forcing.recharge, 2021, 2022), sim_state=sim_state)

# Need to add 2021 and 2022 runoff SURFEX, in _ALL_D.csv or with the method behind
dates = pd.date_range(start='1/1/2021', end='31/12/2022', freq='D', closed=None)
Runof_averag = Runof.groupby([Runof.index.month, 
                              Runof.index.day], as_index=True).mean().reset_index().iloc[:,-1:].iloc[:-1]
Runof_averag = Runof_averag.append(Runof_averag, ignore_index=True)
Runof_averag.index = dates

BV.forcing.update_runoff(select_period(Runof_averag, 2021, 2022), sim_state=sim_state)
'''

