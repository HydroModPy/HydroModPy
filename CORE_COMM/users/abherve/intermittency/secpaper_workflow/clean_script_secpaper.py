# -*- coding: utf-8 -*-
"""
Created on Fri Mar  3 08:18:04 2023

@author: ronan
"""

#%% LIBRARIES

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
# import seaborn as sns
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
# import earthpy.spatial as es
# import earthpy.plot as ep
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
# wbt.verbose = True
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
               
# HYDROMODPY MODULES
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% FONCTIONS

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

#%% ---- CATCHMENT

#%% PATH

pc = 'local'

if pc == 'local':
    git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/"
    # Path where the results will be stored
    out_path = "D:/Users/abherve/SECPAPER/"
    # Figure folder outputs
    figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_vf/'
if pc == 'serv':
    git_path = "D:/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = "D:/abherve/HYDRODATAPY/"
    # Path where the results will be stored
    out_path = "D:/abherve/SECPAPERONELAY/"
    # Figure folder outputs
    figsim_folder = "D:/abherve/SECPAPERONELAY/Figures/"
    
dems_path = data_path + 'DEM/France/' # reginal DEM or conceptual DEM
shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = data_path + 'SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

# surfex_path =  data_path + 'CLIMATE/France/SURFEX/Brittany/'
surfex_path =  data_path + 'CLIMATE/France/SURFEX/Rennes/' # add surfex models in .h5 format (France scale, else, specify None)
drias_path = data_path + 'CLIMATE/France/DRIAS/Bretagne/'
geology_path = data_path + 'GEOLOGY/France/Layer/' # add geologic layers
oceanic_path = data_path + 'OCEANIC/' # add specific sea level files
hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles
hydrometry_path = data_path + 'HYDROLOGY/France/Hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'HYDROLOGY/France/Intermittency/' # add intermittency data for automatic download
piezometry_path = False # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

dem_name = "BDALTI_bzh_75m.tif" # name of dem
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

# Depending on the choices
dem_path = dems_path + dem_name
# import xugrid
# dem_reg = imageio.imread(dem_path)
# section_y = 1200
# section = dem_reg.ugrid.sel(y=section_y)

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

froms_xy = [[327816.965, 6777886.670, 150, 10],
            [389285.910, 6816518.749, 150, 10]] # 389441.944, 6816812.768 Nancon small

#%% GENERATE

load = True

for watershed_name, from_xy in zip(watershed_names, froms_xy):

    print('##### '+watershed_name.upper()+' #####')

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  modflow_path=modflow_path,
                                  library_path=library_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xy=from_xy,
                                  cell_size=cell_size)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
  
#%% DATA

for watershed_name in watershed_names[:]:
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    BV.add_oceanic(oceanic_path)
    BV.add_hydrometry(hydrometry_path)
    BV.add_intermittency(intermittency_path)
    if not os.path.exists(stable_folder+'climatic/REA.H5'):
        BV.add_surfex(surfex_path)
        # BV.add_drias(drias_path)
    BV.add_geology(geology_path)
    if watershed_name == 'Canut':
        types_obs = ['zh_meuchezecanut','complete','river','perennial'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid','fid','fid']
    if watershed_name == 'Nancon':
        types_obs = ['zh_couesnon','complete','river','perennial'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid','fid','fid']
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    try:
        BV.add_piezometry()
    except:
        pass
    BV.add_subbasin()
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
    
#%% ---- RECHARGE

#%% NORMALIZE

recharge = pd.DataFrame()
runoff = pd.DataFrame()

compt=1
for watershed_name in watershed_names[:] :
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    BV.add_forcing()

    BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2020,
                                  time_step = 'M',
                                  sim_state='transient') #
    BV.forcing.update_runoff_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2020,
                                  time_step = 'M',
                                  sim_state='transient') #
    
    recharge[str(compt)]=BV.forcing.recharge
    runoff[str(compt)]=BV.forcing.runoff
    
    compt+=1

recharge = recharge.mean(axis=1)
recharge = recharge.rename('REA_historic')
runoff = runoff.mean(axis=1)
runoff = runoff.rename('REA_historic')

fig = plt.subplots(1,1, figsize=(6,3))

dict_recharge = dict(zip(watershed_names, np.empty((2,1))))
dict_runoff = dict(zip(watershed_names, np.empty((2,1))))

for watershed_name in watershed_names[:] :
    
    print(watershed_name)
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    BV.add_forcing()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots

    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    area = BV.geographic.area
    area = int(round(area))
    print(area)
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    Qobs = Qobs.resample('M').mean() # m/day in monthly
    tmin_Q = Qobs.first_valid_index().year+1
    tmax_Q = Qobs.last_valid_index().year-1
    
    # BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
    #                               first_year = 1960, last_year=2020,
    #                               time_step = 'M',
    #                               sim_state='transient') #
    # BV.forcing.update_runoff_surfex(clim_mod = 'REA', clim_sce='historic',
    #                               first_year = 1960, last_year=2020,
    #                               time_step = 'M',
    #                               sim_state='transient') #
    # Rraw = BV.forcing.recharge
    # rraw = BV.forcing.runoff
    
    Rraw = recharge.copy()
    rraw = runoff.copy()
    tmin_R = Rraw.first_valid_index().year+1
    tmax_R = Rraw.last_valid_index().year-1
    
    year_min = max(tmin_Q, tmin_R)
    year_max = min(tmax_Q, tmax_R)
    
    Qobs_sel = select_period(Qobs, year_min, year_max)
    # print(Qobs_sel.mean() * 365 * 1000)

    R_sel = select_period(Rraw, year_min, year_max)
    r_sel = select_period(rraw, year_min, year_max)
    
    Fnorm = Qobs_sel.mean() / (R_sel.mean() + r_sel.mean())
    print(Fnorm)
    
    R_norm = R_sel * Fnorm
    r_norm = r_sel * Fnorm
    
    # fig = plt.subplots(1,1, figsize=(6,3))
    plt.plot(R_norm+r_norm)
    # plt.plot(r_norm)
    plt.yscale('log')
    
    R_norm = select_period(R_norm, 1990, 2019)
    r_norm = select_period(r_norm, 1990, 2019)
    
    dict_recharge[watershed_name] = R_norm
    dict_runoff[watershed_name] = r_norm
    
    print((R_norm).mean() * 365 * 1000)
    
#%% ---- CALIB
    
#%% DICHOTOMY STREAMS

for watershed_name in watershed_names :
    
    if watershed_name == 'Canut':
        types_obs = ['complete','perennial'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid']
    if watershed_name == 'Nancon':
        types_obs = ['complete','perennial'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid']
        
    df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
    
    for type_obs, field_obs in zip(types_obs, fields_obs):
   
        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
        BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])

        BV.add_forcing()
        BV.forcing.update_recharge(dict_recharge[watershed_name], sim_state='steady')
        
        BV.add_hydrodynamic()
        BV.hydrodynamic.update_nlay(6)
        BV.hydrodynamic.update_thickness(30)
        BV.hydrodynamic.update_bottom(None)
        BV.hydrodynamic.update_cond_decay(0)
        BV.hydrodynamic.update_thick_exp(1)
        
        params_df = pd.DataFrame(columns=['params',
                                          'init_values','lower_bounds','higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+01,'m/j','lin']
        params_file = 'calib_dicot_hom_1v_k1_'+type_obs
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
        calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
        
        # dicot = calib.dichotomy(gap=1)

        typ_calib = 'streams_calibration'
        list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                            key=os.path.getmtime)
        name_file = list_path[-1].split('\\')[-1]
        calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
        test = calib_analysis.CalibAnalysis(calib_file)
        test.display_objective_function(save=None)
        
        koptim = test.calib['params_values'][-1]
        kr = koptim / test.calib['recharge']
        obj_func = test.calib['objective_function'][-1]
                
        df.loc[0,type_obs] = koptim / 24 / 3600
        df.loc[1,type_obs] = kr
        df.loc[2,type_obs] = obj_func
        
    df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

#%% EXPLORATION DISCHARGE

modflow_path = data_path + 'SOFTWARE/MODFLOW/'

for watershed_name in watershed_names[:1] :
    print('##### '+watershed_name.upper()+' #####')
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots    
    BV.add_forcing()
    BV.add_hydrodynamic()

    BV.forcing.update_recharge(dict_recharge[watershed_name], sim_state='transient')
    BV.forcing.update_runoff(dict_runoff[watershed_name], sim_state='transient')
    
    nlay = 1
    bottom = None
    cond_decay = 0
    thick_exp = 1
    thickness = 30
        
    BV.hydrodynamic.update_nlay(nlay) # 1
    BV.hydrodynamic.update_bottom(bottom) # None
    BV.hydrodynamic.update_cond_decay(cond_decay) # 0
    BV.hydrodynamic.update_thick_exp(thick_exp) # 1
    BV.hydrodynamic.update_thickness(thickness) # 30 / intervient pas si bottom != None

    params_df = pd.DataFrame(columns=['params',
                                      'init_values','lower_bounds','higher_bounds',
                                      'units','scale'])
    if watershed_name == 'Canut':
        params_df.loc[0] = ['k1', 0, 1e-8*86400, 1e-2*86400, 'm/j', 'lin']
        params_df.loc[1] = ['n1', 0, 0.1/100, 10/100, 'm/j', 'lin']
    if watershed_name == 'Nancon':
        params_df.loc[0] = ['k1', 0, 1e-8*86400, 1e-2*86400, 'm/j', 'lin']
        params_df.loc[1] = ['n1', 0, 0.1/100, 10/100, 'm/j', 'lin']
        
    params_file = 'calib_explo_hom_2v_k1-n1'
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
    
    calib = calib_root.Calibration(params_file, BV, observations = ['hydrometry'])
    calib.exploration(resolution=1)
    
#%% ---- MODEL
    
#%% MODELING TEST

iD = 'test'

# Options
sim_state = 'transient' # 'steady' or 'transient'
modpath_sim = False # run modpath particle tracking if True
run = True
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process    
init_rech = 'mean'

compt = 0

for watershed_name in watershed_names[:1]:
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    BV.add_forcing()
    BV.add_hydrodynamic()
    BV.add_oceanic('None')
    
    # Recharge and runoff
    mod = 'REA'
    sce = 'historic'
    recharge = dict_recharge[watershed_name]
    runoff = dict_runoff[watershed_name]
    BV.forcing.update_recharge(recharge, sim_state='transient')
    BV.forcing.update_runoff(runoff, sim_state='transient')
    
    # Store results
    list_model_name = []
    list_of_success = []
    list_flow_model = []

    nlay = 6
    bottom = None
    cond_decay = 0
    thick_exp = 1
    thickness = 30
    hyd_cond = [5e-5 * 86400]
    porosity = [1 / 100]
    
    for K, Sy in zip(hyd_cond, porosity):
    
        BV.hydrodynamic.update_nlay(nlay) # 1
        BV.hydrodynamic.update_bottom(bottom) # None
        BV.hydrodynamic.update_cond_decay(cond_decay) # 0
        BV.hydrodynamic.update_thick_exp(thick_exp) # 1
        BV.hydrodynamic.update_thickness(thickness) # 30 / intervient pas si bottom != None
        BV.hydrodynamic.update_hyd_cond(K) 
        BV.hydrodynamic.update_porosity(Sy)
          
        date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
        date_today = date_today.replace('/','-')
        date_today = date_today.replace(':','-')
        date_today = date_today.replace(' ','_')
        
        model_name = iD+'_'+str(compt)+'_'+\
                     mod+'-'+sce+'_'+\
                     str(nlay)+'-'+str(thickness)+'_'+\
                     str(K)+'-'+str(Sy)+'_'+\
                     str(recharge.first_valid_index().year)+'-'+str(recharge.last_valid_index().year)
        
        print(model_name)
    
        success, flow_model = BV.run_modflow(ident=model_name,
                                             modpath_sim=modpath_sim,
                                             sink_fill=sink_fill,
                                             box=box,
                                             verbose=verbose,
                                             post_process=post_process, 
                                             init_rech=init_rech,
                                             verti_k=None)
        if success == True:
            print(     'Success')
        else:
            print(     'Error')

        list_model_name.append(model_name)
        list_of_success.append(success)
        list_flow_model.append(flow_model)
    
        # compt+=1
        
    print(list_of_success)
    
    dictio = {}
    dictio['list_model_name'] = list_model_name
    dictio['list_of_success'] = list_of_success
    dictio['list_flow_model'] = list_flow_model
    h5file = simulations_folder+'/'+'list_'+iD
    
    dd.io.save(h5file, dictio)

#%% PP

iD = 'test'

for watershed_name in watershed_names[:1] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    h5file = simulations_folder+'/'+'list_'+iD
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_of_success = d['list_of_success'][:]
    list_flow_model = d['list_flow_model'][:]
    
    for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
            
        if success==True:
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
                                  residence_times = False,
                                  verbose = True,
                                  export_tif = True)
                
                # # Extract results
                BV.results_modflow(ident=model_name,
                                   recharge=dict_recharge[watershed_name],
                                   runoff=dict_runoff[watershed_name],
                                   actual_date=True,
                                   time_step='M')
                
#%% MODELING CALIBRATED

#%% PP

#%% MODELING SENSITIVITY

#%% PP

#%% ---- PLOT

#%% MATRIX DISCHARGE

sat_typ = 'seepage_areas'

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

for watershed_name in watershed_names[:1]:
    
    print('##### '+watershed_name.upper()+' #####')

    min_nse = 50
    mean_meansat = 3 # sup
    min_maxsat = 8
    max_maxsat = 25
    
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
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    sim_res=test.sim_results
    print(sim_res)
    
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
        sat = pd.to_numeric(sat)
        
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_maxsat:
                if sat.max() > min_maxsat:
                    numb += 1
                # c = []
                # for h in range(len(ind[typ_name])):
                #     d = ind[typ_name][h][0]
                #     c.append(d)
        
        c = np.linspace(0,1,len(obs[typ_name]))

        # cmap = mpl.cm.get_cmap('viridis_r')
        # color_gradients = cmap(c)
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
    pc = ax.contourf(X/3600/24, Y*100, Z, levels=np.arange(0,1.1,0.1), alpha=0.5, ec='none')    
    
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='5%', pad=0.05)
    
    
    # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    # cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,1.1,0.2))
    # cb.set_ticklabels(np.arange(0,101,20)) 
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # cb.ax.tick_params(top=True,
    #             bottom=True,
    #             left=False,
    #             right=False,
    #             labelleft=False,
    #             labelbottom=True)
    
    
    ax.set_xscale('log')
    ax.set_ylabel('θ [%]')
    ax.set_xlabel('K [m/s]')
    # ax.set_yticks(np.arange(0,11,2))
    # ax.set_yticklabels(np.arange(0,11,2))
    # ax.tick_params(direction='in')
    ax.tick_params(top=True,
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
    
    '''
    ax.scatter(Xclip, Yclip, c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    '''
    
    # pc = ax.pcolormesh(X/3600/24, Y*100, Z,
    #                  cmap = mpl.colors.ListedColormap('Grey'),
    #                  alpha=0.5, linewidths=1)
    # pc = ax.contour(X/3600/24, Y*100, Z, levels=np.arange(0,100,5),
    #                  cmap =  mpl.colors.ListedColormap('Grey'),
    #                  alpha=0.75, linewidths=1)
    
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
    
    ax.axvline(df.perennial[0], color='k', lw=2, ls='--')
    ax.axvline(df.river[0], color='k', lw=2, ls='--')
    ax.axvline(df.complete[0], color='k', lw=2, ls='--')
    try:
        ax.axvline(df.zh_couesnon[0], color='k', lw=2, ls='--')
    except:
        ax.axvline(df.zh_meuchezecanut[0], color='k', lw=2, ls='--')
        pass
    
    # ax.set_ylim(0.1,10)
    # ax.set_yticks(np.arange(0.1,11,2))
    # ax.set_yticklabels(np.arange(0,10,2))
    
    ax.set_title(watershed_name, pad=10)
    plt.tight_layout()
    
    # fig.savefig(figsim_folder+watershed_name+'_calib2D_map'+'.png', dpi=300, bbox_inches='tight')
    # fig.savefig(fig_path + 'Qmap_NSElog_' +
    #             watershed_name + '.png', dpi=300, bbox_inches='tight')

    base_name = figsim_folder+'fig03/'
    spec_name = watershed_name+'_explodischarge'
    # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')


#%% MATRIX SATURATION

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'seepage_areas'

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
    
    min_nse = 60
    min_maxsat = 3
    max_maxsat = 25
    
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
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    
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

    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_title(watershed_name, pad=10)
    
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z = np.empty((3,3,))
    Z[:] = np.nan
    p1 = test.params_values[0]
    p2= test.params_values[1]
    sim_sat_min = np.zeros((len(p1),len(p2)))
    sim_sat_mean = np.zeros((len(p1),len(p2)))
    sim_sat_max = np.zeros((len(p1),len(p2)))
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                # ax.set_title('SAT MIN [%]')
                sim_sat_min[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
            except:
                pass
            try:
                # ax.set_title('SAT MEAN [%]')
                sim_sat_mean[j][i] = pd.to_numeric(sim_res[string][sat_typ]).median()
            except:
                pass
            try:
                # ax.set_title('SAT MAX [%]')
                sim_sat_max[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
            except:
                pass
            compt += 1
    
    # sim_sat_min[sim_sat_min==0] = 1/1e6
    # sim_sat_max[sim_sat_max==0] = 1/100
    Z = (sim_sat_max/sim_sat_min)
    # Z = np.log10(Z)
    
    # Z[sim_sat_max==0] = 0
    # Z[sim_sat_min==0] = 0
    # Z[sim_sat_max==0] = 0
    # from numpy import inf
    Z[Z == np.inf] = 100
    # Z[Z == 0] = 0.1
    Z[Z>100] = 100
    print(np.nanmin(Z), np.nanmax(Z))
    # Z[Z == np.nan] = np.inf
    # pc = ax.contour(X/24/3600,Y*100,Z, cmap='jet', alpha=1, lw=2,
    #                  levels=np.arange(0,101,10)) #figadd.cmap_white_jet()    
    
    # pc = ax.pcolormesh(X/24/3600,Y*100,Z, cmap='jet', alpha=0.6,
    #                     # levels=np.arange(0,101,10),
    #                     norm=mpl.colors.LogNorm(vmin=1, vmax=101),
    #                   linewidths=2, shading='auto') #figadd.cmap_white_jet()     levels=np.arange(0,101,10)
    
    # pc = plt.pcolormesh(X/24/3600,Y*100,Z, cmap='jet', alpha=0.6) #figadd.cmap_white_jet()     levels=np.arange(0,101,10)
    # plt.xscale('log')
    # Z[(sim_sat_max==0)&(sim_sat_min==0)] = np.nan
    # pcinf = ax.pcolormesh(X/24/3600,
    #                       Y*100,
    #                       (Z==np.inf), cmap=mpl.colors.ListedColormap('grey'), alpha=0.6,
    #                     # levels=np.arange(0,101,10),
    #                     norm=mpl.colors.LogNorm(vmin=1, vmax=101),
    #                   linewidths=2) #figadd.cmap_white_jet()     levels=np.arange(0,101,10)    
    pc = plt.contourf(X/24/3600,Y*100,Z, cmap='jet', alpha=0.5,
                        levels=np.around(np.geomspace(1, 100, 10)).astype(int),
                        norm=mpl.colors.LogNorm(),
                      linewidths=2)
    
    Z2 = (sim_sat_mean)
    # pc2 = ax.contourf(X/24/3600,Y*100,Z2, cmap=mpl.colors.ListedColormap('white'), 
    #                   alpha=0.25, linewidths=0,
    #                   levels=np.linspace(0.5,10,2),
    #                   ) #figadd.cmap_white_jet()
    pc2 = ax.contourf(X/24/3600,Y*100,Z2, cmap=mpl.colors.ListedColormap('grey'), 
                      alpha=0.25, linewidths=0,
                      levels=np.linspace(0,0.5,2),
                      ) #figadd.cmap_white_jet()
    pc2 = ax.contourf(X/24/3600,Y*100,Z2, cmap=mpl.colors.ListedColormap('grey'), 
                      alpha=0.25, linewidths=0,
                      levels=np.linspace(10,100,2),
                      ) #figadd.cmap_white_jet()   
    pc2 = ax.contour(X/24/3600,Y*100,Z2, cmap=mpl.colors.ListedColormap('k'), alpha=1, linewidths=2,
                      levels=np.linspace(0.5,10,2)
                      ) #figadd.cmap_white_jet()    
    # ax.contourf(X/24/3600,Y*100, Z2/4, cmap='jet', alpha=0.5,
    #                    norm=mpl.colors.LogNorm(vmin=0.1, vmax=101),
    #                   linewidths=2) #♠mpl.colors.ListedColormap('k')
    # pc = ax.contourf(X/24/3600,Y*100,Z, cmap='jet', alpha=0.6,
    #                   levels=np.arange(0,100,0.5)) #figadd.cmap_white_jet()     levels=np.arange(0,101,10)
    # pc = plt.pcolormesh(X/24/3600,Y*100,Z, cmap='jet', alpha=0.6) #figadd.cmap_white_jet()     levels=np.arange(0,101,10)
    plt.xscale('log')
    
    ax.set_xscale('log')
    ax.set_ylabel('θ [%]')
    ax.set_xlabel('K [m/s]')
    
    # Z = sim_sat_mean.copy()
    # Z[Z<1] = np.nan
    # Z[Z>10] = np.nan
    
    '''
    ax.scatter(X/24/3600,Y*100,c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    '''
        
    position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    norm = mpl.colors.LogNorm(vmin=1, vmax=100)
    bounds = np.arange(1,200,5)
    fig.colorbar(pc, ax=ax, norm=mpl.cm.ScalarMappable(norm=norm), cax=position,
                 boundaries=bounds)
    
    # pc = ax.pcolormesh(X/3600/24, Y*100, Z,
    #                   cmap = mpl.colors.ListedColormap('white'),
    #                   alpha=0.5, linewidths=10)
    
    # pc = ax.contourf(X/3600/24, Y*100, Z, cmap=None,
    #                   levels=np.arange(0,100,5), alpha=0.75, linewidths=5,
    #                   colors='k',interpolation='none') # mpl.colors.ListedColormap('Grey')
    
    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    # ax.axvline(df.perennial[0], color='k', lw=2)
    # ax.axvline(df.complete[0], color='k', lw=2, ls='--')
    
    # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    # cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,101,20)) 
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # cb.ax.tick_params(top=True,
    #             bottom=True,
    #             left=False,
    #             right=False,
    #             labelleft=False,
    #             labelbottom=True)
    
    ax.set_xlim(1e-8, 1e-2)
    ax.set_ylim(0.1,10)
    
    plt.tight_layout()    
    
    base_name = figsim_folder+'fig03/'
    spec_name = watershed_name+'_explosaturation'
    # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% STREAMFLOW

iD = 'test'

for watershed_name in watershed_names[:1]:
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    BV.add_forcing()
    BV.forcing.update_recharge(dict_recharge[watershed_name], sim_state='transient')
    BV.forcing.update_runoff(dict_runoff[watershed_name], sim_state='transient')
    # BV.add_intermittency(intermittency_path)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = int(round(BV.geographic.area))
    Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
    Qobs = Qobs.squeeze()
    Qobs = select_period(Qobs, 1990, 2019)
    Qobs = Qobs.resample('M').mean()
    
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'), key=os.path.getmtime)
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]

        Smod_path = simul+'/_watershed/_simulated_results.csv'
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        
        Rmod = Smod['recharge'] * 1000 * 30
        
        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(3,3))
        ax.scatter(select_period(Qobs,1990,2019),select_period(Qmod,1990,2019),
                   s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
        if watershed_name == 'Canut':
            ax.set_xlim(0.1,200)
            ax.set_ylim(0.1,200)
        if watershed_name == 'Nancon':
            ax.set_xlim(5,200)
            ax.set_ylim(5,200)
        # ax.set_xlim(0.1,300)
        # ax.set_ylim(0.1,300)    
        ax.set_xlabel('$Q_{obs}$ / A [mm/month]')
        ax.set_ylabel('$Q_{sim}$ / A [mm/month]')
        
        # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(7,3))
        yearsmaj = mdates.YearLocator(5)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
    
        ax.set_ylabel('Q / A [mm/month]')
        axb = ax.twinx()
        axb.set_ylabel('R [mm/month]', rotation=270, labelpad=25)
        axb.bar(Rmod.index, Rmod,
                color='blue', edgecolor='blue', lw=2.5)
        axb.set_ylim(0,999)
        axb.invert_yaxis()
        axb.set_yticklabels([0,200])
        # axb.xaxis.set_major_formatter_locator(yearsmaj)
        # axb.xaxis.set_minor_locator(yearsmin)
        # axb.xaxis.set_major_formatter(years_fmt)
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='observed')
        # ax.set_yscale('log')
        ax.plot(Qmod, color='red', lw=2, label='modeled')
        ax.set_ylim(0.11,200)
        # ax.grid('grey')
        # ax.set_title('Discharge')
        # ax.set_xlim(pd.to_datetime('1986'))
        ax.set_xlim(pd.to_datetime('1990'), pd.to_datetime('2020'))
 
        import hydroeval as he
        nse = he.evaluator(he.nse, select_period(Qmod,1990,2019), Qobs, transform='log')[0]
        print(round(nse,2))

#%% ONDE

iD = 'test'

for watershed_name in watershed_names[:1]:
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    BV.add_forcing()
    BV.forcing.update_recharge(dict_recharge[watershed_name], sim_state='transient')
    BV.forcing.update_runoff(dict_runoff[watershed_name], sim_state='transient')
    # BV.add_intermittency(intermittency_path)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = int(round(BV.geographic.area))
    Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
    Qobs = Qobs.squeeze()
    Qobs = select_period(Qobs, 1990, 2019)
    Qobs = Qobs.resample('M').mean()
    
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'), key=os.path.getmtime)
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]

        Smod_path = simul+'/_watershed/_simulated_results.csv'
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        
        Rmod = Smod['recharge'] * 1000 * 30
        
        Sonde_path = glob.glob(simul+'/_subbasins/intermittency_*')[0]+'/_simulated_results.csv'
        Sonde = pd.read_csv(Sonde_path, sep=';', index_col=0, parse_dates=True)
        
        d = BV.intermittency.flowing
        assec = d[d==1].dropna()
        invi = d[d==2].dropna()
        low = d[d==3].dropna()
        accep = d[d==4].dropna()
        visib = d[d==5].dropna()
        
        fig, ax = plt.subplots(1,1, figsize=(6,3))

        lw = 4
        for u in range(len(assec)):
            ax.axvline(assec.index[u], color='salmon', linewidth = lw, alpha=1, zorder=-10) # assec
        for u in range(len(invi)):
            ax.axvline(invi.index[u], color='gold', linewidth = lw, alpha=1, zorder=-10) # pond
        for u in range(len(low)):
            ax.axvline(low.index[u], color='lightskyblue', linewidth = lw, alpha=1, zorder=-10) # bio mal
        for u in range(len(accep)):
            ax.axvline(accep.index[u], color='lightskyblue', linewidth = lw, alpha=1, zorder=-10) # bio ok
        for u in range(len(visib)):
            ax.axvline(visib.index[u], color='lightskyblue', linewidth = lw, alpha=1, zorder=-10) # ecoul
        
        # seep = Sonde['seepage_areas']
        # seep = seep.fillna(0)
        # ax.plot(seep, color='k', ls=(0, (1, 1)), lw=1.5, label='upstream')
        # tp = Sonde['surflow_areas']
        # tp = tp.fillna(0)
        # ax.plot(tp, color='k', lw=1.5, label='upstream')
        
        ax.plot(Smod['surflow_areas'], color='navy', ls='-', lw=2.5, label='catchment')
        ax.fill_between(Smod.index, Smod['perenn_areas'], Smod['surflow_areas'],
                        interpolate=False, color='lightgrey', alpha=1)
        ax.plot(Smod['perenn_areas'], color='navy',
                marker=None, markeredgecolor='none',
                markersize=5, lw=0, label='upstream')
        ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                        interpolate=False, color='grey', alpha=1)
        
        ax.grid('grey', axis='x')
        ax.set_ylim(0,20)
        ax.set_ylabel('$A_{sat}$ [%]')
        ax.set_xlim(pd.to_datetime('2012'), pd.to_datetime('2020'))

        months_maj = MonthLocator()  # every x month
        ax.xaxis.set_minor_locator(months_maj)
        
        plt.tight_layout()
                
#%% MMINMAP

iD = 'test'

mod = 'REA'

time_step = 'M'
sim_state = 'transient'

# watershed_names = ['Canut']

types_obs = ['complete'] # list of shapefile name layers for clip hydrology
for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    
    # BV.add_intermittency(intermittency_path)

    BV.add_forcing()
    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'),
                       key=os.path.getmtime)
         
    for simul in simul_list[-1:]:
        model_name = simul.split('\\')[-1]
        Smod_path = simul+'/_watershed/_simulated_results.csv'
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
        min_area = Smod['surflow_areas'].min()
        min_idx = np.argmin(Smod['surflow_areas'])
        max_area = Smod['surflow_areas'].max()
        max_idx = np.argmax(Smod['surflow_areas'])
        max_year = Smod['surflow_areas'].index[max_idx]
        
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
        
        for k, j in enumerate([min_idx, max_idx]):
                
                year = Smod['surflow_areas'].index[j]
                val = Smod.iloc[j]['surflow_areas']

                days_flux = acc_npy[j]
    
                fig, ax = plt.subplots(1,1, figsize=(7,6))
                ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
                             pad=10)
                # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                ax.imshow(np.ma.masked_where((days_flux<=0) | (mask <0),
                                             days_flux), 
                          cmap = mpl.colors.ListedColormap(['navy'])) # dodgerblue
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                plt.axis('off')
        
                # ax.set_title(years[i])
                
                try:
                    path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                    wbt.vector_lines_to_raster(path_sub,
                                               glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                                               base = stable_folder+'geographic/'+'watershed_dem.tif')
                    line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                    line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                    # ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('gold'))
                except:
                    pass

#%% CROSSANIM

iD = 'test'

watershed_names = ['Canut','Nancon']

dates = pd.date_range(start='01/01/1990', end='31/12/2019', freq='M')

for watershed_name in watershed_names[:1]:    

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

    for key in dict(itertools.islice(watertable_elevation.items(),
                                     len(watertable_elevation)-12*8, # ONDE 8 years
                                     len(watertable_elevation))):
        print(key)

        dem_data = imageio.imread(BV.geographic.watershed_dem)
        # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
        wt_data = watertable_elevation[key]
        river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
    
        xvalues = np.linspace(-1,1,dem_data.shape[1])
        yvalues = np.linspace(-1,1,dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues,yvalues)
        
        cur_x = dem_data.shape[1] /2
        cur_y = dem_data.shape[0] /2
        
        cur_x = 65
        cur_y = 40
        
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        
        if watershed_name == 'Nancon':
            dem_h_plot = dem_prof[int(cur_y),:]
            dem_h_plot[dem_h_plot == 0] = np.nan
            wt_h_plot = wt_prof[int(cur_y),:]
            wt_h_plot[wt_h_plot == 0] = np.nan
        if watershed_name == 'Canut':
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
                        
        fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)
    
        if watershed_name == 'Nancon':
            # dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
            # wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, 0, wt_h_plot,
                                            color='dodgerblue', alpha=0.5, lw=0)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                            color='saddlebrown', alpha=0.5, lw=0)
            ax.set_xlim(4000, 7000)
            ax.set_ylim(130, 170)
            ax.set_yticks([140,160])
            
            d_prof = ax.plot(np.arange(xx.shape[1])*75, dem_h_plot, 'saddlebrown', lw=2)
            w_prof = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, color='navy', lw=2)
            
        if watershed_name == 'Canut':
            # dem_v_prof, = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, c='saddlebrown', lw=2)
            # wt_v_prof, = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, c='dodgerblue', lw=2)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 0, wt_v_plot,
                                                color='dodgerblue', alpha=0.5, lw=0)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
            ax.set_xlim(1000, 4000)
            ax.set_ylim(90, 130)
            ax.set_yticks([100,120])
            
            d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=2)
            w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=2)
            
        ax.set_title(str(dates[key])[:7])
        
        plt.tight_layout()
        
        # fig.savefig(simulations_folder+model_name+'/_figures/png/'+'cross_'+str(key)+'.png', dpi=300, bbox_inches='tight')

        plt.close()

for watershed_name in watershed_names[:1]:    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    list_path = sorted(glob.glob(simulations_folder+iD+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]
    begin_by = simulations_folder+model_name+'/_figures/png/'+'cross_'
    filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    base_name = figsim_folder+'fig11/'
    spec_name = watershed_name+'_cross_intermittent_monthly'
    # imageio.mimsave(base_name+spec_name+'.gif', images,
    #                 duration=0.25, loop=0)

#%% MAPANIM

iD = 'test'

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

    years = np.arange(1990,2019+1,1)
        
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
                if i >= 22:
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
                        
                        ax.set_title(str(years[i])+'-'+(str(k+1)))
                        
                        path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                        wbt.vector_lines_to_raster(path_sub,
                                                   glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                                                   base = stable_folder+'geographic/'+'watershed_dem.tif')
                        line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                        line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                        # ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('k'))
                        
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        
                        # if watershed_name=='Canut':
                        #     ax.axvline(x=65, color='k', lw=1, ls='--')
                        # if watershed_name=='Nancon':
                        #     ax.axhline(y=40, color='k', lw=1, ls='--')
                        
                        # fig.savefig(simul+'/_figures/png/'+'_map_intermittent_monthly_'+str(compt)+'.png', dpi=300, bbox_inches='tight')
                        
                        plt.axis('off')
                        plt.close()
                        
                        compt += 1
                        
                    inf+=12
                    sup+=12

    if gif == True:
        begin_by = simul+'/_figures/png/'+'_map_intermittent_monthly'
        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
        images = []
        for filename in filenames:
            images.append(imageio.imread(filename))
        base_name = figsim_folder+'fig11/'
        spec_name = watershed_name+'_map_intermittent_monthly'
        # imageio.mimsave(base_name+spec_name+'.gif', images,
        #                 duration=0.25, loop=0)

#%% CROSSFIX

iD = 'test'

watershed_names = ['Canut','Nancon']

dates = pd.date_range(start='01/01/1990', end='31/12/2019', freq='M')

for watershed_name in watershed_names[:1]:    
    
    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

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
    
    Smod_path = simul+'/_watershed/_simulated_results.csv'
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    Smod = Smod.reset_index()
    argmin = Smod['surflow_areas'].argmin()
    argmax = Smod['surflow_areas'].argmax()
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    
    import itertools            
    
    watertable_elevation = np.load(simulations_folder+model_name+'/_watershed/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
    
    min_wt = dict()
    
    cp = 0
    # for key in dict(itertools.islice(watertable_elevation.items(),
    #                                  len(watertable_elevation), # ONDE 8 years
    #                                  len(watertable_elevation))):
    for i, key in enumerate([argmin, argmax]):
        print(key)

        dem_data = imageio.imread(BV.geographic.watershed_dem)
        # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
        wt_data = watertable_elevation[key]
        river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
    
        xvalues = np.linspace(-1,1,dem_data.shape[1])
        yvalues = np.linspace(-1,1,dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues,yvalues)
        
        cur_x = dem_data.shape[1] /2
        cur_y = dem_data.shape[0] /2
        
        cur_x = 65
        cur_y = 40
        
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        
        if watershed_name == 'Nancon':
            dem_h_plot = dem_prof[int(cur_y),:]
            dem_h_plot[dem_h_plot == 0] = np.nan
            wt_h_plot = wt_prof[int(cur_y),:]
            wt_h_plot[wt_h_plot == 0] = np.nan
            
            # list_h_wt[cp] = wt_h_plot
            
        if watershed_name == 'Canut':
            dem_v_plot = dem_prof[:,int(cur_x)]
            dem_v_plot[dem_v_plot == 0] = np.nan
            wt_v_plot = wt_prof[:,int(cur_x)]
            wt_v_plot[wt_v_plot == 0] = np.nan
            
            # list_v_wt[cp] = wt_v_plot
            
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
        
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        
        cp+=1
            
        if watershed_name == 'Nancon':
            # dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
            # wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
            if i == 0:
                wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, 0, wt_h_plot,
                                                color='dodgerblue', alpha=0.5, lw=0)
                w_prof = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, color='navy', lw=2)
            if i == 1:
                wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, 0, wt_h_plot,
                                                color='dodgerblue', alpha=0.5, lw=0)
                w_prof = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, color='dodgerblue', lw=2)
                wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
                d_prof = ax.plot(np.arange(xx.shape[1])*75, dem_h_plot, 'saddlebrown', lw=2)
            ax.set_xlim(4000, 7000)
            ax.set_ylim(130, 170)
            ax.set_yticks([140,160])
                   
        if watershed_name == 'Canut':
            # dem_v_prof, = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, c='saddlebrown', lw=2)
            # wt_v_prof, = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, c='dodgerblue', lw=2)
            if i == 0:
                wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 0, wt_v_plot,
                                                    color='dodgerblue', alpha=0.5, lw=0)
                w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=2)
            if i == 1:
                wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 0, wt_v_plot,
                                                    color='dodgerblue', alpha=0.5, lw=0)
                w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='dodgerblue', lw=2)
                wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
                d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=2)
            ax.set_xlim(1000, 4000)
            ax.set_ylim(90, 130)
            ax.set_yticks([100,120])
            
        ax.set_title(str(dates[key])[:7])
        
        plt.tight_layout()
        
        # fig.savefig(simulations_folder+model_name+'/_figures/png/'+'cross_'+str(key)+'.png', dpi=300, bbox_inches='tight')

#%% PI

iD = 'test'

var = 'REC'
sce_list = ['historic']

y_name = 'surflow_areas'

for watershed_name in watershed_names[:1]:

    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'    

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

    for ix in np.arange(0,1,1):
        
        fig, ax = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)

        simul = glob.glob(simulations_folder+'*'+iD+'_'+str(ix)+'*')[0]
        model_name = simul.split('\\')[-1]
        
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        acc_npy = list(acc_npy.items())[:]
        
        for key in range(len(acc_npy)):
            mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
            acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
        zero = acc_npy[0] * 0
        for i in range(len(acc_npy)):
            tempo = acc_npy[i].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy() / len(acc_npy)
                
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
        
        pi = np.ma.masked_where(days_flux <= 0, days_flux)
        pc = ax.imshow(pi,
                       cmap=cmap, norm=norm, alpha=1)
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
        plt.subplots_adjust(hspace = -0.6)
        
        '''        
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
        '''
     
        days_flux = np.ma.masked_where(days_flux == 0, days_flux)
    
        count_inf = np.ma.masked_where(days_flux > 0.1, days_flux).count()
        count_sup = np.ma.masked_where(days_flux < 0.9, days_flux).count()
        
        total = np.ma.masked_where(days_flux == 0, days_flux).count()
    
        print(watershed_name, (count_inf / total)*100, (count_sup / total)*100)
      
        position=fig.add_axes([0.93,0.35,0.01,0.30])  ## the parameters are the specified position you set 
        cb = fig.colorbar(pc,cax=position, orientation="vertical")
        position.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)
        cb.ax.tick_params(axis='y', direction='out')
        
        # fig1.savefig(figsim_folder+watershed_name+'_persistency_map_historic'+'.png', dpi=300, bbox_inches='tight')
    
        base_name = figsim_folder+'fig06/'
        spec_name = watershed_name+'_persistency'
        # fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 
        
        pi_path = os.path.join(simul, '_watershed', 'persistency_index.tif')
        toolbox.export_tif(BV.geographic.watershed_dem, pi, -99999, pi_path)

        pi_shp_path = os.path.join(simul, '_watershed', 'persistency_index.shp')
        wbt.raster_to_vector_points(pi_path, pi_shp_path)
        pi_shp = gpd.read_file(pi_shp_path)
        pi_shp['VALUE'][pi_shp['VALUE']>1] = 1
        pi_shp.to_file(pi_shp_path)
    
#%% HYSTERESIS


#%% ANNEXES


#%% NOTES

plt.plot(test.data_obs['hydrometry'][0])
plt.plot(x['hydrometry'][0])
plt.yscale('log')
