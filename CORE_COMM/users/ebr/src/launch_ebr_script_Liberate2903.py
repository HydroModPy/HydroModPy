# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan
"""

#%% ---- ENVIRONMENT

#%% IMPORT LIBRARIES

# General modules
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
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates

from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
               
# HydroModPy modules                  
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% FONCTIONS NECESSARY

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

#%% ---- WATERSHED

#%% PERSONAL PATHS

user = 'Cimpaye'

if user == 'Abherve':

    git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    # data_path = "H:/EBR/_data/"
    data_path = "C:/Users/ronan/Documents/EBRTRANSFERT/_data/"
    # Path where the results will be stored
    out_path = "C:/Users/ronan/Documents/EBRTRANSFERT/"
    
if user == 'Guillossou':
    # # Path to the git repositoty home page
    git_path = "C:/Users/r.guillossou/Documents/GitHub/HydroModPy/CORE_COMM/"
    # # Path to the data folder
    data_path = "C:/Users/r.guillossou/Documents/Data Hydromodpy/_data/"
    # # Path where the results will be stored
    out_path = 'C:/Users/r.guillossou/Documents/Resultats Hydromodpy/'

if user == 'Cimpaye':
    # # Path to the git repositoty home page
    git_path = "C:/Users/admin/Desktop/Gitub/HydroModPy/CORE_COMM/"
    # # Path to the data folder
    data_path = "G:/_data/"
    # # Path where the results will be stored
    out_path = 'D:/SimulationHydro/'

#%% DEFAULT PATHS

topography_path = data_path + 'topography/' # reginal DEM or conceptual DEM
modflow_path = data_path + 'modflow/' # add bin/ folder with necessary .exe
climate_path =  data_path + 'climate/'
reanalysis_dayon_path = climate_path + 'reanalysis_dayon_2015/' # add surfex models in .h5 format (France scale, else, specify None)
explore2_path = climate_path + 'explore2_2021/' # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = data_path + 'oceanic/' # add specific sea level files
hydrography_path = data_path + 'hydrography/' # add hydrographic shapefiles
hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
divers_path = data_path + 'divers/'
watershed_path = data_path + 'watershed/'
piezometry_path = False # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

# Option
dem_name = "BDALTI_75m_MA.tif" # name of dem
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_xy = []

# Depending on the choices
dem_path = topography_path + dem_name
library_path = watershed_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

"""
watershed_names = [
                   'Cheze',
                   'Canut',
                   'Drains',
                   'Couesnon',
                   'Rophemel',
                   'Mordelles',
                   ]
"""

watershed_names = [
                   'Cheze',
                   ]

types_obs = ['perennial','complete'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid','persitanc']

#%% EXTRACT CATCHMENT

load = False

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
    
    if watershed_name != 'Drains':
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

    if watershed_name == 'Drains':
        Drains_shp = divers_path + 'Drains.shp'
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      modflow_path=modflow_path,
                                      library_path=library_path,
                                      load=load,
                                      from_shp=Drains_shp,
                                      from_dem=from_dem,
                                      from_xy=from_xy,
                                      cell_size=cell_size)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
      
#%% DATA CATCHMENT

update_data = True

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    
    if update_data == True:
        
        #BV.add_surfex(reanalysis_dayon_path)
        #BV.add_drias(explore2_path)
        BV.add_geology(geology_path)
        BV.add_hydrology(hydrography_path, types_obs=types_obs, fields_obs=fields_obs)
        BV.add_oceanic(oceanic_path)
        BV.add_hydrometry(hydrometry_path)
        BV.add_intermittency(intermittency_path)
        BV.add_subbasin()
        try:
            if (watershed_name == 'Mordelles') | (watershed_name == 'Couesnon'):
                BV.add_piezometry()
        except:
            pass
        
    BV.add_hydrodynamic()
    BV.add_forcing()
    
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
            
#%% ---- CLIMATE

#%% REANALYSIS NORMALIZE

time_step = 'M'

fig = plt.subplots(1,1, figsize=(6,3))

dict_recharge = dict(zip(watershed_names, np.empty((2,1))))
dict_runoff = dict(zip(watershed_names, np.empty((2,1))))
dict_facnorm = dict(zip(watershed_names, np.empty((2,1))))

for watershed_name in watershed_names:
    
    print(watershed_name)
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    BV.add_forcing()
    
    BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2019,
                                  time_step = time_step,
                                  sim_state='transient') #
    BV.forcing.update_runoff_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2019,
                                  time_step = time_step,
                                  sim_state='transient') #
    
    Rraw = BV.forcing.recharge
    rraw = BV.forcing.runoff
    tmin_R = Rraw.first_valid_index().year+1
    tmax_R = Rraw.last_valid_index().year-1
    
    raw_path = data_path+'hydrometry/'
    Qo_paths = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_'+watershed_name+'*')
    print(Qo_paths)
    Qo_mix = pd.DataFrame()
    cp = 0
    for Qo_path in Qo_paths[:]:
        Qo = pd.read_csv(raw_path+Qo_path, sep=';', index_col=0, parse_dates=True)
        area = float(Qo_path.split('_')[-1].split('.')[0])
        # print(area)
        Qo = (Qo / (area*1000000)) * (3600 * 24) # m3/s to m/day
        Qo_mix[str(cp)] = Qo
        cp+=1
    Qobs = Qo_mix.mean(axis=1).squeeze()
    Qobs = Qobs.rename('Q')
    
    if time_step == 'M':
        Qobs = Qobs.resample('M').mean() # m/day in monthly
        
    tmin_Q = Qobs.first_valid_index().year+1
    tmax_Q = Qobs.last_valid_index().year-1
        
    year_min = max(tmin_Q, tmin_R)
    year_max = min(tmax_Q, tmax_R)
    
    Qobs_sel = select_period(Qobs, year_min, year_max)

    R_sel = select_period(Rraw, year_min, year_max)
    r_sel = select_period(rraw, year_min, year_max)
    
    Fnorm = Qobs_sel.mean() / (R_sel.mean() + r_sel.mean())
    print('Fnorm',Fnorm)
    
    R_norm = Rraw * Fnorm
    r_norm = rraw * Fnorm
    
    plt.plot(R_norm+r_norm)
    plt.yscale('log')
    
    dict_facnorm[watershed_name] = round(Fnorm, 2)
    dict_recharge[watershed_name] = R_norm
    dict_runoff[watershed_name] = r_norm
    
    print('Rnorm', (R_norm).mean() * 365 * 1000)
    print('rnorm', (r_norm).mean() * 365 * 1000)

#%% PROJECTIONS NORMALIZE

time_step = 'M'

dayon_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
              'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']

explore2_list = ['ECE-RCA','ECE-RAC','HAD-REG','NOR-R15',
                 'MPI-CCL','MPI-R09','CNR-RAC','CNR-ALA',
                 'IPS-WRF','HAD-CCL','IPS-RCA','NOR-HIR']

# mod_list = ['IPS1','NOR1','CAN3','CNR-ALA','ECE-RCA','MPI-CCL']

mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
            'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1',
            'ECE-RCA','ECE-RAC','HAD-REG','NOR-R15',
            'MPI-CCL','MPI-R09','CNR-RAC','CNR-ALA',
            'IPS-WRF','HAD-CCL','IPS-RCA','NOR-HIR']
mod_list = ['NOR1']

sce_list = ['RCP2.6','RCP8.5']
col_list = ['blue','red']
dict_scecol = dict(zip(sce_list, col_list))

all_proj = pd.DataFrame()
all_proj.index = pd.date_range(start='01/01/1975', end='31/12/2099', freq=time_step)

for watershed_name in watershed_names[:] :
    
    print(watershed_name)
    
    for mod in mod_list:
        
        try:
            if len(mod.split('-')) == 1:
                BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                  first_year = 1975, last_year = 2019,
                                                  time_step = time_step, sim_state='transient')
                BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce = 'historic',
                                                first_year = 1975, last_year = 2019,
                                                time_step = time_step, sim_state='transient')
            if len(mod.split('-')) == 2:
                GCM = mod.split('-')[0]
                RCM = mod.split('-')[1]
                BV.forcing.update_recharge_drias(gcm_mod = GCM, rcm_mod = RCM, sce_mod = 'historic',
                                                 first_year = 1975, last_year = 2019, sim_state='transient')
                BV.forcing.update_runoff_drias(gcm_mod = GCM, rcm_mod = RCM, sce_mod = 'historic',
                                                 first_year = 1975, last_year = 2019, sim_state='transient')
            
            if time_step == 'M':
                R_mod = BV.forcing.recharge.resample('M').mean()
                r_mod = BV.forcing.runoff.resample('M').mean()
    
            R_rea = select_period(dict_recharge[watershed_name].copy(), 1975, 2019)
            r_rea = select_period(dict_runoff[watershed_name].copy(), 1975, 2019)
            
            tmin_Rea = R_rea.first_valid_index().year+1
            tmax_Rea = R_rea.last_valid_index().year+1
            tmin_Mod = R_mod.first_valid_index().year+1
            tmax_Mod = R_mod.last_valid_index().year-1
            
            year_min = max(tmin_Rea, tmin_Mod)
            year_max = min(tmax_Rea, tmax_Mod)
            print(year_min, year_max)
            
            R_rea_sel = select_period(R_rea, year_min, year_max)
            r_rea_sel = select_period(r_rea, year_min, year_max)
            R_mod_sel = select_period(R_mod, year_min, year_max)
            r_mod_sel = select_period(r_mod, year_min, year_max)
            
            Fnorm = ( R_rea_sel.mean() + r_rea_sel.mean() )  / ( R_mod_sel.mean() + r_mod_sel.mean() )
            print(Fnorm)
            
            R_mod_norm = (Fnorm * R_mod)
            R_mod_norm = R_mod_norm[(R_mod_norm.index.strftime("%Y-%m")<='2005-07')]
            r_mod_norm = Fnorm * r_mod
            r_mod_norm = r_mod_norm[(r_mod_norm.index.strftime("%Y-%m")<='2005-07')]
            
            # all_proj[watershed_name+'_'+'REC'+'_'+mod+'_'+'historic'] = R_mod_norm
            # all_proj[watershed_name+'_'+'RUN'+'_'+mod+'_'+'historic'] = r_mod_norm
    
            for sce in sce_list:
            
                if len(mod.split('-')) == 1:
                    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                                      first_year = 1975, last_year = 2100,
                                                      time_step = time_step, sim_state='transient')
                    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce = sce,
                                                    first_year = 1975, last_year = 2100,
                                                    time_step = time_step, sim_state='transient')
                if len(mod.split('-')) == 2:
                    GCM = mod.split('-')[0]
                    RCM = mod.split('-')[1]
                    BV.forcing.update_recharge_drias(gcm_mod = GCM, rcm_mod = RCM, sce_mod = sce,
                                                     first_year = 1975, last_year = 2100, sim_state='transient')
                    BV.forcing.update_runoff_drias(gcm_mod = GCM, rcm_mod = RCM, sce_mod = sce,
                                                     first_year = 1975, last_year = 2100, sim_state='transient')
                
                R_proj_norm = BV.forcing.recharge * Fnorm
                r_proj_norm = BV.forcing.runoff * Fnorm
                
                all_proj[watershed_name+'_'+'REC'+'_'+mod+'_'+sce] = pd.concat((R_proj_norm, R_mod_norm), axis=1).mean(axis=1)
                all_proj[watershed_name+'_'+'RUN'+'_'+mod+'_'+sce] = pd.concat((r_proj_norm, r_mod_norm), axis=1).mean(axis=1)
    
            all_proj[watershed_name+'_'+'REC'+'_'+'REA'+'_'+'historic'] = R_rea
            all_proj[watershed_name+'_'+'RUN'+'_'+'REA'+'_'+'historic'] = r_rea
        except:
            pass
        
    if not os.path.exists(stable_folder+'recharge_runoff/'):
        toolbox.create_folder(stable_folder+'recharge_runoff/')
    all_proj.to_csv(stable_folder+'recharge_runoff/'+'_Climate_Time_Series_'+time_step+'.csv', sep=';')
            
#%% ---- MODEL

#%% PARAM SIMULATION

"""
watershed_names = [
                   'Cheze',
                   'Canut',
                   'Drains',
                   'Couesnon',
                   'Rophemel',
                   'Mordelles',
                   ]
"""

watershed_names = [
                   'Cheze',
                   ]

# type_simulation = 'analysis_past'
type_simulation = 'analysis_future'

if type_simulation == 'analysis_past':
    ### To chnage
    iD = 'checkpast'
    periods = [2015, 2019]
    time_step = 'M' # or 'D'
    ### Not change
    mod_list = ['REA']
    sce_list = ['historic']
    col_list = ['k']
    dict_scecol = dict(zip(sce_list, col_list))
    init_rech = 'mean' # or 'mean'
    for watershed_name in watershed_names[:]:
        print('##### '+watershed_name.upper()+' #####')
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        all_proj = pd.read_csv(stable_folder+'recharge_runoff/'+'_Climate_Time_Series_'+time_step+'.csv',
                               sep=';', index_col=0, parse_dates=True)
        for mod in mod_list:
            fig, ax = plt.subplots(1,1, figsize=(6,3))
            for sce in sce_list:
                c = dict_scecol[sce]
                toplot = all_proj[watershed_name+'_'+'REC'+'_'+mod+'_'+sce].resample('Y').sum()*1000
                ax.plot(toplot, color=c)
                ax.set_title(watershed_name+'_'+mod)
                ax.set_yscale('log')

if type_simulation == 'analysis_future':
    ### To change
    iD = 'projfuture'
    periods = [1990, 2025]
    time_step = 'M' # or 'D'
    mod_list = ['NOR1']
    ### Not change
    sce_list = ['RCP2.6','RCP8.5']
    col_list = ['blue','red']
    dict_scecol = dict(zip(sce_list, col_list))
    init_rech = 'first' # or 'mean'  
    for watershed_name in watershed_names[:]:
        print('##### '+watershed_name.upper()+' #####')
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        all_proj = pd.read_csv(stable_folder+'recharge_runoff/'+'_Climate_Time_Series_'+time_step+'.csv',
                               sep=';', index_col=0, parse_dates=True)
        for mod in mod_list:
            fig, ax = plt.subplots(1,1, figsize=(6,3))
            for sce in sce_list:
                c = dict_scecol[sce]
                toplot = all_proj[watershed_name+'_'+'REC'+'_'+mod+'_'+sce].resample('Y').sum()*1000
                ax.plot(select_period(toplot,2005,2100), color=c)
                ax.plot(select_period(toplot,1975,2005), color='k')
                ax.set_title(watershed_name+'_'+mod)
                ax.set_yscale('log')

dic_params = {
             'Cheze':       [3.4e-5,    0.1],
             'Canut':       [5.1e-5,    0.1],
             'Drains':      [2.4e-5,    2.0],
             'Couesnon':    [5.0e-5,    1.0],
             'Rophemel':    [2.5e-5,    0.3],
             'Mordelles':   [6.2e-5,    0.2]
             }

#%% RUN SIMULATION

# Options
sim_state = 'transient' # 'steady' or 'transient'
modpath_sim = False # run modpath particle tracking if True
run = True
actual_date = True # False if date is conceptual
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process    

for watershed_name in watershed_names[:]:
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
    
    compt = 1
    
    for mod in mod_list:
        
        for sce in sce_list:
            
            recharge = all_proj[watershed_name+'_'+'REC'+'_'+mod+'_'+sce]
            recharge = select_period(recharge, periods[0], periods[1])
            
            runoff = all_proj[watershed_name+'_'+'RUN'+'_'+mod+'_'+sce]
            runoff = select_period(runoff, periods[0], periods[1])
    
            BV.forcing.update_recharge(recharge, sim_state='transient')
            BV.forcing.update_runoff(runoff, sim_state='transient')
            
            # Store results
            list_model_name = []
            list_of_success = []
            list_flow_model = []
        
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
            
            K = dic_params[watershed_name][0]
            Sy = dic_params[watershed_name][1]
            BV.hydrodynamic.update_hyd_cond(K*86400) 
            BV.hydrodynamic.update_porosity(Sy/100)
              
            date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
            date_today = date_today.replace('/','-')
            date_today = date_today.replace(':','-')
            date_today = date_today.replace(' ','_')
            
            model_name = iD+'_'+str(compt)+'_'+\
                         mod+'-'+sce+'_'+\
                         str(nlay)+'-'+str(thickness)+'_'+\
                         str("{:.1e}".format(K))+'-'+str(Sy)+'_'+\
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
                        
            print(list_of_success)
                
            dictio = {}
            dictio['list_model_name'] = list_model_name
            dictio['list_of_success'] = list_of_success
            dictio['list_flow_model'] = list_flow_model
            h5file = simulations_folder+'/'+'list_'+iD+'_'+mod+'_'+sce
            
            dd.io.save(h5file, dictio)
        
        compt+=1

#%% POST-PROCESS

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    for mod in mod_list:
        
        for sce in sce_list:
        
            h5file = simulations_folder+'/'+'list_'+iD+'_'+mod+'_'+sce
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
                                          perenn_intermit_shp = True,
                                          groundwater_storage = True,
                                          residence_times = False,
                                          verbose = True,
                                          export_tif = True)
                        
                        # # Extract results
                        if model_name.split('_')[2].split('-')[-1] == 'historic':
                            rec = dict_recharge[watershed_name]
                            run = dict_runoff[watershed_name]
                            rec = select_period(rec, periods[0], periods[1])
                            run = select_period(run, periods[0], periods[1])
                        else:
                            rec = all_proj[watershed_name+'_'+'REC'+'_'+mod+'_'+sce]
                            run = all_proj[watershed_name+'_'+'RUN'+'_'+mod+'_'+sce]
                            rec = select_period(rec, periods[0], periods[1])
                            run = select_period(run, periods[0], periods[1])
                        
                        BV.results_modflow(ident=model_name,
                                           recharge=rec,
                                           runoff=run,
                                           actual_date=True,
                                           time_step='M')

#%% ---- REANALYSIS

### To change
iD = 'checkpast'

#%% PLOT CHRONIC SREAMFLOW

for watershed_name in watershed_names[:]:
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
    
    station_hydro = fnmatch.filter(os.listdir(data_path+'hydrometry/'), 'Hydrometric_'+watershed_name+'*')[0].split('\\')[-1] \
                        .split('_')[-2][:-2]
                        
    raw_path = data_path+'hydrometry/'
    Qo_paths = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_'+watershed_name+'*')
    Qo_mix = pd.DataFrame()
    cp = 0
    for Qo_path in Qo_paths:
        Qo = pd.read_csv(raw_path+Qo_path, sep=';', index_col=0, parse_dates=True)
        area = float(Qo_path.split('_')[-1].split('.')[0])
        # print(area)
        Qo = (Qo / (area*1000000)) * (3600 * 24) # m3/s to m/day
        Qo_mix[str(cp)] = Qo
        cp+=1
    Qobs = Qo_mix.mean(axis=1).squeeze()
    Qobs = Qobs.rename('Q')
    Qobs = Qobs.resample('M').mean() * 1000 * 30 # m/day in monthly
    
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'), key=os.path.getmtime)
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]
        
        if (watershed_name == 'Cheze') | (watershed_name == 'Canut') | (watershed_name == 'Drains'):
            Smod_path = simul+'/_watershed/_simulated_results.csv'
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        else:
            Smod_path = simul+'/_subbasins/'+'hydrometry_'+station_hydro+'/'+'_simulated_results.csv'
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            
        Qmod = Smod['outflow_drain'] # mm/day
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        
        Rmod = Smod['recharge'] * 1000 * 30
        
        Qmix = Qmod.to_frame()
        Qmix['1'] = Qobs
        Qmix.columns = ['Qmod','Qobs']
        
        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(3,3))
        ax.scatter(Qmix.Qobs, Qmix.Qmod,
                   s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
        ax.set_xlim(0.1,1000)
        ax.set_ylim(0.1,1000) 
        ax.set_xlabel('$Q_{obs}$ / A [mm/month]')
        ax.set_ylabel('$Q_{sim}$ / A [mm/month]')
        
        base_name = simul+'/_figures/'
        spec_name = 'PLOT CHRONIC SREAMFLOW 1'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(7,3))
        yearsmaj = mdates.YearLocator(5)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
    
        axb = ax.twinx()
        axb.set_ylabel('R [mm/month]', rotation=270, labelpad=25)
        axb.bar(Rmod.index, Rmod,
                color='blue', edgecolor='blue', lw=2.5)
        axb.set_ylim(0,1000)
        axb.invert_yaxis()
        axb.set_yticklabels([0,200])
        
        ax.set_ylabel('Q / A [mm/month]')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        ax.plot(Qmix.Qobs, color='k', lw=2, ls='-', zorder=0, label='observed')
        ax.set_yscale('log')
        ax.plot(Qmix.Qmod, color='red', lw=2, label='modeled')
        ax.set_ylim(0.1,200)
        # ax.set_xlim(pd.to_datetime('1975'), pd.to_datetime('2019'))
        
        base_name = simul+'/_figures/'
        spec_name = 'PLOT CHRONIC SREAMFLOW 2'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
 
        import hydroeval as he
        Qmix = Qmix.dropna(how='any')
        nse = he.evaluator(he.nse, Qmix.Qmod, Qmix.Qobs)[0] # 
        nselog = he.evaluator(he.nse, Qmix.Qmod, Qmix.Qobs, transform='log')[0] # 
        print(round(nse,2))
        print(round(nselog,2))

#%% PLOT CHRONIC SATURATION

for watershed_name in watershed_names[:]:
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
    
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'), key=os.path.getmtime)
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]

        Smod_path = simul+'/_watershed/_simulated_results.csv'
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        Rmod = Smod['recharge'] * 1000 * 30
        
        fig, ax = plt.subplots(1,1, figsize=(6,3))

        ax.plot(Smod['surflow_areas'], color='dodgerblue', ls='-', lw=2, label='catchment')
        ax.fill_between(Smod.index, Smod['perenn_areas'], Smod['surflow_areas'],
                        interpolate=False, color='dodgerblue', alpha=0.4)
        ax.plot(Smod['perenn_areas'], color='navy',
                marker=None, markeredgecolor='none',
                markersize=5, lw=2, label='upstream')
        ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                        interpolate=False, color='navy', alpha=0.4)
        
        ax.grid('grey', axis='x')
        ax.set_ylim(0,20)
        ax.set_ylabel('$A_{sat}$ [%]')
        # ax.set_xlim(pd.to_datetime('1975'), pd.to_datetime('2020'))

        months_maj = MonthLocator(6)  # every x month
        ax.xaxis.set_minor_locator(months_maj)
        
        ax.set_title(watershed_name)
        
        plt.tight_layout()
        
        base_name = simul+'/_figures/'
        spec_name = 'PLOT CHRONIC SATURATION'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% PLOT MAP HYDROGRAPHY

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
        
            base_name = simul+'/_figures/'
            spec_name = 'PLOT MAP HYDROGRAPHY '+str(k)
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% PLOT CROSSECTION MINMAX 

dates = pd.date_range(start='01/01/1975', end='31/12/2019', freq='M')

for watershed_name in watershed_names[:]:    
    
    fig, ax = plt.subplots(1, 1, figsize=(6,4), dpi=300)

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
    for i, key in enumerate([argmin, argmax]):
        print(key)

        dem_data = imageio.imread(BV.geographic.watershed_dem)
        wt_data = watertable_elevation[key]
        river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
    
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
        
        if watershed_name == 'xxx':
            dem_h_plot = dem_prof[int(cur_y),:]
            dem_h_plot[dem_h_plot == 0] = np.nan
            wt_h_plot = wt_prof[int(cur_y),:]
            wt_h_plot[wt_h_plot == 0] = np.nan
                        
        if (watershed_name == 'Canut') | (watershed_name == 'Cheze') | \
            (watershed_name == 'Drains') | (watershed_name == 'Couesnon') | \
             (watershed_name == 'Rophemel') | (watershed_name == 'Mordelles'):
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
        
        cp+=1
            
        if watershed_name == 'xxx':
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
                   
        if (watershed_name == 'Canut') | (watershed_name == 'Cheze') | \
            (watershed_name == 'Drains') | (watershed_name == 'Couesnon') | \
             (watershed_name == 'Rophemel') | (watershed_name == 'Mordelles'):
            if i == 0:
                wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 0, wt_v_plot,
                                                    color='dodgerblue', alpha=0.5, lw=0)
                w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=0.5)
            if i == 1:
                wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 0, wt_v_plot,
                                                    color='dodgerblue', alpha=0.5, lw=0)
                w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='dodgerblue', lw=0.5)
                wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
                d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1)
                
        ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-30, 'dimgray', lw=0, ls='-')
        ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-30, 0,
                                                color='lightgrey', alpha=0.8, lw=0)

        if (watershed_name == 'Cheze'):
            ax.set_xlim(500, 4200)
            ax.set_ylim(80, 160)
            ax.set_yticks([100,120,140,160])
        if (watershed_name == 'Canut'):
            ax.set_xlim(1000, 4000)
            ax.set_ylim(80, 140)
            ax.set_yticks([100,120,140])
        if (watershed_name == 'Drains'):
            ax.set_xlim(3000, 10000)
            ax.set_ylim(100, 150)
            ax.set_yticks([110,130,150])
        if (watershed_name == 'Couesnon'):
            ax.set_xlim(14000, 25000)
            ax.set_ylim(40, 160)
            ax.set_yticks([60,100,140])
        if (watershed_name == 'Rophemel'):
            ax.set_xlim(8000, 17500)
            ax.set_ylim(40, 150)
            ax.set_yticks([60,100,140])  
        if (watershed_name == 'Mordelles'):
            ax.set_xlim(6000, 25000)
            ax.set_ylim(30, 160)
            ax.set_yticks([40,80,120,160])    
            
        # plt.setp(ax.get_yticklabels()[0], visible=False)    
        # plt.setp(ax.get_yticklabels()[-1], visible=False)
            
        ax.set_title(watershed_name)
        
        plt.tight_layout()
        
        base_name = simul+'/_figures/'
        spec_name = 'PLOT CROSSECTION MINMAX'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
#%% PLOT MAP PERSISTENCY

var = 'REC'
sce_list = ['historic']

y_name = 'surflow_areas'

for watershed_name in watershed_names[:]:

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

    for ix in np.arange(0,1,1):
        
        fig, ax = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)

        simul = glob.glob(simulations_folder+'*'+iD+'_'+'*')[0]
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
        
        days_flux = np.ma.masked_where(days_flux == 0, days_flux)
    
        count_inf = np.ma.masked_where(days_flux > 0.1, days_flux).count()
        count_sup = np.ma.masked_where(days_flux < 0.9, days_flux).count()
        
        total = np.ma.masked_where(days_flux == 0, days_flux).count()
    
        print(watershed_name, (count_inf / total)*100, (count_sup / total)*100)
      
        position=fig.add_axes([0.93,0.35,0.01,0.30])  ## the parameters are the specified position you set 
        cb = fig.colorbar(pc,cax=position, orientation="vertical")
        position.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)
        cb.ax.tick_params(axis='y', direction='out')
        
        base_name = simul+'/_figures/'
        spec_name = 'PLOT MAP PERSISTENCY'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

        pi_path = os.path.join(simul, '_watershed', 'persistency_index.tif')
        toolbox.export_tif(BV.geographic.watershed_dem, pi, -99999, pi_path)

        pi_shp_path = os.path.join(simul, '_watershed', 'persistency_index.shp')
        wbt.raster_to_vector_points(pi_path, pi_shp_path)
        pi_shp = gpd.read_file(pi_shp_path)
        pi_shp['VALUE'][pi_shp['VALUE']>1] = 1
        pi_shp.to_file(pi_shp_path)

#%% PLOT MAP INTERMITTENCY

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
        
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'),
                       key=os.path.getmtime)
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data

    for simul in simul_list:
        
        years = np.arange(2019,2019+1,1)
        
        Smod_path = simul+'/_watershed/_simulated_results.csv'  
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        Smod = Smod.reset_index()
        Smod['iloc'] = Smod.index
        Smod = Smod.set_index('date')
        Smod = select_period(Smod, years[0], years[-1])
        
        for dt, i in zip(Smod.index, Smod['iloc']):
            
            fig, ax = plt.subplots(1,1, figsize=(7,6))
            
            show(dem_data, ax=ax, transform=dem.transform,
                  cmap='Greys', alpha=0.7, zorder=0, aspect="auto")
            
            ms=20

            shp = gpd.read_file(simul+'/_watershed/_surfaceflow/'+
                                'tracept_t('+str(i)+').shp')
            shp[shp['id_persist']==0].plot(ax=ax, column='id_persist', lw=0,
                                           marker='s', color='dodgerblue',
                                           markersize=ms, zorder=1)
            shp[shp['id_persist']==1].plot(ax=ax, column='id_persist', lw=0,
                                           marker='s', color='navy',
                                           markersize=ms, zorder=1)
            line.plot(ax=ax, color='k', lw=2)
    
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            plt.axis('off')
            
            ax.set_title(str(dt)[:7])
            fig.suptitle(simul.split('\\')[-1], fontsize=5)
    
            compt_print = "{:02d}".format(compt)

            base_name = simul+'/_figures/_intermittency/'
            if not os.path.exists(base_name):
                toolbox.create_folder(base_name)            
            spec_name = 'map_anim_'+str(i)+'_'+str(dt)[:7]
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
            
            plt.close()
        
        compt += 1

        if gif == True:
            begin_by = base_name+'map_anim_'
            filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
            images = []
            for filename in filenames:
                images.append(imageio.imread(filename))
            gif_name = '_map_anim_monthly'
            imageio.mimsave(base_name+gif_name+'.gif', images,
                            duration=0.25, loop=0)

#%% ---- PROJECTION

### To change
iD = 'projfuture'

#%% PLOT CHRONIC STREAMFLOW
 
sce_list = ['historic','RCP2.6','RCP8.5']

df = pd.DataFrame()

for watershed_name in watershed_names[:]:
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
            
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce_name+'*')
            
            if len(simul_list)>0 :
                simul = simul_list[0]
            else:
                continue
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            df['Q_'+mod+'_'+sce] = (Smod['outflow_drain']+ Smod['runoff']) * 1000 * 365 #
            
            if sce == 'historic':
                df['Q_'+mod+'_'+sce][df.index.year>2005] = np.nan
            
    fig, ax = plt.subplots(1,1, figsize=(10,4))
    
    per_list = [[1975,2005],[2005,2100],[2005,2100]]
    sce_list = ['historic','RCP2.6','RCP8.5']
    
    col_list = ['dimgrey','dodgerblue','red']
    col_list_b = ['k','navy','darkred']
    dict_c = dict(zip(sce_list, col_list))
    dict_c_b = dict(zip(sce_list, col_list_b))
    
    for sce, per in zip(sce_list, per_list):
        
        # d = select_period(df, per[0], per[1])
        
        # if typ_climate == 'DRIAS' :
        d = df.copy()
        d['MIN'] = d.filter(regex=sce).min(axis=1)
        d['Q5'] = d.filter(regex=sce).quantile(0.05, axis=1)
        d['Q10'] = d.filter(regex=sce).quantile(0.10, axis=1)
        d['Q25'] = d.filter(regex=sce).quantile(0.25, axis=1)
        d['MEAN'] = d.filter(regex=sce).mean(axis=1)
        d['MED'] = d.filter(regex=sce).median(axis=1)
        d['Q75'] = d.filter(regex=sce).quantile(0.75, axis=1)
        d['Q90'] = d.filter(regex=sce).quantile(0.90, axis=1)
        d['Q95'] = d.filter(regex=sce).quantile(0.95, axis=1)
        d['MAX'] = d.filter(regex=sce).max(axis=1)
        d = d.resample('Y').mean() #* 1000 * 365
            
        high = select_period(d['Q25'].copy(), per[0], per[1]).rolling(window=5).mean()
        mean = select_period(d['MED'].copy(), per[0], per[1]).rolling(window=5).mean()
        low = select_period(d['Q75'].copy(), per[0], per[1]).rolling(window=5).mean()
        
        high = select_period(d['Q25'].copy(), per[0], per[1])#.rolling(window=5).mean()
        mean = select_period(d['MED'].copy(), per[0], per[1])#.rolling(window=5).mean()
        low = select_period(d['Q75'].copy(), per[0], per[1])#.rolling(window=5).mean()
        
        ax.plot(mean, c=dict_c_b[sce], lw=2)
        ax.fill_between(mean.index, low, high, color=dict_c[sce], alpha=0.25, ec='None')
        ax.set_axisbelow(True)
        ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.set_xlim(pd.to_datetime('1976'), pd.to_datetime('2100'))
                
        ax.set_ylim(100, 600)
        
        yearsmaj = mdates.YearLocator(10)   # every year
        monthsmaj = mdates.MonthLocator(12)  # every month
        years_fmt = mdates.DateFormatter('%Y')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(monthsmaj)
        ax.xaxis.set_major_formatter(years_fmt)
        
        """
        base_name = simul+'/_figures/'
        spec_name = 'xxx'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        """
        
#%% PLOT MODEL COMPARISON
 
sce_list = ['historic','RCP2.6','RCP8.5']

df = pd.DataFrame()

for watershed_name in watershed_names[:]:
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
            
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce_name+'*')
            
            if len(simul_list)>0 :
                simul = simul_list[0]
            else:
                continue
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            df['Q_'+mod+'_'+sce] = (Smod['outflow_drain']+ Smod['runoff']) #
            
            if sce == 'historic':
                df['Q_'+mod+'_'+sce][df.index.year>2005] = np.nan
            

    sce_list = ['RCP2.6','RCP8.5']
    col_list = ['dimgray','maroon','darkorange','forestgreen','darkviolet','navy']
    dict_c = dict(zip(mod_list, col_list))
    
    for sce in sce_list:
        
        fig, ax = plt.subplots(1,1, figsize=(6,4))
    
        for mod in mod_list:
    
            d = df.copy()
            d = d.filter(regex=sce).filter(regex=mod)
            d = d.resample('Y').mean() * 1000 * 365
                
            # d = d.rolling(window=0).mean()
    
            ax.plot(d, c=dict_c[mod], lw=2, label=mod)
            ax.legend(loc='lower left', frameon=False)
            ax.set_title(watershed_name+'  '+sce)
            # ax.set_ylim(150, 500)
            
            yearsmaj = mdates.YearLocator(20)   # every year
            monthsmaj = mdates.MonthLocator(12)  # every month
            years_fmt = mdates.DateFormatter('%Y')
            ax.xaxis.set_major_locator(yearsmaj)
            ax.xaxis.set_minor_locator(monthsmaj)
            ax.xaxis.set_major_formatter(years_fmt)
        
            # ax.set_yscale('log')
            
            """
            base_name = simul+'/_figures/'
            spec_name = 'xxx'
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
            """
            
#%% PLOT BOXPLOT STREAMFLOW

sce_list = ['historic','RCP2.6','RCP8.5']

df = pd.DataFrame()

for watershed_name in watershed_names[:]:
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
                
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce_name+'*')
                        
            if len(simul_list)>0 :
                simul = simul_list[0]
            else:
                continue
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            df['Q_'+mod+'_'+sce] = ( Smod['outflow_drain'] + Smod['runoff'] ) * 1000 * 365
    
    fig, ax = plt.subplots(1,1, figsize=(5,4))
    
    per_list = [[1980,2005],[2010,2040],[2040,2070],[2070,2098]]
    # per_list = [[1980,2010]]
    
    sce_list = ['RCP8.5','RCP2.6']
    col_list = ['red','dodgerblue']
    dict_c = dict(zip(sce_list, col_list))
    
    g = 0
    
    for sce in sce_list:
            
        if g >= 0:
            
            i = 0
            
            for per in per_list:
                
                d = df.copy()
                d = d.filter(regex=sce) 
                d = select_period(d, per[0], per[1])
                d = d.resample('Y').mean()
                d = pd.Series(d.values.ravel('F'))
                
                if (per[0] == 1980) & (sce == 'RCP8.5'):
                    store = d.copy()
                
                if (per[0] == 1980):
                    d = store.copy()
                
                coul = dict_c[sce]
        
                if sce == 'RCP2.6':
                    ps = -0.12
                    ax.axvline(1.5, c='grey')
                if sce == 'RCP8.5':
                    ps = +0.12
                    ax.axvline(2.5, c='grey')
                if per[0] == 1980:
                    ps = 0
                    ax.axvline(3.5, c='grey')
                    coul = 'dimgray'
                
                boxprops = dict(linestyle='-', linewidth=1, color='black',
                                facecolor=coul, alpha=0.40)
                medianprops = dict(linestyle='-', linewidth=1, color='black')
                meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                                      markerfacecolor='k', linestyle='-')
                
                bp = ax.boxplot(d, widths=0.2,
                                positions=[i+1+ps],
                                  whis=False, showfliers=False, showmeans=False, 
                                  medianprops=medianprops, meanprops=meanpointprops,
                                  patch_artist=True, boxprops=boxprops)
                for element in bp['whiskers']:
                    element.set_color('k')
                    element.set_linestyle('-')
                
                ax.vlines(x=i+1+ps, 
                            ymin=d.quantile(0.75), 
                            ymax=d.quantile(0.90), color='k', zorder=2)
                ax.vlines(x=i+1+ps, 
                            ymin=d.quantile(0.10), 
                            ymax=d.quantile(0.25), color='k', zorder=2)
                ax.plot(i+1+ps, 
                          d.quantile(0.10), color='k', zorder=2, lw=0,
                          marker='_', mew=1)
                ax.plot(i+1+ps, 
                          d.quantile(0.90), color='k', zorder=2, lw=0,
                          marker='_', mew=1)
                  
                ax.plot(i+1+ps, d.mean(), marker='o', mec='k', ms=3, lw=0,
                        mfc='k', mew=1,
                        color='k', zorder=1000)
                
                ax.set_yscale('log')
                ax.set_ylim(2, 200)
                ax.set_ylim(150, 700)
                ax.set_yticks([150,300,400,500,600,700])
                ax.set_yticklabels([150,300,400,500,600,700])
                ax.set_xlim(0.5,4.5)
                     
                ax.set_axisbelow(True)
                ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
                ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')
                
                i += 1
      
            else:
                continue
    
    ax.set_xticklabels(['','2010 \n 2040','2040 \n 2070','2070 \n 2100','1980 \n 2010','','',''])
    
    """
    base_name = simul+'/_figures/'
    spec_name = 'xxx'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
    """
    
#%% PLOT INTERMENSUAL STREAMOFLOW

sce_list = ['historic','RCP2.6','RCP8.5']

df = pd.DataFrame()

for watershed_name in watershed_names[:]:
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
                
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce_name+'*')
            if len(simul_list)>0 :
                simul = simul_list[0]
            else:
                continue
            
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            
            df['Q_'+mod+'_'+sce] = (Smod['outflow_drain']+Smod['runoff']) * 1000 * 30 # + (Smod['runoff']*1)) 

    # per_list = [[2010,2040],[2040,2070],[2070,2100],[1980,2005]]
    per_list = [[2030,2100],[1980,2005]]
        
    sce_list = ['RCP8.5','RCP2.6']
    col_list = ['red','dodgerblue']
    col_list_b = ['darkred','navy']
    dict_c = dict(zip(sce_list, col_list))
    dict_c_b = dict(zip(sce_list, col_list))
    
    for sce in sce_list:
        
        i = 0
        
        fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))
        
        for per in per_list:
            
            if sce == 'RCP8.5':
                list_c = ['gold','darkorange','red','k']
            if sce == 'RCP2.6':
                list_c = ['forestgreen','dodgerblue','darkviolet','k']
                
            if sce == 'RCP8.5':
                list_c = ['red','grey']
                list_c_b = ['darkred','k']
            if sce == 'RCP2.6':
                list_c = ['dodgerblue','grey']
                list_c_b = ['navy','k']
            
            d = df.copy()
            d = d.filter(regex=sce)
            d = select_period(d, per[0], per[1])
            print(d.shape)
            # d = pd.Series(d.values.ravel('F'))
            d = d.stack().reset_index()
            d = d.set_index('date')
            d = d[0]
            
            if (sce == 'RCP8.5') & (per[0] == 1980):
                store = d
            
            if (sce == 'RCP2.6') & (per[0] == 1980):
                d = store.copy()
                
            dg = d.groupby([(d.index.month)]).median().to_frame()
            dg.columns = ['MED']
            dg['MIN'] = d.groupby([(d.index.month)]).min()
            dg['Q5'] = d.groupby([(d.index.month)]).quantile(0.05)
            dg['Q10'] = d.groupby([(d.index.month)]).quantile(0.1)
            dg['Q25'] = d.groupby([(d.index.month)]).quantile(0.25)
            dg['MEAN'] = d.groupby([(d.index.month)]).mean()
            dg['Q75'] = d.groupby([(d.index.month)]).quantile(0.75)
            dg['Q90'] = d.groupby([(d.index.month)]).quantile(0.90)
            dg['Q95'] = d.groupby([(d.index.month)]).quantile(0.95)
            dg['MAX'] = d.groupby([(d.index.month)]).max()

            coul = dict_c[sce]

            if per[0] == 1980:
                coul = 'k'
            
            ax.plot(dg['MED'], c=list_c_b[i], lw=3)

            ax.fill_between(dg.index, dg['Q10'], dg['Q90'], color=coul, alpha=0.25, ec='none')
            
            squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
            x1 = np.arange(1,12+1,1)
            ax.set_xticks(x1)
            ax.set_xticklabels(squad, minor=False, rotation='horizontal')
            ax.set_xlim(1,12)
            ax.set_yscale('log')
            
            ax.set_ylim(1, 500)
            
            ax.set_axisbelow(True)
            ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
            ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')
    
            i += 1
            
        """
        base_name = simul+'/_figures/'
        spec_name = 'xxx'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        """
        
#%% EXPORT ANOMALY STREAMFLOW

sce_list = ['historic','RCP2.6','RCP8.5']

df = pd.DataFrame()

for watershed_name in watershed_names[:]:
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
                
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce_name+'*')
            if len(simul_list)>0 :
                simul = simul_list[0]
            
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            df['Q_'+mod+'_'+sce] = Smod['outflow_drain'] * 1000 * 30
    
    dtemp = pd.DataFrame()
    for sce in sce_list:
        dtemp['Q_TOT1_'+sce] = df.filter(regex=sce).mean(axis=1)
        
        if sce == 'historic':
            dtemp['Q_TOT1_'+sce][dtemp.index.year>2005] = np.nan
    
    df = dtemp.copy()

    mod_list = ['TOT1']
    
    per = [2030,2100]
    
    sce_list = ['RCP2.6','RCP8.5']
    col_list = ['dodgerblue','red']
    dict_c = dict(zip(sce_list, col_list))
    
    fig, ax = plt.subplots(1,1, figsize=(4,3))
    
    dft = pd.DataFrame()
    
    for sce in sce_list:
        
        i = 0
                    
        hist = df.copy()
        hist = hist.filter(regex='historic')
        hist = select_period(hist, 1980, 2005)
        hist = hist.stack().reset_index()
        hist = hist.set_index('date')
        hist = hist[0]
        dft['Past'] = hist.groupby([(hist.index.month)]).mean()
        
        fut = df.copy()
        fut = fut.filter(regex=sce)
        fut = select_period(fut, per[0], per[1])
        fut = fut.stack().reset_index()
        fut = fut.set_index('date')
        fut = fut[0]
        dft['Future_'+sce] = fut.groupby([(fut.index.month)]).mean()
        
        dft['d_min_'+sce] = ((fut.groupby([(fut.index.month)]).min()-
                              hist.groupby([(hist.index.month)]).min())/
                              hist.groupby([(hist.index.month)]).min())*100
        dft['d_mean_'+sce] = ((fut.groupby([(fut.index.month)]).mean()-
                              hist.groupby([(hist.index.month)]).mean())/
                              hist.groupby([(hist.index.month)]).mean())*100
        dft['d_med_'+sce] = ((fut.groupby([(fut.index.month)]).median()-
                              hist.groupby([(hist.index.month)]).median())/
                              hist.groupby([(hist.index.month)]).median())*100
        dft['d_max_'+sce] = ((fut.groupby([(fut.index.month)]).max()-
                              hist.groupby([(hist.index.month)]).max())/
                              hist.groupby([(hist.index.month)]).max())*100
        
    dft[dft>100] = 100
    dft.boxplot(rot=-270)   
    
    
    dft = dft.T
    
    """
    base_name = simul+'/_figures/'
    spec_name = 'xxx/'
    dft.to_csv(base_name + spec_name + '_table_' + str(mod_list) + '.csv', sep=';')
    """
    
#%% PLOT RETURN QMNA

mod_list = ['IPS1','CNR-ALA']
sce_list = ['historic','RCP2.6','RCP8.5']

df = pd.DataFrame()

for watershed_name in watershed_names[:]:
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            if sce == 'historic':
                sce_name = 'RCP8.5'
            else:
                sce_name = sce
                
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce_name+'*')
            print(simul_list)
            if len(simul_list)>0 :
                simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            df['Q_'+mod+'_'+sce] = (Smod['outflow_drain']+Smod['runoff']) * 1000 * 30
            # df['Q_'+mod+'_'+sce] = Smod['surflow_areas']
            
    dtemp = pd.DataFrame()
    for sce in sce_list:
        dtemp['Q_TOT1_'+sce] = df.filter(regex=sce).mean(axis=1)
        
        if sce == 'historic':
            dtemp['Q_TOT1_'+sce][dtemp.index.year>2005] = np.nan
    
    df = dtemp.copy()

    mod = 'TOT1'

    per = [2030,2100]
    
    sce_list = ['RCP2.6','RCP8.5']
    col_list = ['dodgerblue','red']
    col_list_b = ['navy','darkred']
    dict_c = dict(zip(sce_list, col_list))
    dict_c_b = dict(zip(sce_list, col_list_b))
    
    fig, ax = plt.subplots(1,1, figsize=(4,3.5))
    
    dft = pd.DataFrame()
        
    for sce in sce_list:
        
        i = 0
        
        hist = df.copy()
        hist = hist.filter(regex='historic')
        hist = hist.filter(regex=mod)
        hist = select_period(hist, 1980, 2005)
        hist = hist.stack().reset_index()
        hist = hist.set_index('date')
        hist = hist[0]

        fut = df.copy()
        fut = fut.filter(regex=sce)
        fut = fut.filter(regex=mod)
        fut = select_period(fut, per[0], per[1])
        fut = fut.stack().reset_index()
        fut = fut.set_index('date')
        fut = fut[0]
        
        ################################################
        
        qmna_hist = hist.groupby([(hist.index.year)]).min()
        qmna_sort = qmna_hist.sort_values().to_frame()
        qmna_sort.columns = ['x']
    
        qmna_sort = qmna_sort.round(3) #/ 12
        
        # Method 1
        Z = qmna_sort.copy()
        N = len(Z)
        count, bins_count = np.histogram(Z, bins=100, density=True)
        pdf = count / sum(count)
        cdf = np.cumsum(pdf)
        
        # Method 2
        qh = np.array(qmna_sort.copy())
        LBINS = 100
        # No log
        linbins = np.linspace(0, qh.max(), LBINS)
        hist_lin, bins_lin = np.histogram(qh, bins=linbins, density=True)
        bins_lin_centers = 0.5*(bins_lin[1:]+bins_lin[:-1])
        # Log
        logbins = np.logspace(np.log10(qh.min()), np.log10(qh.max()), LBINS)
        hist_log, bins_log = np.histogram(qh, bins=logbins, density=True)
        bins_log_centers = 10**(0.5*(np.log10(bins_log[1:]) + np.log10(bins_log[:-1])))
        
        freq = qmna_sort.groupby('x').size().reset_index(name='counts')
        freq['frequency'] = freq.counts/freq.counts.sum() #freq
        freq['cumulative_frequency'] = freq['frequency'].cumsum() #freq cumulated
        freq['retour'] = 1/(freq['cumulative_frequency'])
        freq['target'] = 5
        
        ax.plot(freq['retour'], freq['x']-2, ls='-', c='grey', linewidth=2)
        ax.plot(freq['retour'], freq['x']-2, ls='-', c='k', marker='+',
                ms=6, mew=2, linewidth=0)
    
        ################################################
    
        qmna_fut = fut.groupby([(fut.index.year)]).min()
        qmna_sort = qmna_fut.sort_values().to_frame()
        qmna_sort.columns = ['x']
        qmna_sort = qmna_sort.round(3) #/ 12
        
        # Method 1
        Z = qmna_sort.copy()
        N = len(Z)
        count, bins_count = np.histogram(Z, bins=100, density=True)
        pdf = count / sum(count)
        cdf = np.cumsum(pdf)
        
        # Method 2
        qh = np.array(qmna_sort.copy())
        LBINS = 100
        # No log
        linbins = np.linspace(0, qh.max(), LBINS)
        hist_lin, bins_lin = np.histogram(qh, bins=linbins, density=True)
        bins_lin_centers = 0.5*(bins_lin[1:]+bins_lin[:-1])
        # Log
        logbins = np.logspace(np.log10(qh.min()), np.log10(qh.max()), LBINS)
        hist_log, bins_log = np.histogram(qh, bins=logbins, density=True)
        bins_log_centers = 10**(0.5*(np.log10(bins_log[1:]) + np.log10(bins_log[:-1])))
        
        freq = qmna_sort.groupby('x').size().reset_index(name='counts')
        
        freq['frequency'] = freq.counts/freq.counts.sum() #freq
        freq['cumulative_frequency'] = freq['frequency'].cumsum() #freq cumulated
        freq['retour'] = 1/(freq['cumulative_frequency'])
        freq['target'] = 5
        
        print(sce)
        ax.plot(freq['retour'], freq['x']-2, ls='-', c=dict_c[sce], linewidth=2)
        ax.plot(freq['retour'], freq['x']-2, ls='-', c=dict_c_b[sce], marker='+',
                ms=6, mew=2, linewidth=0)
        
        ################################################
        
        # ax.set_ylim(2, 7)
        # ax.set_yticks([1, 2, 3, 4])
        # ax.set_yscale('log')
        ax.set_xlim(1, 20)
        ax.set_xscale('log')
        ax.set_xticks([2, 5, 10, 20])
        ax.get_xaxis().set_major_formatter(mpl.ticker.ScalarFormatter())
        
        ax.set_axisbelow(True)
        ax.xaxis.grid(color='gray', alpha=0.5, zorder=-20)
        ax.yaxis.grid(color='gray', alpha=0.5, zorder=-20, which='both')
            
    """
    base_name = simul+'/_figures/'
    spec_name = 'xxx'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
    """
        
#%% PLOT MAP PERSISTENCY

var = 'REC'
sce_list = ['historic']

y_name = 'surflow_areas'

for watershed_name in watershed_names[:]:

    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'    

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    for ix in np.arange(0,1,1):
        
        fig, ax = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)

        simul = glob.glob(simulations_folder+iD+'_'+'*')[0]
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
        
        cmap = plt.cm.YlGnBu
        cmaplist = [cmap(i) for i in range(cmap.N)]
        cmaplist = ['skyblue','dodgerblue','navy']
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
     
        days_flux = np.ma.masked_where(days_flux == 0, days_flux)
    
        count_inf = np.ma.masked_where(days_flux > 0.1, days_flux).count()
        count_sup = np.ma.masked_where(days_flux < 0.9, days_flux).count()
        
        total = np.ma.masked_where(days_flux == 0, days_flux).count()
    
        print(watershed_name, (count_inf / total)*100, (count_sup / total)*100)
      
        position=fig.add_axes([0.93,0.35,0.01,0.30])  ## the parameters are the specified position you set 
        cb = fig.colorbar(pc,cax=position, orientation="vertical")
        position.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)
        cb.ax.tick_params(axis='y', direction='out')
        
        """
        base_name = simul+'/_figures/'
        spec_name = 'xxx'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        """
        
        pi_path = os.path.join(simul, '_watershed', 'persistency_index.tif')
        toolbox.export_tif(BV.geographic.watershed_dem, pi, -99999, pi_path)

        pi_shp_path = os.path.join(simul, '_watershed', 'persistency_index.shp')
        wbt.raster_to_vector_points(pi_path, pi_shp_path)
        pi_shp = gpd.read_file(pi_shp_path)
        pi_shp['VALUE'][pi_shp['VALUE']>1] = 1
        pi_shp.to_file(pi_shp_path)

#%% PLOT MAP INTERMITTENCY

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
        
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'),
                       key=os.path.getmtime)
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data

    for simul in simul_list:
        
        years = np.arange(2025,2030+1,1)
        
        Smod_path = simul+'/_watershed/_simulated_results.csv'  
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        Smod = Smod.reset_index()
        Smod['iloc'] = Smod.index
        Smod = Smod.set_index('date')
        Smod = select_period(Smod, years[0], years[-1])
        
        for dt, i in zip(Smod.index, Smod['iloc']):
            
            fig, ax = plt.subplots(1,1, figsize=(7,6))
            
            show(dem_data, ax=ax, transform=dem.transform,
                  cmap='Greys', alpha=0.7, zorder=0, aspect="auto")
            
            ms=20

            shp = gpd.read_file(simul+'/_watershed/_surfaceflow/'+
                                'tracept_t('+str(i)+').shp')
            shp[shp['id_persist']==0].plot(ax=ax, column='id_persist', lw=0,
                                           marker='s', color='dodgerblue',
                                           markersize=ms, zorder=1)
            shp[shp['id_persist']==1].plot(ax=ax, column='id_persist', lw=0,
                                           marker='s', color='navy',
                                           markersize=ms, zorder=1)
            line.plot(ax=ax, color='k', lw=2)
    
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            plt.axis('off')
            
            ax.set_title(str(dt)[:7])
            fig.suptitle(simul.split('\\')[-1], fontsize=5)
    
            compt_print = "{:02d}".format(compt)

            base_name = simul+'/_figures/_intermittency/'
            if not os.path.exists(base_name):
                toolbox.create_folder(base_name)            
            spec_name = 'map_anim_'+str(i)+'_'+str(dt)[:7]
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
            
            plt.close()
        
        compt += 1

        if gif == True:
            begin_by = base_name+'map_anim_'
            filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
            images = []
            for filename in filenames:
                images.append(imageio.imread(filename))
            gif_name = '_map_anim_monthly'
            imageio.mimsave(base_name+gif_name+'.gif', images,
                            duration=0.25, loop=0)

#%% ---- NOTES

