# -*- coding: utf-8 -*-
"""
Created on Fri Jan  6 16:15:34 2023

@author: ronan
"""

#%% INFORMATION
"""
Example to test MODPATH: pathlines and residence times
- Study site in Guadeloupe with residence times measurement targets
- Estimate K in steady-state from a stream network layer: Kcalib
- Launch MODPATH from different complexity of hydraulic properties hetrogeneity 
  with a bottom flat aquifer:
    .K lower layer = K upper layer
    .K lower layer = K upper layer / 10
    .K lower layer = K upper layer * 10
        *where Kupper = Kcalib and the lower layer start from 50 m
- Option for modeling particles:
    . Forward from all cells at the surface of target
    . Backward from all cells at the surface of target
- Post-processing on the pathlines and strating/endpoint
    . Identified the pathlines passed through a geological formation or not
        *using the 'pthobj' MODLFOW
    . From indices obtained, apply mask on pathlines/starting/ending files
        *using the shapefiles created
"""
#%% LIBRAIRIES

import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import glob
from os.path import dirname, abspath
import pandas as pd
import geopandas as gpd
import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
from datetime import datetime
import deepdish as dd
import imageio
import rasterio
import flopy
import pickle
import random
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show

from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from calibration import calib_root, calib_analysis, calib_basis
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display

#%% USERS

# user_path = "Martin"
user_path = "Ronan"
# data_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/USERS/QUIOCK/"
data_path = 'C:/Users/ronan/OneDrive/UNINE/11_Paper/QUIOCK/_data/QUIOCK/'
# out_path = "C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/"
out_path = 'C:/Users/ronan/Simulations/GUADELOUPE/'
# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/v1/raw/"
# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/v1/explor/"
# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/v2/paper1/"
# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/v3/"

# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/tests1/"
# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/nearest1/"
fig_path = 'C:/Users/ronan/OneDrive/UNINE/11_Paper/QUIOCK/_figures/bulk/'

print("Define a well-validated name of user")

#%% PATHS

watershed_name = 'Quiock3'

library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

if watershed_name == 'Quiock2':
    dem_name = "BasseTerre_dem_clip.tif"
    from_shp = None
    types_obs = ['L_Quiock_creek2']
    fields_obs = ['fid']

if watershed_name == 'Quiock3':
    dem_name = "BasseTerre_dem_clip.tif"
    from_shp = []
    types_obs = ['L_Quiock_creek2']
    fields_obs = ['fid']

from_dem = False
cell_size = None
    
climate_path =  None
dem_path = os.path.join(data_path,dem_name)
geology_path = None
hydrology_path = os.path.join(data_path)
hydrometry_path = 'None' # add hydrometry data for automatic download
intermittency_path = 'None' # add intermittency data for automatic download
modflow_path = os.path.join(data_path,'modflow')
oceanic_path = None
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

#%% WATERSHED

load = True
# False to build and save python object4

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              cell_size=cell_size)

BV.add_hydrometry(hydrometry_path)
BV.add_intermittency(intermittency_path)
BV.geographic.reg_path = 'C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3\\results_stable/geographic/regional/'
BV.add_subbasin()

d8_path = stable_folder+'/geographic/watershed_buff_direc.tif'
down_path = stable_folder+'/geographic/watershed_downslope.tif'
wbt.downslope_flowpath_length(
    d8_path, 
    down_path, 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)

#%% DATA

BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

BV.add_oceanic('None')
BV.add_hydrodynamic()
BV.add_forcing()
    
# watershed_display.watershed_dem(BV)
# watershed_display.watershed_local(dem_path, BV)

#%% ---- DICHOTOMY

#%% LAUNCH

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

area = BV.geographic.area
    
recharge = 2 / 365  # m/y to m/d

BV.forcing.update_recharge(recharge, sim_state='steady') #

BV.hydrodynamic.update_porosity(0.01)
BV.hydrodynamic.update_hyd_cond(2)
BV.hydrodynamic.update_nlay(1)
BV.hydrodynamic.update_thickness(40)
BV.hydrodynamic.update_bottom(-100)
# BV.hydrodynamic.update_bottom(None)
BV.hydrodynamic.update_cond_decay(0)
BV.hydrodynamic.update_thick_exp(1)

params_df = pd.DataFrame(columns=['params',
                                  'init_values','lower_bounds','higher_bounds',
                                  'units','scale'])
params_df.loc[0] = ['k1','?',8.64e-04,8.64e-01,'m/j','lin']

params_file = 'calib_dicot_hom_1v_k1'

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

calib = calib_root.Calibration(params_file, BV, observations = ['streams'])

dicot = calib.dichotomy(gap=1)

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

df.loc[0,types_obs[0]] = koptim / 24 / 3600
df.loc[1,types_obs[0]] = kr
df.loc[2,types_obs[0]] = obj_func

df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

#%% ---- MODELING

#%% CASES

# Import K calibrated
df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
Koptim = float('{:.1e}'.format(df.loc[0][1]))

# Aquifer
thick = 300 # m
bottom = -100 # aquifer flat or not

# Discretization
nlay = 50 # vertical discrtization
thick_exp = 1.2 # exponential decay of nlay with depth

# Climate
recharge = 2 / 365 # m/y to m/d

# Porosity
Sy = 0.1 # Charlotte ==> 10%

######################
    # case = 'k0k1'
    # case = 'calib'
    # case = 'inter1'
    # case = 'best1'
    # case = 'explor1'
    # case = 'paper2'
    # case = 'paper3'
    # case = 'test1'
    # case = 'poro5'
# case = 'tests1'
case = 'nearest1'
######################

if case == 'k0k1':
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    k_minus = list(np.geomspace(Koptim * 3600 * 24 / 100, Koptim * 3600 * 24, 20)[:-1])
    k_plus = list(np.geomspace(Koptim * 3600 * 24, Koptim * 3600 * 24 * 100, 20))
    k1s = k_minus.copy()
    k1s.extend(k_plus)
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'casek0k1'

if case == 'calib':
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    k1s = [Koptim * 3600 * 24 / 0.6]
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'casecalib'
    
if case == 'inter1':
    etot = 400
    esurf = 40
    list_x = np.array([0.01,0.1,1,10,100])
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    thick_k0 = 40 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = [ [ [k0s[0], [0, thick_k0]] ],
                 [ [k0s[1], [0, thick_k0]] ],
                 [ [k0s[2], [0, thick_k0]] ],
                 [ [k0s[3], [0, thick_k0]] ],
                 [ [k0s[4], [0, thick_k0]] ],
               ]
    # Name
    typ = 'caseinter1'

if case == 'best1':
    etot = 400
    esurf = 40
    list_x = np.array([0.1,1,10])
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    k1s = np.append(k1s,None)
    ke = Koptim * (etot/esurf)*(1-np.exp(-etot/esurf)) * 3600 * 24
    k0s = np.append(k0s,ke)
    
    thick_k0 = 40 # thickness of the upper layer
    cond_decays = [0, 0, 0, 1/esurf] # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = [ [ [k0s[0], [0, thick_k0]] ],
                 [ [k0s[1], [0, thick_k0]] ],
                 [ [k0s[2], [0, thick_k0]] ],
                 None
               ]
            
    # Name
    typ = 'casebest1'

if case == 'explor1':
    etot = 400
    esurf = 40
    # list_x = np.array([0.1,1,10])
    list_x = np.geomspace(0.001, 1000, 10)
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    thick_k0 = 40 # thickness of the upper layer
    cond_decays = [0] * 10 # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = []
    for i in range(len(list_x)):
        verti_ks.append( [ [k0s[i], [0, thick_k0]] ] )
            
    # Name
    typ = 'explor1'
    
if case == 'paper2':
    etot = 400
    esurf = 40
    # list_x = np.array([0.1,1,10])
    # list_x = np.geomspace(0.001, 1000, 10)
    list_x = np.array([1/1000,1/100,1/10,1,10,100,1000])
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    thick_k0 = 40 # thickness of the upper layer
    cond_decays = [0] * 10 # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = []
    for i in range(len(list_x)):
        verti_ks.append( [ [k0s[i], [0, thick_k0]] ] )
            
    # Name
    typ = 'paper2'

if case == 'paper3':
    etot = 400
    esurf = 40
    # list_x = np.array([0.1,1,10])
    # list_x = np.geomspace(0.001, 1000, 10)
    list_x = np.array([1/1000,1/100,1/10,1,10,100,1000,10000])
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    thick_k0 = 40 # thickness of the upper layer
    cond_decays = [0] * 10 # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = []
    for i in range(len(list_x)):
        verti_ks.append( [ [k0s[i], [0, thick_k0]] ] )
            
    # Name
    typ = 'paper3'

if case == 'test1':
    etot = 400
    esurf = 40
    # list_x = np.array([0.1,1,10])
    # list_x = np.geomspace(0.001, 1000, 10)
    list_x = np.array([1000])
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    thick_k0 = 40 # thickness of the upper layer
    cond_decays = [0] * 10 # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = []
    for i in range(len(list_x)):
        verti_ks.append( [ [k0s[i], [0, thick_k0]] ] )
            
    # Name
    typ = 'test1'

if case == 'tests1':
    etot = 400
    esurf = 40
    # list_x = np.array([0.1,1,10])
    # list_x = np.geomspace(0.001, 1000, 10)
    list_x = np.array([1/1000,1/100,1/10,1,10,100,1000,10000])
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    thick_k0 = 40 # thickness of the upper layer
    cond_decays = [0] * 10 # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = []
    for i in range(len(list_x)):
        verti_ks.append( [ [k0s[i], [0, thick_k0]] ] )
            
    # Name
    typ = 'tests1'

if case == 'nearest1':
    etot = 400
    esurf = 40
    # list_x = np.array([0.1,1,10])
    # list_x = np.geomspace(0.001, 1000, 10)
    list_x = np.array([50,150,200,250,500])
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    thick_k0 = 40 # thickness of the upper layer
    cond_decays = [0] * 10 # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = []
    for i in range(len(list_x)):
        verti_ks.append( [ [k0s[i], [0, thick_k0]] ] )
            
    # Name
    typ = 'nearest1'

if case == 'poro5':
    etot = 400
    esurf = 40
    # list_x = np.array([0.1,1,10])
    # list_x = np.geomspace(0.001, 1000, 10)
    list_x = np.array([150])
    k0s = Koptim * (etot/(esurf+((etot-esurf)/list_x))) * 3600 * 24
    k1s = (k0s / list_x)
    thick_k0 = 40 # thickness of the upper layer
    cond_decays = [0] * 10 # exponential decay of K with depth : 0.02
    # Vertical
    verti_ks = []
    for i in range(len(list_x)):
        verti_ks.append( [ [k0s[i], [0, thick_k0]] ] )
    Sy = 0.05
    
    # Name
    typ = 'poro5'

#%% OPTIONS

# Option
sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = True # run modpath particle tracking if True
# modpath_sim = False # run modpath particle tracking if True

run = True

# Input recharge
time_step = 'D' # or 'D'
actual_date = False # False if date is conceptual

# Active of not modules
box=True
# zone_partic = 'watershed_box_buff' # watershed or watershed_buff
# zone_partic = 'watershed' # watershed or watershed_buff
zone_partic = 'domain' # watershed or watershed_buff
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process

# Recharge
init_rech = None
BV.forcing.update_recharge(recharge, sim_state=sim_state) #

#%% RUN

# Label
list_model_name = []
list_of_success = []
list_flow_model = []

# Update properties
compt = 1

BV.hydrodynamic.update_nlay(nlay) # 1
BV.hydrodynamic.update_bottom(bottom) # None
BV.hydrodynamic.update_thick_exp(thick_exp) # 1
BV.hydrodynamic.update_thickness(thick) # 30 / intervient pas si bottom != None

BV.hydrodynamic.update_porosity(Sy)
  
date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
date_today = date_today.replace('/','-')
date_today = date_today.replace(':','-')
date_today = date_today.replace(' ','_')

for i, (k0, k1, verti_k, cond_decay) in enumerate(zip(k0s, k1s, verti_ks, cond_decays)):
    print(i, k1, verti_k, cond_decay)
    
    """    
    if i <= 2:
        BV.hydrodynamic.update_hyd_cond(k1)
        model_name = typ+'_'+str(compt)+'_'+\
                         str(Sy*100)+'-'+str(round(verti_k[0][0]/k1,3))+'-'+str(thick)+'_'+str(nlay)
        
    if i == 3:
        BV.hydrodynamic.update_hyd_cond(k0)
        model_name = typ+'_'+str(compt)+'_'+\
                         str(Sy*100)+'-'+'e'+str(cond_decay)+'-'+str(thick)+'_'+str(nlay)
    """    
    
    BV.hydrodynamic.update_hyd_cond(k1)
    model_name = typ+'_'+str(compt)+'_'+\
                     str(Sy*100)+'-'+str(round(verti_k[0][0]/k1,3))+'-'+str(thick)+'_'+str(nlay)
    BV.hydrodynamic.update_cond_decay(cond_decay) # 0

    if run == True:
        # try:
        print('SIM - ' + model_name)

      
        success, flow_model = BV.run_modflow(ident=model_name,
                                             run=run,
                                             modpath_sim=modpath_sim,
                                             sink_fill=sink_fill,
                                             zone_partic=zone_partic,
                                             box=box,
                                             verbose=verbose,
                                             post_process=post_process, 
                                             init_rech=init_rech,
                                             verti_k_tconst=verti_k)
                
    if success == True:
        print(     'Success')
    else:
        print(     'Error')
    # except:
    #     pass
    list_model_name.append(model_name)
    list_of_success.append(success)
    list_flow_model.append(flow_model)
    compt+=1
        
print(list_of_success)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_of_success'] = list_of_success
dictio['list_flow_model'] = list_flow_model
h5file = simulations_folder+'/'+'list_'+typ

dd.io.save(h5file, dictio)

#%% ---- POST-PROCESS

#%% LOAD MODELS

h5file = simulations_folder+'/'+'list_'+typ
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_of_success = d['list_of_success'][:]
list_flow_model = d['list_flow_model'][:]

#%% EXTRACT RESULTS

data_explo = pd.DataFrame(columns=['k0','k1','k0k1','obs','sim','ind']) 

cp = 0

for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
        
    if success==True:
            print(success)
            
            if modpath_sim == True:
                residence_times=True
            else:
                residence_times=False
            
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
            BV.results_modflow(ident=model_name,
                               actual_date=actual_date,
                               time_step=time_step)
            
            ## Plot maps
            surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
                                                  model_name, types_obs,
                                                  save_gif=False,
                                                  first_only=True,
                                                  sim_state=sim_state,
                                                  outflow=False,
                                                  accflux=True,
                                                  intermittency=False,
                                                  chronics=False)
            
            ### Calib
            from calibration import calib_objective_function
            obj_func = calib_objective_function.Streams(BV, 
                                                        hydrology_stable=os.path.join(BV.stable_folder, 'hydrology'),
                                                        calibration_folder=os.path.join(BV.simulations_folder, 
                                                                                        model_name))
            ind, obs, sim = obj_func.get_indicator()
            
            # Stream calib
            data_explo.loc[cp,'k0k1'] = model_name.split('_')[2].split('-')[1]
            data_explo.loc[cp,'D_os'] = obs
            data_explo.loc[cp,'D_so'] = sim
            data_explo.loc[cp,'D_ind'] = ind
            
            # Discharge calib
            sub_res_path = os.path.join(BV.simulations_folder, model_name, 
                                        '_subbasins', 'subbasin_Flowrate')
            sub_res = pd.read_csv(os.path.join(sub_res_path, '_simulated_results.csv'), ';',
                                  index_col='date', parse_dates=True)
            data_explo.loc[cp,'Qacc_sim'] = sub_res['accumulation_flux'].values[0]
            sub_area = gpd.read_file(BV.subbasin.subbasin_path+"subbasin_Flowrate/"+
                                     'watershed.shp')
            sub_area = sub_area.area # / 1e6
            data_explo.loc[cp,'Qout_sim'] = sub_res['outflow_drain'].values[0] * sub_area[0]
            data_explo.loc[cp,'R'] = BV.forcing.recharge * sub_area[0]
            data_explo.loc[cp,'Qsub_obs'] =  3.1 / 1000 * 3600 * 24 # L/s to m3/j            

            # Residence times
            if modpath_sim == True:
                res_path = os.path.join(BV.simulations_folder, model_name, 
                                            '_watershed')
                res = pd.read_csv(os.path.join(res_path, '_simulated_results.csv'), ';',
                                      index_col='date', parse_dates=True)
                data_explo.loc[cp,'t_sim'] = res['residence_times'].values[0]
            
            cp+=1

data_explo['k0'] = k0s
data_explo['k1'] = k1s            

data_explo.to_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')
print(data_explo)

#%% ---- MODPATH FILES NEW

#%% ENDPOINT MODELS

# model_name = 'egu1_1_10.0-0.0-0.0857-26.68'
# model_name = 'egu1_0_500.0-0-0.0058-30.0'

fig_cross = True

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

for model_name in list_selects[:]:
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
        
        axs[0].set_ylim(150, 350)
        axs[1].set_ylim(150, 350)
        
        fig.savefig(fig_path+'cross_section_h_'+model_name+'.png', dpi=300, bbox_inches='tight')
        
        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[0])/2)})
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
        
        axs[0].set_ylim(150, 350)
        axs[1].set_ylim(150, 350)
        
        fig.savefig(fig_path+'cross_section_v_'+model_name+'.png', dpi=300, bbox_inches='tight')
        
    crs_code = 32620 # 2154

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
    
    ########################################## BEGIN WEIGHTED ##########################################
    modeldir = simulations_folder+model_name+'/'
    namepath = model_name
    recharge = flow_model.rchData[0]
    mymodel       = mf
    mybas         = mymodel.get_package('BAS6')
    mydis         = mymodel.get_package('DIS')
    ncol          = np.unique(mydis.ncol)[0]
    nrow          = np.unique(mydis.nrow)[0]
    nlay          = np.unique(mydis.nlay)[0]
    dcol          = np.unique(mydis.delc)[0]
    drow          = np.unique(mydis.delr)[0]    

    period        = 0
    step          = 0
    import flopy.utils.postprocessing as pp

    Qx, Qy, Qz_rech  = pp.get_extended_budget(modeldir+namepath+'.cbc', precision='single', idx=None, 
                                              kstpkper=(step, period), totim=None,boundary_ifaces={'RECHARGE': 6}, hdsfile=modeldir+namepath+'.hds', 
                                              model=mymodel)
    Qx_2, Qy_2, Qz_drain  = pp.get_extended_budget(modeldir+namepath+'.cbc', precision='single', idx=None, 
                                                   kstpkper=(step, period), totim=None,boundary_ifaces={'DRAINS': 6}, hdsfile=modeldir+namepath+'.hds', 
                                                   model=mymodel)
    rech_loop = np.zeros([nrow,ncol])
    for i in range(0,nrow):
        for j in range (0,ncol):
            if Qz_rech[0,i,j] == 0:
                rech_loop[i,j] =-recharge*dcol*drow
            else:
                rech_loop[i,j] =Qz_rech[0,i,j]
                
    rech = -rech_loop
    rech[-1,:] = 0
    rech[:,-1] = 0
    rech[:,0] = 0
    drain = Qz_drain[0,:,:]
    sflux = rech - drain
    sflux[sflux > rech] = rech.max()
    sflows = sflux/drow/dcol
    
    toolbox.export_tif(BV.geographic.watershed_box_buff_dem,
                       sflows, -9999,
                       simulations_folder+
                               model_name+'/'+'_pathlines/'+
                               'sflows_weighted.tif')
    
    wbt.extract_raster_values_at_points(simulations_folder+model_name+'/'+'_pathlines/'+'sflows_weighted.tif', 
                                        simulations_folder+model_name+'/'+'_pathlines/'+'starting_years.shp', 
                                        out_text=False)
    
    start = gpd.read_file(simulations_folder+model_name+'/'+'_pathlines/'+'starting_years.shp')
    end = gpd.read_file(simulations_folder+model_name+'/'+'_pathlines/'+'ending_years.shp')
    end['VALUE1_start'] = start['VALUE1']
    # end[end['VALUE1_start']==-9999] = np.nan
    # end[end['VALUE1']<0] = 0
    end['rchPerc'] = end['VALUE1_start'] / recharge
    end['rchPerc'][end['rchPerc']<0] = 0
    end['time_winput'] = (end['time'])*end['rchPerc']
    end[end['time_winput']<=0] = np.nan
    ########################################## END WEIGHTED ##########################################
    
    
    masked = end.copy()
    masked = masked[masked.k <= 1] # ONLY OUT FIRST CELL
    masked = masked[masked.i0.astype(str)+'-'+masked.j0.astype(str)!=
                    masked.i.astype(str)+'-'+masked.j.astype(str)] # NOT IN AND OUT SAME CELL
    masked.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years_masked_withoutsiders.shp') # time in years !
    if not masked[masked['time_winput'] > 1000].empty:
        print('THERE IS CELL > 1000y')
        if len(masked[masked.time > 1000]) <= (len(masked)*0.05):
            print('DELETE > 1000y', str(len(masked[masked['time_winput'] > 1000]))+'/'+
                                    str((len(masked))))
            # IF ONLY 5% CELL ARE HIGHER THAN 1000 YEARS : MASKED (OUTLIERS):
            masked = masked[masked['time_winput'] <= 1000]
        else:
            print('NO CELL > 1000y')
    masked.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years_masked.shp') # time in years !
    keep_particules = masked.particleid
    keep_particules = keep_particules.tolist()
        
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

#%% PATHLINES MODELS

# VALID egu1_4_20.0-0.0-0.1359-0.8

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
    
    crs_code = 32620 # 2154
    
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
    
    path_obs = data_path+'targets_pathlines_points.shp'
    shp_obs = gpd.read_file(path_obs)
    shp_obs['geometry'] = shp_obs.geometry.buffer(75)
    shp_obs.to_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'targets_pathlines_points.shp', encoding='utf-8')
    
    masked = gpd.read_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years_masked.shp') # time in years !
    intersect = gpd.overlay(masked, shp_obs, how='intersection')
    
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

active_pathlines = True

for model_name in list_selects[:]:

    shp_starting = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'starting_years.shp')
    masked = shp_starting.copy()
    masked = masked[masked.k <= 1] # ONLY OUT FIRST CELL
    masked = masked[masked.i0.astype(str)+'-'+masked.j0.astype(str)!=
                    masked.i.astype(str)+'-'+masked.j.astype(str)] # NOT IN AND OUT SAME CELL
    masked.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'starting_years_filtered.shp') # time in years !
    shp_starting = masked.copy()
    
    shp_ending = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'ending_years.shp')
    masked = shp_ending.copy()
    masked = masked[masked.k <= 1] # ONLY OUT FIRST CELL
    masked = masked[masked.i0.astype(str)+'-'+masked.j0.astype(str)!=
                    masked.i.astype(str)+'-'+masked.j.astype(str)] # NOT IN AND OUT SAME CELL
    masked.to_file(simulations_folder+
                         model_name+'/'+'_pathlines/'+
                         'ending_years_filtered.shp') # time in years !
    shp_ending = masked.copy()

    if active_pathlines == True:

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
    
    cond_lay = 38 # ==> 38 approx. 40 meters more 50m, so 37
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
    
    if active_pathlines == True:

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

#%% KEEP PATHLINES INSIDE DEEP

shp_contour = gpd.read_file(BV.geographic.watershed_shp)

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name[:]

df_area = pd.DataFrame()

for i, model_name in enumerate(list_selects[:]):

    ######## KEEP PATHLINES DEEP @@@@@@@@@@@@@
    
    shp_starting_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_starting_deep.shp') # time in years !
    
    shp_ending_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    
    clip_shp_ending_deep = shp_ending_deep.clip(shp_contour)
    
    try:
        clip_shp_ending_deep.to_file(simulations_folder+
                                  model_name+'/'+'_pathlines/'+
                                  'shp_ending_deep_inside.shp')
    
        id_deep_inside = clip_shp_ending_deep.particleid
        
        shp_starting_deep_inside = shp_starting_deep[shp_starting_deep['particleid'].isin(id_deep_inside)]
        
        shp_starting_deep_inside.to_file(simulations_folder+
                                  model_name+'/'+'_pathlines/'+
                                  'shp_starting_deep_inside.shp')
    except:
        pass
    
    LEN = len(shp_starting_deep_inside)
    AREA = LEN * (5*5) # m2
    print(model_name, LEN, AREA, AREA/1e6)
    
    print('Create shapefile particules and pathlines')
    pthobj = flopy.utils.PathlineFile(simulations_folder+
                                      model_name+'/'+model_name+'.mppth')
    pth_data = pthobj.get_alldata()
    # pth_filt = pthobj.get_data(partid=7503)
    # The pthlines selected 7503 transformed by FloPy is the ID 7504
    # Pour un ID point de 7053, prendre la pathline 7504
    
    mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
    
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    grid_model = mf.modelgrid
    crs_code = 32620 # 2154

    for k in range(len(pth_data)):
        pth_data[k].time = pth_data[k].time / 365

    test = filter(lambda score: score.particleid[0] == id_deep_inside, pth_data)
    
    pth_data_save = []
    # for n_pts, i_pts in enumerate(id_deep_inside+1):
    for n_pts, i_pts in enumerate(id_deep_inside[:]):
        for n_pth, j_pth in enumerate(pth_data):
            if i_pts-1 == j_pth['particleid'][0]:
                print(i_pts-1, j_pth['particleid'][0], n_pts, len(id_deep_inside[:]))
                pth_data_save.append(j_pth)
    
    ### 1000 pathlines
    # print('1000 pathlines')
    # pthobj.write_shapefile(pathline_data=pth_data,
    #                         shpname=simulations_folder+
    #                                 model_name+'/'+'_pathlines/'+
    #                                 'test.shp',
    #                         one_per_particle=True, 
    #                         direction='ending',
    #                         mg=grid_model, epsg=crs_code, sr=None)
    
    pthobj.write_shapefile(pathline_data=pth_data_save,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'pathlines_deep_inside.shp',
                            one_per_particle=True, 
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    
    pthobj.write_shapefile(pathline_data=pth_data_save,
                            shpname=simulations_folder+
                                    model_name+'/'+'_pathlines/'+
                                    'particules_deep_inside.shp',
                            one_per_particle=False, 
                            direction='ending',
                            mg=grid_model, epsg=crs_code, sr=None)
    
    pathlines_deep_inside = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'pathlines_deep_inside.shp') # time in years !
    pathlines_deep_inside_filter = pathlines_deep_inside[pathlines_deep_inside.k<=1]
    pathlines_deep_inside_filter.to_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'pathlines_deep_inside_filter.shp')
    
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

#%% ---- CREATE RESULTS

#%% DISTRIBUTION OUTFLOW DRAIN

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

for model_name in list_selects[:]:
    
    with open(simulations_folder+
                      model_name+'/'+'_id_profon_superf.data', 'rb') as f:
        indices_layers = pickle.load(f)
    
    endobj = flopy.utils.EndpointFile(simulations_folder+
                                      model_name+'/'+model_name+'.mpend')
    e = endobj.get_alldata()
    
    ###########################################################################
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    bv = gpd.read_file(BV.geographic.watershed_shp)
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    contour = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    contour = np.ma.masked_where(contour <= 0, contour)
    streams = imageio.imread(stable_folder+'hydrology/'+'L_Quiock_creek2.tif')
    dem_path = BV.geographic.watershed_dem
    dem_im = imageio.imread(dem_path)
    dem_masked = np.ma.masked_where(dem_im < -100, dem_im)
    d8_path = stable_folder+'/geographic/watershed_buff_direc.tif'
    acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    outflow_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    wbt.downslope_flowpath_length(
        d8_path, 
        down_path, 
        watersheds=None, 
        weights=None, 
        esri_pntr=False)
    acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
    acc[acc<0] = np.nan
    down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)
    down[down<0] = np.nan
    out = np.ma.masked_array(imageio.imread(outflow_path), mask=dem_masked.mask)
    out[out<0] = np.nan
    
    wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                              'watertable_elevation_t(0).tif') 
    ###########################################################################
    
    acc_masked = np.ma.masked_where(acc <= acc.mean(), acc)
    down_masked = np.ma.masked_array(down, mask=acc_masked.mask)
    
    dist_riv = down.flatten()
    outflow_riv = out.flatten()
    accumul_riv = acc.flatten()
    
    wbt.raster_to_vector_polygons(
    simulations_folder+model_name+'/_watershed/_tifs/'+\
                              'watertable_elevation_t(0).tif',
    simulations_folder+model_name+'/'+'_watershed/_tifs/'+\
                              'outflow_drain_t(0).shp')
    
    outflow_riv_shp = gpd.read_file(simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).shp')
    
    shp_ending_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    
    shp_ending_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    
    resume = pd.DataFrame()    
    resume['distance_riv'] = dist_riv
    resume['outflow_riv'] = outflow_riv
    resume['accumul_riv'] = accumul_riv
    resume['FID'] = outflow_riv_shp.FID
    
    the_idx = resume['FID'].unique()

    pointInPoly_shal = gpd.sjoin(shp_ending_shal, outflow_riv_shp, op='within')
    pointInPoly_shal.crs = 'EPSG:32620'
    pointInPoly_deep = gpd.sjoin(shp_ending_deep, outflow_riv_shp, op='within')
    pointInPoly_deep.crs = 'EPSG:32620'

    join_shal = pointInPoly_shal.groupby(['FID']).agg(['max','count','nunique'])
    join_deep = pointInPoly_deep.groupby(['FID']).agg(['max','count','nunique'])
    join_shal.index = join_shal.index-1
    join_deep.index = join_deep.index-1
    
    resume['count_shal'] = join_shal.index_right['count']
    resume['count_deep'] = join_deep.index_right['count']
    resume['count_shal'] = resume['count_shal'].fillna(0)
    resume['count_deep'] = resume['count_deep'].fillna(0)

    # for i in the_idx:
    #     print(i, len(the_idx))
    #     # i = 97
    #     inter_shal = pointInPoly_shal[pointInPoly_shal.FID==i]
    #     resume.loc[resume['FID']==i,'count_shal'] = len(inter_shal)
    #     inter_deep = pointInPoly_deep[pointInPoly_deep.FID==i]
    #     resume.loc[resume['FID']==i,'count_deep'] = len(inter_deep)
    
    resume['count_total'] = resume['count_shal'] + resume['count_deep']
    
    resume = resume.dropna(subset=['distance_riv'])
    resume = resume.dropna(subset=['accumul_riv'])
    resume = resume[resume['accumul_riv']!=0]
    
    resume['Qriv_shal'] = ( resume['outflow_riv'] * resume['count_shal'] ) / resume['count_total']
    resume['Qriv_deep'] = ( resume['outflow_riv'] * resume['count_deep'] ) / resume['count_total']

    # resume['distance_riv'] = resume['distance_riv'] - resume['distance_riv'].min()
    
    resume.to_csv(BV.simulations_folder+'/'+model_name+'/resume.csv', sep=';')
    
#%% DISTRIBUTION GOOD FLUX

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

wt_shp = gpd.read_file(BV.geographic.watershed_shp)
direc = BV.geographic.watershed_direc

for model_name in list_selects[:]:
    
    with open(simulations_folder+
                      model_name+'/'+'_id_profon_superf.data', 'rb') as f:
        indices_layers = pickle.load(f)
    
    endobj = flopy.utils.EndpointFile(simulations_folder+
                                      model_name+'/'+model_name+'.mpend')
    e = endobj.get_alldata()
    
    ###########################################################################
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    bv = gpd.read_file(BV.geographic.watershed_shp)
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    contour = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    contour = np.ma.masked_where(contour <= 0, contour)
    streams = imageio.imread(stable_folder+'hydrology/'+'L_Quiock_creek2.tif')
    dem_path = BV.geographic.watershed_dem
    dem_im = imageio.imread(dem_path)
    dem_masked = np.ma.masked_where(dem_im < -100, dem_im)
    d8_path = stable_folder+'/geographic/watershed_buff_direc.tif'
    acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    outflow_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    wbt.downslope_flowpath_length(
        d8_path, 
        down_path, 
        watersheds=None, 
        weights=None, 
        esri_pntr=False)
    acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
    acc[acc<0] = np.nan
    down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)
    down[down<0] = np.nan
    out = np.ma.masked_array(imageio.imread(outflow_path), mask=dem_masked.mask)
    out[out<0] = np.nan
    
    wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                              'watertable_elevation_t(0).tif') 
    ###########################################################################
    
    wbt.raster_to_vector_points(
    acc_path, 
    simulations_folder+model_name+'/'+'_watershed/_tifs/'+\
                              'accumulation_flux_t(0).shp')
    
    # The raster
    
    acc_masked = np.ma.masked_where(BV.geographic.dem_clip <= 0, acc)
    acc_masked = np.ma.masked_where(acc_masked==0, acc_masked)
    the_mean = acc_masked.mean()
    acc_masked = np.ma.masked_where(acc_masked<the_mean, acc_masked)
    down_masked = np.ma.masked_array(down, mask=acc_masked.mask)
    
    dist_mask_riv = down_masked.flatten()
    accumul_mask_riv = acc_masked.flatten()
    
    resume_mask = pd.DataFrame()    
    resume_mask['distance_mask_riv'] = dist_mask_riv
    resume_mask['accumul_mask_riv'] = accumul_mask_riv
    resume_mask = resume_mask.dropna(subset=['distance_mask_riv'])
    resume_mask = resume_mask.dropna(subset=['accumul_mask_riv'])
    resume_mask = resume_mask[resume_mask['accumul_mask_riv']!=0]

    # The shp

    accumul_riv_shp = gpd.read_file(simulations_folder+model_name+'/'+'_watershed/_tifs/'+\
                              'accumulation_flux_t(0).shp')
    accumul_riv_shp = accumul_riv_shp.clip(wt_shp)
    accumul_riv_shp = accumul_riv_shp[accumul_riv_shp['VALUE']>0]
    accumul_riv_shp = accumul_riv_shp[accumul_riv_shp['VALUE']>=the_mean]
    
    accumul_riv_shp.plot(column='VALUE')

    accumul_riv_shp = accumul_riv_shp.sort_values('VALUE')
    resume_mask = resume_mask.sort_values('accumul_mask_riv')
    resume_mask['FID'] = accumul_riv_shp.FID.values
            
    shp_ending_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    
    shp_ending_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    
    for i, j in enumerate(resume_mask['FID'][:]):
        
        print(i, len(resume_mask))
        
        inter = accumul_riv_shp.iloc[i]
        X_val = inter.geometry.x
        Y_val = inter.geometry.y
                
        # BVs = watershed_root.Watershed(watershed_name=str(i),
        #                               dem_path='C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/regional/region_fill.tif', 
        #                               out_path='C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/_TEMPO/',
        #                               modflow_path=modflow_path,
        #                               library_path=library_path,
        #                               load=False,
        #                               from_xy=[X_val, Y_val, 0, 0],
        #                               from_shp=[],
        #                               from_dem=False,
        #                               cell_size=cell_size,
        #                               regio_out=True)
        
        crs = 'EPSG:32620'
        dfxy = pd.DataFrame({'x': [X_val], 'y': [Y_val]})
        gdf = gpd.GeoDataFrame(dfxy, geometry=gpd.points_from_xy(dfxy['x'], dfxy['y']), crs=crs)
        outlet_shp = simulations_folder+model_name+'/'+'_subbasins/'  + 'outlet.shp'
        gdf.to_file(outlet_shp)
        subwatershed_tif = simulations_folder+model_name+'/'+'_subbasins/' + str(i) + '.tif'
        wbt.watershed(direc, outlet_shp, subwatershed_tif, esri_pntr=False)
        subwatershed_shp = simulations_folder+model_name+'/'+'_subbasins/' + str(i) + '.shp'
        wbt.raster_to_vector_polygons(subwatershed_tif, subwatershed_shp)
        wbt.polygon_area(subwatershed_shp)
        
        sub_catch = gpd.read_file(simulations_folder+model_name+'/'+'_subbasins/' + str(i) + '.shp')
        sub_catch.crs = 'EPSG:32620'
        
        sub_shal = shp_ending_shal.clip(sub_catch)
        sub_deep = shp_ending_deep.clip(sub_catch)
        
        pointInPoly_shal = len(sub_shal)
        pointInPoly_deep = len(sub_deep)

        # resume_mask[resume_mask['FID']==j]['count_shal'] = pointInPoly_shal
        # resume_mask[resume_mask['FID']==j]['count_deep'] = pointInPoly_deep
        
        resume_mask.loc[resume_mask['FID']==j,'count_shal'] = pointInPoly_shal
        resume_mask.loc[resume_mask['FID']==j,'count_deep'] = pointInPoly_deep
    
    # resume = resume_mask.copy()
    
    resume_mask['count_total'] = resume_mask['count_shal'] + resume_mask['count_deep']
    
    resume_mask['Qriv_mask_shal'] = ( resume_mask['accumul_mask_riv'] * resume_mask['count_shal'] ) / resume_mask['count_total']
    resume_mask['Qriv_mask_deep'] = ( resume_mask['accumul_mask_riv'] * resume_mask['count_deep'] ) / resume_mask['count_total']
    
    # resume_mask['distance_mask_riv'] = resume_mask['distance_mask_riv'] - resume_mask['distance_mask_riv'].min()
    
    resume_mask.to_csv(BV.simulations_folder+'/'+model_name+'/resume_clean.csv', 
                       sep=';')

#%% ---- PLOTS

#%% 1 - PLOT GENERAL QGIS

model_name = list_model_name[0]

### SIG ###
dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
bv = gpd.read_file(BV.geographic.watershed_shp)
wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                           stable_folder+'geographic/'+'watershed_contour.tif',
                           base = stable_folder+'geographic/'+'watershed_dem.tif')
contour = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
contour = np.ma.masked_where(contour <= 0, contour)
streams = imageio.imread(stable_folder+'hydrology/'+'L_Quiock_creek2.tif')
dem_path = BV.geographic.watershed_dem
dem_im = imageio.imread(dem_path)
dem_masked = np.ma.masked_where(dem_im < -100, dem_im)
d8_path = stable_folder+'/geographic/watershed_buff_direc.tif'
acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
wbt.downslope_flowpath_length(
    d8_path, 
    down_path, 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)

wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                          'watertable_elevation_t(0).tif') 

xvalues = np.linspace(-1,1,dem_data.shape[1])
yvalues = np.linspace(-1,1,dem_data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues)

dem_max = dem_data.max()
dem_prof = dem_data.astype(float)
dem_prof[dem_prof<0] = np.nan
wt_prof = wt_data.astype(float)
wt_prof[wt_prof<0] = np.nan

fig_l, ax_l = plt.subplots(1, 1, figsize=(5,8))

for i, coord in enumerate([[60,55,140,35]]): # [90,90,140,35]
    cros = i

    x0, y0 = coord[0], coord[1] # These are in _pixel_ coordinates !
    x1, y1 = coord[2], coord[3]
    num = int(np.hypot(x1-x0, y1-y0))
    num = x1-x0
    # num=100
    x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
    zd = dem_data[y.astype(np.int), x.astype(np.int)]
    zw = wt_data[y.astype(np.int), x.astype(np.int)]
    
    dem_max = dem_data.max()
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
    
    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    
    ax_l.imshow(dem_plot, origin='lower', cmap='terrain', aspect="equal")
    ax_l.set_ylim(ax_l.get_ylim()[::-1])
    d_line = ax_l.plot((x0,x1),(y0,y1), 'k-', lw=3)
    # v_line = ax.axvline(cur_x, color='k', lw=2)
    # h_line = ax.axhline(cur_y, color='k', lw=2)

streams = imageio.imread(stable_folder+'hydrology/'+'L_Quiock_creek2.tif')
ax_l.imshow(np.ma.masked_where(streams<0, streams), cmap=mpl.colors.ListedColormap('navy'))
ax_l.imshow(contour, cmap=mpl.colors.ListedColormap('k'))
# ax_l.invert_yaxis()

#%% 2 - PLOT CHEMISTRY

colors = ['darkviolet','lightskyblue','navy']

field = pd.read_csv('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_data/Field_data.csv',
                    sep=';')
field['d_mouth'] = pd.to_numeric(field['d_mouth'])

fig, axs = plt.subplots(6,1, figsize=(4.5,12), sharex=True)
axs = axs.ravel()

data_root = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_data/'
samples = pd.read_csv(os.path.join(data_root, 'data_river.csv'), sep = ';', decimal=',', index_col = 0 , encoding = "ISO-8859-1")
samples['d_mouth'] = abs(samples['d_mouth'])
samples['Mg_Na'] = samples.apply(lambda x: x.Mg_ppm/x.Na_ppm/24.3*23, axis = 1)
samples['Ca_Na'] = samples.apply(lambda x: x.Ca_ppm/x.Na_ppm/40.1*23, axis = 1)
samples['Na_Sr'] = samples.apply(lambda x: x.Na_ppm/x.Sr_ppm/23*87, axis = 1)
ratio = pd.read_csv(os.path.join(data_root, 'data_ratio.csv'), sep = ';', decimal=',', index_col = 0 , encoding = "ISO-8859-1")
ratio2 = samples[['Mg_Na', 'Ca_Na', '87Sr_86Sr', 'Na_Sr', 'Date', 'Location']]
ratio3 = pd.concat([ratio2, ratio])
debit = pd.read_csv(os.path.join(data_root, 'data_flow.csv'), sep = ';', decimal=',', index_col = 0 , encoding = "ISO-8859-1")
debit['d_mouth'] = abs(debit['d_mouth'])

dem_data = imageio.imread(BV.geographic.watershed_dem)
dem_data[dem_data<0] = np.nan
thedem = pd.Series(np.nanmin(dem_data, axis=0))
thedem = thedem.to_frame()
thedem['x'] = thedem.index*5
thedem['xinv'] = thedem['x'].sort_values(ascending=False).reset_index(drop=True)
thedem.loc[0,0] = 325
thedem.loc[151,0] = 202
thedem = thedem.dropna()

ax = axs[0]
ax.plot(thedem['xinv'], thedem[0], c='saddlebrown', lw=2)
ax.set_ylabel('Elevation [m]')
ax.set_ylim(200,325)
ax.set_yticks([200, 225, 250, 275, 300, 325])
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[1]
data = samples[samples['Date']=='June 2016']
ax.plot(data["d_mouth"], data["Conductivity"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = samples[samples['Date']=='May 2019']
ax.plot(data["d_mouth"], data["Conductivity"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = samples[samples['Date']=='June 2019']
ax.plot(data["d_mouth"], data["Conductivity"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
# ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('EC [μS]')
ax.set(ylim=(0,120))
ax.invert_xaxis()
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[2]
data = debit[debit['Date']=='June 2016']
ax.plot(data["d_mouth"], data["Val"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = debit[debit['Date']=='May 2019']
ax.plot(data["d_mouth"], data["Val"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = debit[debit['Date']=='June 2019']
ax.plot(data["d_mouth"], data["Val"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
# ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('$Q_{obs}$ [L/s]')
data = debit[debit['Date']=='Average']
ax.plot(data["d_mouth"], data["Val"], marker='*', lw=0, ms=15, mew=1, c='white', label = 'June 2019')
ax.set(ylim=(0,10))
ax.invert_xaxis()
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[3]
data = samples[samples['Date']=='June 2016']
ax.plot(data["d_mouth"], data["Si_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = samples[samples['Date']=='May 2019']
ax.plot(data["d_mouth"], data["Si_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = samples[samples['Date']=='June 2019']
ax.plot(data["d_mouth"], data["Si_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
# ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('Si [ppm]')
ax.set(ylim=(0,15))
ax.invert_xaxis()
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[4]
data = samples[samples['Date']=='June 2016']
ax.plot(data["d_mouth"], data["Sr_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = samples[samples['Date']=='May 2019']
ax.plot(data["d_mouth"], data["Sr_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = samples[samples['Date']=='June 2019']
ax.plot(data["d_mouth"], data["Sr_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
# ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('Sr [ppm]')
ax.set(ylim=(0,0.030))
ax.invert_xaxis()
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[5]
data = samples[samples['Date']=='June 2016']
ax.plot(data["d_mouth"], data["87Sr_86Sr"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = samples[samples['Date']=='May 2019']
ax.plot(data["d_mouth"], data["87Sr_86Sr"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = samples[samples['Date']=='June 2019']
ax.plot(data["d_mouth"], data["87Sr_86Sr"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('$^{87}$Sr/$^{86}$Sr [-]')
ax.set_ylim(0.705, 0.710)
ax.ticklabel_format(style='plain')
ax.ticklabel_format(useOffset=False, style='plain')
ax.invert_xaxis()
ax.set_xlim(750,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/'+
            'CHEMISTRY.png', dpi=300, bbox_inches='tight')

#%% 2 - PLOT CHEMISTRY - UP

colors = ['darkviolet','lightskyblue','navy']

field = pd.read_csv('C:/Users/ronan/OneDrive/UNINE/11_Paper/QUIOCK/_data/Field_data.csv',
                    sep=';')
field['d_mouth'] = pd.to_numeric(field['d_mouth'])

fig, axs = plt.subplots(6,1, figsize=(4.5,12), sharex=True)
axs = axs.ravel()

data_root = 'C:/Users/ronan/OneDrive/UNINE/11_Paper/QUIOCK/_data/'
samples = pd.read_csv(os.path.join(data_root, 'data_river_uM_2024.csv'), sep = ';', decimal=',', index_col = 0 , encoding = "ISO-8859-1")
samples['d_mouth'] = abs(samples['d_mouth'])
samples['Mg_Na'] = samples.apply(lambda x: x['Mg_uM']/x['Mg_uM']/24.3*23, axis = 1)
samples['Ca_Na'] = samples.apply(lambda x: x['Ca_uM']/x['Na_uM']/40.1*23, axis = 1)
samples['Na_Sr'] = samples.apply(lambda x: x['Na_uM']/x['Sr_ppb']/23*87, axis = 1)
ratio = pd.read_csv(os.path.join(data_root, 'data_ratio.csv'), sep = ';', decimal=',', index_col = 0 , encoding = "ISO-8859-1")
ratio2 = samples[['Mg_Na', 'Ca_Na', '87Sr_86Sr', 'Na_Sr', 'Date', 'Location']]
ratio3 = pd.concat([ratio2, ratio])
debit = pd.read_csv(os.path.join(data_root, 'data_flow.csv'), sep = ';', decimal=',', index_col = 0 , encoding = "ISO-8859-1")
debit['d_mouth'] = abs(debit['d_mouth'])

dem_data = imageio.imread(BV.geographic.watershed_dem)
dem_data[dem_data<0] = np.nan
thedem = pd.Series(np.nanmin(dem_data, axis=0))
thedem = thedem.to_frame()
thedem['x'] = thedem.index*5
thedem['xinv'] = thedem['x'].sort_values(ascending=False).reset_index(drop=True)
thedem.loc[0,0] = 325
thedem.loc[151,0] = 202
thedem = thedem.dropna()

ax = axs[0]
ax.plot(thedem['xinv'], thedem[0], c='saddlebrown', lw=2)
ax.set_ylabel('Elevation [m]')
ax.set_ylim(200,325)
ax.set_yticks([200, 225, 250, 275, 300, 325])
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[1]
data = samples[samples['Date']=='June 2016']
ax.plot(data["d_mouth"], data["Conductivity"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = samples[samples['Date']=='May 2019']
ax.plot(data["d_mouth"], data["Conductivity"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = samples[samples['Date']=='June 2019']
ax.plot(data["d_mouth"], data["Conductivity"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
# ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('EC [μS]')
ax.set(ylim=(0,120))
ax.invert_xaxis()
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[2]
data = debit[debit['Date']=='June 2016']
ax.plot(data["d_mouth"], data["Val"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = debit[debit['Date']=='May 2019']
ax.plot(data["d_mouth"], data["Val"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = debit[debit['Date']=='June 2019']
ax.plot(data["d_mouth"], data["Val"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
# ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('$Q_{obs}$ [L/s]')
data = debit[debit['Date']=='Average']
ax.plot(data["d_mouth"], data["Val"], marker='*', lw=0, ms=15, mew=1, c='white', label = 'June 2019')
ax.set(ylim=(0,10))
ax.invert_xaxis()
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[3]
data = samples[samples['Date']=='June 2016']
ax.plot(data["d_mouth"], data["Si_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = samples[samples['Date']=='May 2019']
ax.plot(data["d_mouth"], data["Si_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = samples[samples['Date']=='June 2019']
ax.plot(data["d_mouth"], data["Si_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
# ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('Si [ppm]')
ax.set(ylim=(0,15))
ax.invert_xaxis()
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[4]
data = samples[samples['Date']=='June 2016']
ax.plot(data["d_mouth"], data["Sr_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = samples[samples['Date']=='May 2019']
ax.plot(data["d_mouth"], data["Sr_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = samples[samples['Date']=='June 2019']
ax.plot(data["d_mouth"], data["Sr_ppm"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
# ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('Sr [ppm]')
ax.set(ylim=(0,0.030))
ax.invert_xaxis()
# ax.set_xlim(800,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

# fig, ax = plt.subplots(1,1, figsize=(5.5,3))
ax = axs[5]
data = samples[samples['Date']=='June 2016']
ax.plot(data["d_mouth"], data["87Sr_86Sr"], marker='o', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = samples[samples['Date']=='May 2019']
ax.plot(data["d_mouth"], data["87Sr_86Sr"], marker='o', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2016')
data = samples[samples['Date']=='June 2019']
ax.plot(data["d_mouth"], data["87Sr_86Sr"], marker='o', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')
ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('$^{87}$Sr/$^{86}$Sr [-]')
ax.set_ylim(0.705, 0.710)
ax.ticklabel_format(style='plain')
ax.ticklabel_format(useOffset=False, style='plain')
ax.invert_xaxis()
ax.set_xlim(750,-20)
ax.axvspan(xmin=250, xmax=150, color='grey', alpha=0.2, zorder=-10)
ax.axvline(250, c='k', ls='--', zorder=-10)
ax.axvline(150, c='k', ls='--', zorder=-10)
# ax.grid()

fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/'+
            'CHEMISTRY.png', dpi=300, bbox_inches='tight')

#%% 3 - PLOT MIXING

colors = ['darkviolet','lightskyblue','navy']

fig, axs = plt.subplots(1,2, figsize=(7.5,3.5), 
                        # sharex=True, sharey=True
                        )
axs = axs.ravel()

ax = axs[0]

data = ratio3[(ratio3['Date']=='June 2016') & (ratio3['Location']=='Upstream')]
ax.plot(data["Ca_Na"], data["Mg_Na"], marker='^', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = ratio3[(ratio3['Date']=='May 2019') & (ratio3['Location']=='Upstream')]
ax.plot(data["Ca_Na"], data["Mg_Na"], marker='^', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2019')
data = ratio3[(ratio3['Date']=='June 2019') & (ratio3['Location']=='Upstream')]
ax.plot(data["Ca_Na"], data["Mg_Na"], marker='^', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')

data = ratio3[(ratio3['Date']=='June 2016') & (ratio3['Location']=='Downstream')]
ax.plot(data["Ca_Na"], data["Mg_Na"], marker='v', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = ratio3[(ratio3['Date']=='May 2019') & (ratio3['Location']=='Downstream')]
ax.plot(data["Ca_Na"], data["Mg_Na"], marker='v', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2019')
data = ratio3[(ratio3['Date']=='June 2019') & (ratio3['Location']=='Downstream')]
ax.plot(data["Ca_Na"], data["Mg_Na"], marker='v', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')

ax.plot(ratio3.at['Seawater',"Ca_Na"], ratio3.at['Seawater',"Mg_Na"], 
        marker='X', lw=0, ms=10, mew=1, c='white', 
        label = 'Seawater')
ax.plot(ratio3.at['Rainfall',"Ca_Na"], ratio3.at['Rainfall',"Mg_Na"], 
        marker='X', lw=0, ms=10, mew=1, c='yellow', 
        label = 'Rainfall')
ax.plot(ratio3.at['Silicates',"Ca_Na"], ratio3.at['Silicates',"Mg_Na"], 
        marker='X', lw=0, ms=10, mew=1, c='darkorange', 
        label = 'Silicates')
ax.plot(ratio3.at['Volcanic Rock',"Ca_Na"], ratio3.at['Volcanic Rock',"Mg_Na"], 
        marker='X', lw=0, ms=10, mew=1, c='red', 
        label = 'Volcanic Rock')

ax.set_xlim(0,0.40)
ax.set_xticks([0,0.1,0.2,0.3,0.40])
ax.set_ylim(0.1,0.25)
ax.set_yticks([0.1,0.15,0.2,0.25])
ax.plot([0.025,0.35], [0.11,0.24], linestyle='--', c='grey', lw=1.5, zorder=-2)

ax.set_xlabel('Ca / Na [-]')
ax.set_ylabel('Mg / Na [-]')

ax = axs[1]

data = ratio3[(ratio3['Date']=='June 2016') & (ratio3['Location']=='Upstream')]
ax.plot(data["Na_Sr"], data["87Sr_86Sr"], marker='^', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = ratio3[(ratio3['Date']=='May 2019') & (ratio3['Location']=='Upstream')]
ax.plot(data["Na_Sr"], data["87Sr_86Sr"], marker='^', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2019')
data = ratio3[(ratio3['Date']=='June 2019') & (ratio3['Location']=='Upstream')]
ax.plot(data["Na_Sr"], data["87Sr_86Sr"], marker='^', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')

data = ratio3[(ratio3['Date']=='June 2016') & (ratio3['Location']=='Downstream')]
ax.plot(data["Na_Sr"], data["87Sr_86Sr"], marker='v', lw=0, ms=8, mew=1, c=colors[1], label = 'June 2016')
data = ratio3[(ratio3['Date']=='May 2019') & (ratio3['Location']=='Downstream')]
ax.plot(data["Na_Sr"], data["87Sr_86Sr"], marker='v', lw=0, ms=8, mew=1, c=colors[0], label = 'May 2019')
data = ratio3[(ratio3['Date']=='June 2019') & (ratio3['Location']=='Downstream')]
ax.plot(data["Na_Sr"], data["87Sr_86Sr"], marker='v', lw=0, ms=8, mew=1, c=colors[2], label = 'June 2019')

ax.plot(ratio3.at['Seawater',"Na_Sr"], ratio3.at['Seawater',"87Sr_86Sr"], 
        marker='X', lw=0, ms=10, mew=1, c='white', 
        label = 'Seawater')
ax.plot(ratio3.at['Rainfall',"Na_Sr"], ratio3.at['Rainfall',"87Sr_86Sr"], 
        marker='X', lw=0, ms=10, mew=1, c='yellow', 
        label = 'Rainfall')
ax.plot(ratio3.at['Silicates',"Na_Sr"], ratio3.at['Silicates',"87Sr_86Sr"], 
        marker='X', lw=0, ms=10, mew=1, c='darkorange', 
        label = 'Silicates')
ax.plot(ratio3.at['Volcanic Rock',"Na_Sr"], ratio3.at['Volcanic Rock',"87Sr_86Sr"], 
        marker='X', lw=0, ms=10, mew=1, c='red', 
        label = 'Volcanic Rock')

ax.set_ylim(0.703, 0.710)
ax.set_yticks([0.703,0.705,0.707,0.709])
ax.ticklabel_format(style='plain')
ax.ticklabel_format(useOffset=False, style='plain')

ax.set_xlim(-200,7000)
ax.set_xticks([0,2000,4000,6000])
# ax.set_ylim(0.1,0.25)
# ax.plot([0.025,0.35], [0.11,0.24], linestyle='--', c='grey', lw=1.5, zorder=-2)

ax.plot([200,4800], [0.704,0.7095], linestyle='--', c='grey', lw=1.5, zorder=-2)

ax.set_xlabel('Na / Sr [-]')
ax.set_ylabel('$^{87}$Sr/$^{86}$Sr [-]')

plt.tight_layout()

fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/'+
            'MIXING.png', dpi=300, bbox_inches='tight')

#%% 5 - PLOT MAPS (OR QGIS)

dem = rasterio.open("C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_box_buff_dem.tif")

list_selects = list_model_name

shp_contour = gpd.read_file(BV.geographic.watershed_shp)
shp_box = gpd.read_file(stable_folder+'geographic/box_buff.shp')
stre = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2.shp')

wt_mask = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/watershed_mask.shp')
subwt_flow = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/subbasin/subbasin_Flowrate/watershed_contour.shp')
subwt_point = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/snap_flowrate.shp')

for model_name in list_selects[:]:
    
    # shp_ending = gpd.read_file(simulations_folder+
    #                               model_name+'/'+'_pathlines/'+
    #                               'ending_years_masked.shp') # time in years !
    
    # shp_starting_shal = gpd.read_file(simulations_folder+
    #                           model_name+'/'+'_pathlines/'+
    #                           'shp_starting_shal.shp') # time in years !
    
    shp_starting_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_starting_deep.shp') # time in years !
    
    shp_ending_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    
    shp_ending_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    
    shp_pathlines_1000 = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'pathlines_1000.shp') # time in years !
    
    fig, ax = plt.subplots(1,1, figsize=(5,5))
    
    mnt = rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.5, zorder=0, aspect="auto",
                              vmin=200, vmax=300)
    
    shp_contour.plot(ax=ax, facecolor='none', lw=1.5, zorder=1000)
    # subwt_flow.plot(ax=ax, facecolor='none', lw=1, ls=':', edgecolor='k', zorder=1000)
    # subwt_point.plot(ax=ax, facecolor='white',  edgecolor='k', marker='s', lw=1, markersize=10, zorder=1001)
    
    stre.plot(ax=ax, color='blue', lw=1, zorder=-1)
    shp_box.plot(ax=ax, facecolor='none', lw=1, zorder=10)
    # ax.set_title('Pathlines deep vs. shallow', fontsize=10)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')
    
    shp_ending_shal[shp_ending_shal.time>0].plot(ax=ax, color='dodgerblue', lw=0, markersize=2)
    
    shp_ending_deep.plot(ax=ax, color='red', lw=0, markersize=2)
    
    
    try:
        # shp_starting_shal.plot(ax=ax, color='dodgerblue', lw=0, markersize=4)
        shp_starting_deep_inside = gpd.read_file(simulations_folder+
                                  model_name+'/'+'_pathlines/'+
                                  'shp_starting_deep_inside.shp')
        # shp_starting_deep_inside = shp_starting_deep[shp_starting_deep['particleid'].isin(id_deep_inside)]
        shp_starting_deep_inside.plot(ax=ax, color='gold', lw=0, markersize=2)
        id_deep_inside = shp_starting_deep_inside['particleid']
    except:
        pass     
    """
    shp_pathlines_1000_clip = shp_pathlines_1000[shp_pathlines_1000['particleid'].isin(id_deep_inside)]
    
    shp_pathlines_1000_clip = shp_pathlines_1000_clip.sample(n = 50, replace=True)
    shp_pathlines_1000_clip = shp_pathlines_1000_clip.sample(n = 20, replace=True)
    shp_pathlines_1000_clip.plot(ax=ax, column='time',
                                 cmap=mpl.colors.ListedColormap('darkorange'), 
                                 lw=0.5,
                              norm=mpl.colors.LogNorm(vmin=1, vmax=100))
    """
    
    wt_mask.plot(ax=ax, color='white', alpha=0.75)
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')
    
    ax.set_title(model_name, fontsize=8)

    # fig.savefig(fig_path+'PLOT CLEAN MAPS'+'_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/maps_sensitivity/'+
                'PLOT CLEAN MAPS'+'_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
#%% 5 - PLOT Q SR RTD BEST

list_selects = list_model_name

data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')

dem = rasterio.open("C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_box_buff_dem.tif")
dem_data = imageio.imread("C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem.tif")
dem_data[dem_data<0] = np.nan
shp_contour = gpd.read_file("C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed.shp")
shp_box = gpd.read_file(stable_folder+'geographic/box_buff.shp')
stre = gpd.read_file('C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2.shp')
wt_mask = gpd.read_file('C:/Users/ronan/SIMULATIONS/GUADELOUPE/watershed_mask.shp')
# subwt_flow = gpd.read_file('C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/subbasin/subbasin_Flowrate/watershed_contour.shp')
subwt_point = gpd.read_file('C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/snap_flowrate.shp')
wbt.raster_to_vector_points(BV.geographic.watershed_dem, 
                            'C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp')
wbt.extract_raster_values_at_points(down_path, 
                                    'C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp')
dem_down = gpd.read_file('C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp')
wbt.extract_raster_values_at_points('C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_box_buff_dem.tif', 
                                    'C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp')
wbt.extract_raster_values_at_points(down_path, 
                                    'C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp')
riv_pts = gpd.read_file('C:/Users/ronan/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp')

field = pd.read_csv('C:/Users/ronan/OneDrive/UNINE/11_Paper/QUIOCK/_data/Field_data.csv',
                    sep=';')
field['d_mouth'] = pd.to_numeric(field['d_mouth'])
field = field.dropna(subset=['Name']) 
field = field.dropna(subset=['d_mouth'])
field_filter = field[field['Date']!='May 2019']
field_filter = field_filter.dropna(subset=['Name']) 
field_filter = field_filter.dropna(subset=['d_mouth'])
field_filter = field_filter.sort_values('d_mouth')
field_filter = field_filter.reset_index()
field_filter.loc[1,'d_mouth'] = 10
field_filter.loc[2,'d_mouth'] = 20
field_filter['d_mouth'] = field_filter ['d_mouth'].astype(int)
field_filter.loc[12,'d_mouth'] = 472
field_filter.loc[13,'d_mouth'] = 475


field = pd.read_csv(os.path.join(data_root, 'data_river_uM_2024.csv'), sep = ';', decimal=',', index_col = 0 , encoding = "ISO-8859-1")
field = field.reset_index()
field['d_mouth'] = abs(field['d_mouth'])
field = field.dropna(subset=['Name']) 
field = field.dropna(subset=['d_mouth'])
field_filter = field[field['Date']!='May 2019']
field_filter = field_filter.dropna(subset=['Name']) 
field_filter = field_filter.dropna(subset=['d_mouth'])
field_filter = field_filter.sort_values('d_mouth')
field_filter = field_filter.reset_index()
field_filter.loc[1,'d_mouth'] = 10
field_filter.loc[2,'d_mouth'] = 20
field_filter['d_mouth'] = field_filter ['d_mouth'].astype(int)
field_filter.loc[12,'d_mouth'] = 472
field_filter.loc[13,'d_mouth'] = 475

for model_name in list_selects[1:2]:
    
    cpt = int(model_name.split('_')[1]) - 1
    
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    wbt.extract_raster_values_at_points(down_path, 
                                        simulations_folder+model_name+'/'+'_pathlines/'+'shp_ending_shal.shp', 
                                        out_text=False)
    wbt.extract_raster_values_at_points(down_path, 
                                        simulations_folder+model_name+'/'+'_pathlines/'+'shp_ending_deep.shp', 
                                        out_text=False)
    
    shp_ending_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    shp_ending_shal = shp_ending_shal[shp_ending_shal['VALUE1']>0]
    shp_ending_shal = shp_ending_shal.clip(shp_contour)
    
    shp_ending_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    shp_ending_deep = shp_ending_deep[shp_ending_deep['VALUE1']>0]
    shp_ending_deep = shp_ending_deep.clip(shp_contour)
    
    resume_mask = pd.read_csv(BV.simulations_folder+'/'+model_name+'/resume_clean.csv',
                         sep=';')
    
    # print(resume_mask['distance_mask_riv'].min())
    the_proj_max = shp_ending_shal['VALUE1'].max()
    the_proj_min = resume_mask['distance_mask_riv'].min()
    resume_mask['distance_mask_riv'] = resume_mask['distance_mask_riv'] - the_proj_min
    
    resume_mask['accumul_mask_riv_new'] = np.nan
    resume_mask['Qriv_mask_shal_new'] = np.nan
    
    fig, axs = plt.subplots(2,1, figsize=(6.5,5.5), sharex=True)
    
    # fig, ax = plt.subplots(1,1, figsize=(6.5,3.5))
    
    ax = axs[0]
    axb = ax.twinx()
    
    resume_mask['accumul_mask_riv_new'] = resume_mask['accumul_mask_riv']
    resume_mask['accumul_mask_riv_new'][resume_mask['accumul_mask_riv_new']* 1000 / 3600 / 24<1.1] = np.nan
    resume_mask.loc[0,'accumul_mask_riv_new'] = resume_mask['accumul_mask_riv'].min()
    masked_acc = resume_mask.dropna(subset=['accumul_mask_riv_new'])
    masked_acc.loc[-1, 'accumul_mask_riv_new'] = 0
    masked_acc.loc[-1, 'distance_mask_riv'] = the_proj_max - the_proj_min
    masked_acc = masked_acc.reset_index()
    masked_acc = masked_acc.sort_values('distance_mask_riv')
    resume_mask['Qriv_mask_shal_new'] = resume_mask['Qriv_mask_shal']
    resume_mask['Qriv_mask_shal_new'][resume_mask['Qriv_mask_shal_new']* 1000 / 3600 / 24<1.1] = np.nan
    resume_mask.loc[0,'Qriv_mask_shal_new'] = resume_mask['Qriv_mask_shal'].min()
    masked_shal = resume_mask.dropna(subset=['Qriv_mask_shal_new'])
    masked_shal.loc[-1, 'Qriv_mask_shal_new'] = 0
    masked_shal.loc[-1, 'distance_mask_riv'] = the_proj_max - the_proj_min
    masked_shal = masked_shal.reset_index()
    masked_shal = masked_shal.sort_values('distance_mask_riv')
    
    if model_name == 'nearest1_2_10.0-150.0-300_50':
        ax.plot(masked_acc['distance_mask_riv'], masked_acc['accumul_mask_riv_new']* 1000 / 3600 / 24,
                color='k', lw=5, marker='_', ms=0)
        ax.plot(masked_shal['distance_mask_riv'], masked_shal['Qriv_mask_shal_new']* 1000 / 3600 / 24,
                color='dodgerblue', lw=3, marker='_', ms=0)
        ax.plot(resume_mask['distance_mask_riv'][resume_mask['Qriv_mask_deep']>0],
                resume_mask['Qriv_mask_deep'][resume_mask['Qriv_mask_deep']>0]* 1000 / 3600 / 24,
                color='red', lw=3, marker='_', ms=0)
    else:
        masked_acc = masked_acc.dropna(subset=['accumul_mask_riv_new'])
        masked_shal = masked_shal.dropna(subset=['Qriv_mask_shal_new'])
        resume_mask = resume_mask.dropna(subset=['Qriv_mask_deep'])
        ax.plot(masked_acc['distance_mask_riv'], masked_acc['accumul_mask_riv_new']* 1000 / 3600 / 24,
                color='k', lw=0, marker='_', mew=5, ms=5)
        ax.plot(masked_shal['distance_mask_riv'], masked_shal['Qriv_mask_shal_new']* 1000 / 3600 / 24,
                color='darkblue', lw=0, marker='_', mew=3, ms=5)
        ax.plot(resume_mask['distance_mask_riv'][resume_mask['Qriv_mask_deep']>0],
                resume_mask['Qriv_mask_deep'][resume_mask['Qriv_mask_deep']>0]* 1000 / 3600 / 24,
                color='darkred', lw=0, marker='_', mew=3, ms=5)

    ax.set_xlim(-20,750)
    ax.set_ylim(0,10)
    if model_name != 'nearest1_2_10.0-150.0-300_50':
        ax.set_ylim(1,10)
    # ax.set_xlabel('Distance to outlet [m]')
    # ax.set_ylabel('$Q_{sim}$ [L/s]')
    ax.set_ylabel('Q [L/s]')
    ax.set_title(model_name, fontsize=8)
    
    ax.plot(450, 3.1, lw=2, marker='*', color='white', ms=15, mew=2, markeredgecolor='k')
    
    # ax.scatter(shp_ending_shal['VALUE1'],shp_ending_shal['time'])
    # ax.scatter(shp_ending_deepl['VALUE1'],shp_ending_deepl['time'])
    
    # axb.vlines(x=shp_ending_shal['VALUE1']-83.28427-20,
    #           ymin=shp_ending_shal['time']*0,
    #           ymax=shp_ending_shal['time'], color='dodgerblue', lw=0.25)
    # axb.vlines(x=shp_ending_deep['VALUE1']-83.28427-20,
    #           ymin=shp_ending_deep['time']*0,
    #           ymax=shp_ending_deep['time'], color='red', lw=0.25)

    # axb.vlines(x=(shp_ending_shal['VALUE1']*masked_acc['distance_mask_riv'].max())/shp_ending_shal['VALUE1'].max(),
    #           ymin=shp_ending_shal['time']*0,
    #           ymax=shp_ending_shal['time'], color='dodgerblue', lw=0.25)
    # axb.vlines(x=(shp_ending_deep['VALUE1']*masked_acc['distance_mask_riv'].max())/shp_ending_shal['VALUE1'].max(),
    #           ymin=shp_ending_deep['time']*0,
    #           ymax=shp_ending_deep['time'], color='red', lw=0.25)

    shp_ending_shal['VALUE1'] = shp_ending_shal['VALUE1'] - the_proj_min # shp_ending_shal['VALUE1'].min()
    shp_ending_deep['VALUE1'] = shp_ending_deep['VALUE1'] - the_proj_min # shp_ending_deep['VALUE1'].min()

    axb.vlines(x=shp_ending_shal['VALUE1'],
              ymin=shp_ending_shal['time']*0,
              ymax=shp_ending_shal['time']/2, color='dodgerblue', lw=0.25)
    axb.vlines(x=shp_ending_deep['VALUE1'],
              ymin=shp_ending_deep['time']*0,
              ymax=shp_ending_deep['time']/2, color='red', lw=0.25)

    # # cb = fig.colorbar(s)
    # # cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)
    axb.set_ylim(0.1,1000)
    axb.set_yscale('log')
    axb.set_ylabel('t [y]', rotation= 270, labelpad=40)
    
    ax.invert_xaxis()
    ax.patch.set_visible(False)
    ax.set_zorder(axb.get_zorder()+1)
    
    ax = axs[1]
    
    Srp = 4.5
    Srr = 150     # 110
    RSrp = 0.7092
    RSrr = 0.7038 # 0.7041
    
    resume_mask = pd.read_csv(BV.simulations_folder+'/'+model_name+'/resume_clean.csv',
                         sep=';')
    
    # print(resume_mask['distance_mask_riv'].min())
    resume_mask['distance_mask_riv'] = resume_mask['distance_mask_riv'] - resume_mask['distance_mask_riv'].min()

    resume_mask.loc[-1, 'Csr_riv_calc'] = Srp
    resume_mask.loc[-1, 'Rsr_riv_calc'] = RSrp
    resume_mask.loc[-1, 'accumul_mask_riv'] = 0
    resume_mask.loc[-1, 'Qriv_mask_shal'] = 0
    resume_mask.loc[-1, 'Qriv_mask_deep'] = 0
    resume_mask.loc[-1, 'distance_mask_riv'] = the_proj_max - the_proj_min
    resume_mask = resume_mask.sort_values('distance_mask_riv', ascending=False)
    resume_mask = resume_mask.reset_index()

    resume_mask['Csr_riv_calc'] = ''
    resume_mask['Rsr_riv_calc'] = ''

    for i in resume_mask.index:
        if i == 0:
            resume_mask.loc[i,'Csr_riv_calc'] = Srp
            resume_mask.loc[i,'Rsr_riv_calc'] = RSrp
        else:
            resume_mask.loc[i,'Csr_riv_calc'] = ( resume_mask.loc[i-1,'Csr_riv_calc']*resume_mask.loc[i-1,'accumul_mask_riv'] + \
                                                  Srr*(resume_mask.loc[i,'Qriv_mask_deep']-resume_mask.loc[i-1,'Qriv_mask_deep']) + \
                                                  Srp*(resume_mask.loc[i,'Qriv_mask_shal']-resume_mask.loc[i-1,'Qriv_mask_shal']) ) / \
                                                  resume_mask.loc[i,'accumul_mask_riv']
                                             
            resume_mask.loc[i,'Rsr_riv_calc'] = ( resume_mask.loc[i-1,'Rsr_riv_calc']*resume_mask.loc[i-1,'Csr_riv_calc']*resume_mask.loc[i-1,'accumul_mask_riv'] + \
                                                  RSrr*Srr*(resume_mask.loc[i,'Qriv_mask_deep']-resume_mask.loc[i-1,'Qriv_mask_deep']) + \
                                                  RSrp*Srp*(resume_mask.loc[i,'Qriv_mask_shal']-resume_mask.loc[i-1,'Qriv_mask_shal']) ) / \
                                                  (resume_mask.loc[i,'accumul_mask_riv']*resume_mask.loc[i,'Csr_riv_calc'])

    # fig, ax = plt.subplots(1,1, figsize=(6.5,3.5))
    axb = ax.twinx()
    # s = ax.scatter(resume_mask['distance_mask_riv'],
    #                resume_mask['accumul_mask_riv'] * 1000 / 3600 / 24,
    #                marker='_', lw=3, c='k',
    #                 s=10,
    #                 # norm=matplotlib.colors.LogNorm()
    #                 )
    # sb = axb.bar(resume['distance_riv'],
    #              resume['Qriv_shal'] * 1000 / 3600 / 24,
    #              width=5, lw=0, color='dodgerblue', zorder=-1)
    # sb = axb.bar(resume['distance_riv'],
    #              resume['Qriv_deep'] * 1000 / 3600 / 24,
    #              width=5, lw=0, color='red', zorder=-1)
    s = ax.plot(resume_mask['distance_mask_riv'],
                   resume_mask['Csr_riv_calc'],
                   marker='|', ms=0, lw=3, c='darkorange',
                    # s=10,
                    # norm=matplotlib.colors.LogNorm()
                    zorder=-10
                    )
    s = axb.plot(resume_mask['distance_mask_riv'],
                   resume_mask['Rsr_riv_calc'],
                   marker='|', ms=0, lw=3, c='forestgreen',
                    # s=10,
                    # norm=matplotlib.colors.LogNorm()
                    zorder=-10
                    )
    ax.set_xlim(-20,750)
    ax.set_xlabel('Distance to outlet [m]')
    ax.set_ylabel('Sr [ppb]', c='darkorange')
    # ax.axvline(x=130, c='dimgray', ls=':', lw=3)
    axb.set_ylabel('$^{87}$Sr/$^{86}$Sr [-]', rotation=270, labelpad = 40, color='forestgreen')
    ax.set_ylim(0.003*1000, 0.013*1000)
    ax.set_yticks(np.array([0.004, 0.006, 0.008, 0.010, 0.012])*1000)
    axb.set_ylim(0.705, 0.710)
    axb.ticklabel_format(style='plain')
    axb.ticklabel_format(useOffset=False, style='plain')
    ax.set_title(model_name, fontsize=8)
    ax.invert_xaxis()
    ax.patch.set_visible(False)
    ax.set_zorder(axb.get_zorder()+1)
    
    """
    samp = field_filter[field_filter['Date']=='June 2016']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[1],
                   facecolor='forestgreen',
                   marker='<', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppb'],
                   # facecolor=colors[1],
                   facecolor='darkorange',
                   marker='<', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )
    """
    
    """
    samp = field[field['Date']=='May 2019']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[0],
                   facecolor='forestgreen',
                   marker='^', lw=0.5,
                    s=20,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppm'],
                   # facecolor=colors[0],
                   facecolor='darkorange',
                   marker='^', lw=0.5,
                    s=20,
                    # norm=matplotlib.colors.LogNorm()
                    )
    """
    
    samp = field_filter[field_filter['Date']=='June 2019']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[2],
                   facecolor='forestgreen',
                   marker='>', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppb'],
                   # facecolor=colors[2],
                   facecolor='darkorange',
                   marker='>', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )
    # field_filter = field[field['Date']!='May 2019']
    # field_filter = field_filter.dropna(subset=['Name']) 
    # field_filter = field_filter.dropna(subset=['d_mouth'])
    # field_filter = field_filter.sort_values('d_mouth')
    # field_filter = field_filter.reset_index()
    # field_filter.loc[1,'d_mouth'] = 10
    # field_filter.loc[2,'d_mouth'] = 20
    # field_filter['d_mouth'] = field_filter ['d_mouth'].astype(int)
    # field_filter.loc[13,'d_mouth'] = 471
    # field_filter.loc[13,'d_mouth'] = 472
        
    for ix, dm in zip(field_filter.index, field_filter.d_mouth):
        index = np.argmin(np.abs(resume_mask['distance_mask_riv']-dm))
        # print(index)
        resume_mask.loc[index,'SrR_obs'] = field_filter.loc[ix,'87Sr_86Sr']
        resume_mask.loc[index,'SrC_obs'] = field_filter.loc[ix,'Sr_ppb']
    
    resume_mask_dropna = resume_mask.dropna(subset=['SrR_obs'])
    # resume_mask_dropna = resume_mask.copy()
    
    the_diff = resume_mask_dropna['Rsr_riv_calc'] - resume_mask_dropna['SrR_obs']
    value=np.sqrt(np.sum((the_diff)**2)/len(resume_mask_dropna))
    if value == 0:
        value = np.nan
    print(value)
    data_explo.loc[cpt,'RMSE_R'] = value
    
    the_diff = resume_mask_dropna['Csr_riv_calc']/1000 - resume_mask_dropna['SrC_obs']
    value=np.sqrt(np.sum((the_diff)**2)/len(resume_mask_dropna))
    if value == 0:
        value = np.nan
    print(value)
    data_explo.loc[cpt,'RMSE_C'] = value
    
    # fig.savefig(fig_path+'PLOT CLEAN RTD'+'_'+model_name+'.png', dpi=300, bbox_inches='tight')

    # fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/best/'+
    #             'Q_RTD_SR.png', dpi=300, bbox_inches='tight')
    
    # fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/maps_sensitivity/'+
    #             'Q_RTD_SR_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
    fig.savefig('C:/Users/ronan/OneDrive/UNINE/11_Paper/QUIOCK/_figures/_paper_v1/_raw/best/'+
                'Q_RTD_SR_'+model_name+'_up'+'.png', dpi=300, bbox_inches='tight')

# data_explo.to_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')

#%% 5 - PLOT Q SR RTD SENSITIVITY

list_selects = list_model_name

data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')

dem = rasterio.open("C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_box_buff_dem.tif")
dem_data = imageio.imread(BV.geographic.watershed_dem)
dem_data[dem_data<0] = np.nan
shp_contour = gpd.read_file(BV.geographic.watershed_shp)
shp_box = gpd.read_file(stable_folder+'geographic/box_buff.shp')
stre = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2.shp')
wt_mask = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/watershed_mask.shp')
subwt_flow = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/subbasin/subbasin_Flowrate/watershed_contour.shp')
subwt_point = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/snap_flowrate.shp')
wbt.raster_to_vector_points(BV.geographic.watershed_dem, 
                            'C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp')
wbt.extract_raster_values_at_points(down_path, 
                                    'C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp')
dem_down = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp')
wbt.extract_raster_values_at_points('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_box_buff_dem.tif', 
                                    'C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp')
wbt.extract_raster_values_at_points(down_path, 
                                    'C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp')
riv_pts = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp')

field = pd.read_csv('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_data/Field_data.csv',
                    sep=';')
field['d_mouth'] = pd.to_numeric(field['d_mouth'])
field = field.dropna(subset=['Name']) 
field = field.dropna(subset=['d_mouth'])

field_filter = field[field['Date']!='May 2019']
field_filter = field_filter.dropna(subset=['Name']) 
field_filter = field_filter.dropna(subset=['d_mouth'])
field_filter = field_filter.sort_values('d_mouth')
field_filter = field_filter.reset_index()
field_filter.loc[1,'d_mouth'] = 10
field_filter.loc[2,'d_mouth'] = 20
field_filter['d_mouth'] = field_filter ['d_mouth'].astype(int)
field_filter.loc[12,'d_mouth'] = 472
field_filter.loc[13,'d_mouth'] = 475

for ip, model_name in enumerate(list_selects[:]):
    
    cpt = int(model_name.split('_')[1]) - 1
    
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    wbt.extract_raster_values_at_points(down_path, 
                                        simulations_folder+model_name+'/'+'_pathlines/'+'shp_ending_shal.shp', 
                                        out_text=False)
    wbt.extract_raster_values_at_points(down_path, 
                                        simulations_folder+model_name+'/'+'_pathlines/'+'shp_ending_deep.shp', 
                                        out_text=False)
    
    shp_ending_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    shp_ending_shal = shp_ending_shal[shp_ending_shal['VALUE1']>0]
    shp_ending_shal = shp_ending_shal.clip(shp_contour)
    
    shp_ending_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    shp_ending_deep = shp_ending_deep[shp_ending_deep['VALUE1']>0]
    shp_ending_deep = shp_ending_deep.clip(shp_contour)
    
    resume_mask = pd.read_csv(BV.simulations_folder+'/'+model_name+'/resume_clean.csv',
                         sep=';')
    
    # print(resume_mask['distance_mask_riv'].min())
    the_proj_max = shp_ending_shal['VALUE1'].max()
    the_proj_min = resume_mask['distance_mask_riv'].min()
    resume_mask['distance_mask_riv'] = resume_mask['distance_mask_riv'] - the_proj_min
    
    resume_mask['accumul_mask_riv_new'] = np.nan
    resume_mask['Qriv_mask_shal_new'] = np.nan
    
    fig, axs = plt.subplots(2,1, figsize=(5.5,6), sharex=True)
    
    # fig, ax = plt.subplots(1,1, figsize=(6.5,3.5))
    
    ax = axs[0]
    axb = ax.twinx()
    
    resume_mask['accumul_mask_riv_new'] = resume_mask['accumul_mask_riv']
    resume_mask['accumul_mask_riv_new'][resume_mask['accumul_mask_riv_new']* 1000 / 3600 / 24<1.1] = np.nan
    resume_mask.loc[0,'accumul_mask_riv_new'] = resume_mask['accumul_mask_riv'].min()
    masked_acc = resume_mask.dropna(subset=['accumul_mask_riv_new'])
    masked_acc.loc[-1, 'accumul_mask_riv_new'] = 0
    masked_acc.loc[-1, 'distance_mask_riv'] = the_proj_max - the_proj_min
    masked_acc = masked_acc.reset_index()
    masked_acc = masked_acc.sort_values('distance_mask_riv')
    resume_mask['Qriv_mask_shal_new'] = resume_mask['Qriv_mask_shal']
    resume_mask['Qriv_mask_shal_new'][resume_mask['Qriv_mask_shal_new']* 1000 / 3600 / 24<1.1] = np.nan
    resume_mask.loc[0,'Qriv_mask_shal_new'] = resume_mask['Qriv_mask_shal'].min()
    masked_shal = resume_mask.dropna(subset=['Qriv_mask_shal_new'])
    masked_shal.loc[-1, 'Qriv_mask_shal_new'] = 0
    masked_shal.loc[-1, 'distance_mask_riv'] = the_proj_max - the_proj_min
    masked_shal = masked_shal.reset_index()
    masked_shal = masked_shal.sort_values('distance_mask_riv')
    
    if model_name == 'nearest1_2_10.0-150.0-300_50':
        ax.plot(masked_acc['distance_mask_riv'], masked_acc['accumul_mask_riv_new']* 1000 / 3600 / 24,
                color='k', lw=5, marker='_', ms=0)
        ax.plot(masked_shal['distance_mask_riv'], masked_shal['Qriv_mask_shal_new']* 1000 / 3600 / 24,
                color='dodgerblue', lw=3, marker='_', ms=0)
        ax.plot(resume_mask['distance_mask_riv'][resume_mask['Qriv_mask_deep']>0],
                resume_mask['Qriv_mask_deep'][resume_mask['Qriv_mask_deep']>0]* 1000 / 3600 / 24,
                color='red', lw=3, marker='_', ms=0)
    else:
        masked_acc = masked_acc.dropna(subset=['accumul_mask_riv_new'])
        masked_shal = masked_shal.dropna(subset=['Qriv_mask_shal_new'])
        resume_mask = resume_mask.dropna(subset=['Qriv_mask_deep'])
        ax.plot(masked_acc['distance_mask_riv'], masked_acc['accumul_mask_riv_new']* 1000 / 3600 / 24,
                color='k', lw=0, marker='_', mew=5, ms=5)
        ax.plot(masked_shal['distance_mask_riv'], masked_shal['Qriv_mask_shal_new']* 1000 / 3600 / 24,
                color='darkblue', lw=0, marker='_', mew=3, ms=5)
        ax.plot(resume_mask['distance_mask_riv'][resume_mask['Qriv_mask_deep']>0],
                resume_mask['Qriv_mask_deep'][resume_mask['Qriv_mask_deep']>0]* 1000 / 3600 / 24,
                color='darkred', lw=0, marker='_', mew=3, ms=5)

    ax.set_xlim(-20,750)
    ax.set_ylim(0,10)
    # if model_name != 'nearest1_2_10.0-150.0-300_50':
    #     ax.set_ylim(1,10)
    # ax.set_xlabel('Distance to outlet [m]')
    # ax.set_ylabel('$Q_{sim}$ [L/s]')
    ax.set_ylabel('Q [L/s]')
    ax.set_title(model_name, fontsize=8)
    
    ax.plot(450, 3.1, lw=2, marker='*', color='white', ms=15, mew=2, markeredgecolor='k')
    
    # ax.scatter(shp_ending_shal['VALUE1'],shp_ending_shal['time'])
    # ax.scatter(shp_ending_deepl['VALUE1'],shp_ending_deepl['time'])
    
    # axb.vlines(x=shp_ending_shal['VALUE1']-83.28427-20,
    #           ymin=shp_ending_shal['time']*0,
    #           ymax=shp_ending_shal['time'], color='dodgerblue', lw=0.25)
    # axb.vlines(x=shp_ending_deep['VALUE1']-83.28427-20,
    #           ymin=shp_ending_deep['time']*0,
    #           ymax=shp_ending_deep['time'], color='red', lw=0.25)

    # axb.vlines(x=(shp_ending_shal['VALUE1']*masked_acc['distance_mask_riv'].max())/shp_ending_shal['VALUE1'].max(),
    #           ymin=shp_ending_shal['time']*0,
    #           ymax=shp_ending_shal['time'], color='dodgerblue', lw=0.25)
    # axb.vlines(x=(shp_ending_deep['VALUE1']*masked_acc['distance_mask_riv'].max())/shp_ending_shal['VALUE1'].max(),
    #           ymin=shp_ending_deep['time']*0,
    #           ymax=shp_ending_deep['time'], color='red', lw=0.25)

    shp_ending_shal['VALUE1'] = shp_ending_shal['VALUE1'] - the_proj_min # shp_ending_shal['VALUE1'].min()
    shp_ending_deep['VALUE1'] = shp_ending_deep['VALUE1'] - the_proj_min # shp_ending_deep['VALUE1'].min()

    axb.vlines(x=shp_ending_shal['VALUE1'],
              ymin=shp_ending_shal['time']*0,
              ymax=shp_ending_shal['time']/2, color='dodgerblue', lw=0.25)
    axb.vlines(x=shp_ending_deep['VALUE1'],
              ymin=shp_ending_deep['time']*0,
              ymax=shp_ending_deep['time']/2, color='red', lw=0.25)

    # # cb = fig.colorbar(s)
    # # cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)
    axb.set_ylim(0.1,1000)
    axb.set_yscale('log')
    axb.set_ylabel('t [y]', rotation= 270, labelpad=40)
    
    ax.invert_xaxis()
    ax.patch.set_visible(False)
    ax.set_zorder(axb.get_zorder()+1)
    
    ax = axs[1]
    
    Srp = 4.5
    Srr = 150     # 110
    RSrp = 0.7092
    RSrr = 0.7038 # 0.7041
    
    resume_mask = pd.read_csv(BV.simulations_folder+'/'+model_name+'/resume_clean.csv',
                         sep=';')
    
    # print(resume_mask['distance_mask_riv'].min())
    resume_mask['distance_mask_riv'] = resume_mask['distance_mask_riv'] - resume_mask['distance_mask_riv'].min()

    resume_mask.loc[-1, 'Csr_riv_calc'] = Srp
    resume_mask.loc[-1, 'Rsr_riv_calc'] = RSrp
    resume_mask.loc[-1, 'accumul_mask_riv'] = 0
    resume_mask.loc[-1, 'Qriv_mask_shal'] = 0
    resume_mask.loc[-1, 'Qriv_mask_deep'] = 0
    resume_mask.loc[-1, 'distance_mask_riv'] = the_proj_max - the_proj_min
    resume_mask = resume_mask.sort_values('distance_mask_riv', ascending=False)
    resume_mask = resume_mask.reset_index()

    resume_mask['Csr_riv_calc'] = ''
    resume_mask['Rsr_riv_calc'] = ''

    for i in resume_mask.index:
        if i == 0:
            resume_mask.loc[i,'Csr_riv_calc'] = Srp
            resume_mask.loc[i,'Rsr_riv_calc'] = RSrp
        else:
            resume_mask.loc[i,'Csr_riv_calc'] = ( resume_mask.loc[i-1,'Csr_riv_calc']*resume_mask.loc[i-1,'accumul_mask_riv'] + \
                                                  Srr*(resume_mask.loc[i,'Qriv_mask_deep']-resume_mask.loc[i-1,'Qriv_mask_deep']) + \
                                                  Srp*(resume_mask.loc[i,'Qriv_mask_shal']-resume_mask.loc[i-1,'Qriv_mask_shal']) ) / \
                                                  resume_mask.loc[i,'accumul_mask_riv']
                                             
            resume_mask.loc[i,'Rsr_riv_calc'] = ( resume_mask.loc[i-1,'Rsr_riv_calc']*resume_mask.loc[i-1,'Csr_riv_calc']*resume_mask.loc[i-1,'accumul_mask_riv'] + \
                                                  RSrr*Srr*(resume_mask.loc[i,'Qriv_mask_deep']-resume_mask.loc[i-1,'Qriv_mask_deep']) + \
                                                  RSrp*Srp*(resume_mask.loc[i,'Qriv_mask_shal']-resume_mask.loc[i-1,'Qriv_mask_shal']) ) / \
                                                  (resume_mask.loc[i,'accumul_mask_riv']*resume_mask.loc[i,'Csr_riv_calc'])

    # fig, ax = plt.subplots(1,1, figsize=(6.5,3.5))
    axb = ax.twinx()
    # s = ax.scatter(resume_mask['distance_mask_riv'],
    #                resume_mask['accumul_mask_riv'] * 1000 / 3600 / 24,
    #                marker='_', lw=3, c='k',
    #                 s=10,
    #                 # norm=matplotlib.colors.LogNorm()
    #                 )
    # sb = axb.bar(resume['distance_riv'],
    #              resume['Qriv_shal'] * 1000 / 3600 / 24,
    #              width=5, lw=0, color='dodgerblue', zorder=-1)
    # sb = axb.bar(resume['distance_riv'],
    #              resume['Qriv_deep'] * 1000 / 3600 / 24,
    #              width=5, lw=0, color='red', zorder=-1)
    s = ax.plot(resume_mask['distance_mask_riv'],
                   resume_mask['Csr_riv_calc']/1000,
                   marker='|', ms=0, lw=3, c='darkorange',
                    # s=10,
                    # norm=matplotlib.colors.LogNorm()
                    zorder=-10
                    )
    s = axb.plot(resume_mask['distance_mask_riv'],
                   resume_mask['Rsr_riv_calc'],
                   marker='|', ms=0, lw=3, c='forestgreen',
                    # s=10,
                    # norm=matplotlib.colors.LogNorm()
                    zorder=-10
                    )
    ax.set_xlim(-20,750)
    ax.set_xlabel('Distance to outlet [m]')
    ax.set_ylabel('Sr [ppm]', c='darkorange')
    # ax.axvline(x=130, c='dimgray', ls=':', lw=3)
    axb.set_ylabel('$^{87}$Sr/$^{86}$Sr [-]', rotation=270,
                   labelpad = 40, color='forestgreen')
    if cpt > 4 :
        ax.set_ylim(0.003, 0.013)
        ax.set_yticks([0.004, 0.006, 0.008, 0.010, 0.012])
        axb.set_ylim(0.705, 0.710)
    if cpt <= 4:
        # Srp = 4.5
        # Srr = 150     # 110
        # RSrp = 0.7092
        # RSrr = 0.7038 # 0.7041
        ax.set_ylim(0, 0.15)
        # ax.set_yticks([0.004, 0.006, 0.008, 0.010, 0.012])
        axb.set_ylim(0.703, 0.710)
    axb.ticklabel_format(style='plain')
    axb.ticklabel_format(useOffset=False, style='plain')
    ax.set_title(model_name, fontsize=8)
    ax.invert_xaxis()
    ax.patch.set_visible(False)
    ax.set_zorder(axb.get_zorder()+1)
    
    samp = field_filter[field_filter['Date']=='June 2016']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[1],
                   facecolor='forestgreen',
                   marker='<', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppm'],
                   # facecolor=colors[1],
                   facecolor='darkorange',
                   marker='<', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )
    
    """
    samp = field[field['Date']=='May 2019']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[0],
                   facecolor='forestgreen',
                   marker='^', lw=0.5,
                    s=20,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppm'],
                   # facecolor=colors[0],
                   facecolor='darkorange',
                   marker='^', lw=0.5,
                    s=20,
                    # norm=matplotlib.colors.LogNorm()
                    )
    """
    
    samp = field_filter[field_filter['Date']=='June 2019']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[2],
                   facecolor='forestgreen',
                   marker='>', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppm'],
                   # facecolor=colors[2],
                   facecolor='darkorange',
                   marker='>', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )
    # field_filter = field[field['Date']!='May 2019']
    # field_filter = field_filter.dropna(subset=['Name']) 
    # field_filter = field_filter.dropna(subset=['d_mouth'])
    # field_filter = field_filter.sort_values('d_mouth')
    # field_filter = field_filter.reset_index()
    # field_filter.loc[1,'d_mouth'] = 10
    # field_filter.loc[2,'d_mouth'] = 20
    # field_filter['d_mouth'] = field_filter ['d_mouth'].astype(int)
    # field_filter.loc[13,'d_mouth'] = 471
    # field_filter.loc[13,'d_mouth'] = 472
        
    for ix, dm in zip(field_filter.index, field_filter.d_mouth):
        index = np.argmin(np.abs(resume_mask['distance_mask_riv']-dm))
        # print(index)
        resume_mask.loc[index,'SrR_obs'] = field_filter.loc[ix,'87Sr_86Sr']
        resume_mask.loc[index,'SrC_obs'] = field_filter.loc[ix,'Sr_ppm']
    
    resume_mask_dropna = resume_mask.dropna(subset=['SrR_obs'])    
    # resume_mask_dropna = resume_mask.copy()
    
    the_diff = resume_mask_dropna['Rsr_riv_calc'] - resume_mask_dropna['SrR_obs']
    value=np.sqrt(np.sum((the_diff)**2)/len(resume_mask_dropna))
    if value == 0:
        value = np.nan
    print(value)
    data_explo.loc[cpt,'RMSE_R'] = value
    
    the_diff = resume_mask_dropna['Csr_riv_calc']/1000 - resume_mask_dropna['SrC_obs']
    value=np.sqrt(np.sum((the_diff)**2)/len(resume_mask_dropna))
    if value == 0:
        value = np.nan
    print(value)
    data_explo.loc[cpt,'RMSE_C'] = value
    
    # fig.savefig(fig_path+'PLOT CLEAN RTD'+'_'+model_name+'.png', dpi=300, bbox_inches='tight')

    # fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/best/'+
    #             'Q_RTD_SR.png', dpi=300, bbox_inches='tight')
    
    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/maps_sensitivity/'+
                'Q_RTD_SR_'+model_name+'.png', dpi=300, bbox_inches='tight')

# data_explo.to_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')


#%% 4 - PLOT CALIB ALL

# if not 'data_explo' in globals():
#     data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')

# if not 'data_explo' in globals():
#     data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')

# if not 'data_explo' in globals():
typ = 'tests1'
data_explo1 = pd.read_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')
data_explo1['k0k1'] = pd.to_numeric(data_explo1['k0k1'])
data_explo1['Doptim'] = (data_explo1['D_so']+data_explo1['D_os'])/2

typ = 'nearest1'
data_explo2 = pd.read_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')
data_explo2['k0k1'] = pd.to_numeric(data_explo2['k0k1'])
data_explo2['Doptim'] = (data_explo2['D_so']+data_explo2['D_os'])/2

data_explo3 = data_explo2.append(data_explo1,ignore_index = True)
data_explo3 = data_explo3.sort_values('k0k1')

# fig, ax = plt.subplots(1,1, figsize=(4.5,3.5))

fig, axs = plt.subplots(4,1, figsize=(4,12), sharex=True)
axs = axs.ravel()

def make_patch_spines_invisible(ax):
    ax.set_frame_on(True)
    ax.patch.set_visible(False)
    for sp in ax.spines.values():
        sp.set_visible(False)

ax = axs[0]
ax.axvline(x=1, c='grey', ls=':', lw=2)

ax.plot(data_explo3['k0k1'], data_explo3['D_so'],
            color='grey', marker='o', lw=1, mec='grey', mfc='w', mew=1)
ax.plot(data_explo3['k0k1'], data_explo3['D_os'],
            color='k', marker='o', lw=1, mec='k', mfc='w', mew=1)
# ax_l0.plot(data_explo['k0k1'], (abs(data_explo['D_so']-data_explo['D_os'])),
            # color='darkred', marker='s', lw=2, mew=1.5, mec='darkred', mfc='white')
# ax_l0.set_yscale('log')
ax.plot(data_explo3['k0k1'], data_explo3['Doptim'],
            color='red', marker='s', lw=2, mec='k', mfc='red', mew=1)

ax.set_xscale('log')
# ax.set_yscale('log')
# ax.axhline(y=1, c='k', ls='--')
ax.set_ylim(-5, 90)
# ax.set_xlabel('K1 / K2 [-]')
ax.set_ylabel('$D_{streams}$ [m]', c='k')

# ax.grid()

# fig.savefig(fig_path+'PLOT CALIB STREAMS GRAPH'+".PNG", dpi=300, bbox_inches='tight')

# fig.savefig(fig_path+'PLOT CALIB STREAMS GRAPH'+".PNG", dpi=300, bbox_inches='tight')

# 4 - PLOT CALIB STREAMFLOW

# if not 'data_explo' in globals():
#     data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')

# if not 'data_explo' in globals():
typ = 'tests1'
data_explo1 = pd.read_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')
data_explo1['k0k1'] = pd.to_numeric(data_explo1['k0k1'])
data_explo1['Doptim'] = (data_explo1['D_so']+data_explo1['D_os'])/2

typ = 'nearest1'
data_explo2 = pd.read_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')
data_explo2['k0k1'] = pd.to_numeric(data_explo2['k0k1'])
data_explo2['Doptim'] = (data_explo2['D_so']+data_explo2['D_os'])/2

data_explo3 = data_explo2.append(data_explo1,ignore_index = True)
data_explo3 = data_explo3.sort_values('k0k1')

typ = 'tests1'
data_explo4 = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')
data_explo4['k0k1'] = pd.to_numeric(data_explo1['k0k1'])
data_explo4['Doptim'] = (data_explo1['D_so']+data_explo1['D_os'])/2

typ = 'nearest1'
data_explo5 = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')
data_explo5['k0k1'] = pd.to_numeric(data_explo2['k0k1'])
data_explo5['Doptim'] = (data_explo2['D_so']+data_explo2['D_os'])/2

data_explo6 = data_explo5.append(data_explo4,ignore_index = True)
data_explo6 = data_explo6.sort_values('k0k1')

# fig, ax = plt.subplots(1,1, figsize=(4.5,3.5))

def make_patch_spines_invisible(ax):
    ax.set_frame_on(True)
    ax.patch.set_visible(False)
    for sp in ax.spines.values():
        sp.set_visible(False)

ax = axs[1]
ax.axvline(x=1, c='grey', ls=':', lw=2)

# ax.plot(data_explo6['k0k1'], data_explo6['Qout_sim']/data_explo6['Qsub_obs'],
#         color='blue', marker='s', lw=2, mec='k', mfc='blue', mew=1)

ax.plot(data_explo6['k0k1'], 
        abs((data_explo6['Qout_sim']-data_explo6['Qsub_obs'])/data_explo6['Qsub_obs']),
        color='blue', marker='s', lw=2, mec='k', mfc='blue', mew=1)


ax.set_xscale('log')
ax.set_yscale('log')
# ax.axhline(y=1, c='k', ls='--')
ax.set_ylim(2e-4, 1e-0)
# ax.set_xlabel('K1 / K2 [-]')
ax.set_ylabel('|($Q_{sim}$-$Q_{obs}$)/$Q_{obs}$| [-]', c='k')

# ax.grid()

# fig.savefig(fig_path+'PLOT CALIB STREAMFLOW'+'.png', dpi=300, bbox_inches='tight')

# 4 - PLOT CALIB SR

colors = ['navy','dodgerblue','lightskyblue']

# fig, ax = plt.subplots(1,1, figsize=(4.5,3.5))

def make_patch_spines_invisible(ax):
    ax.set_frame_on(True)
    ax.patch.set_visible(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
        
ax = axs[3]
ax.axvline(x=1, c='grey', ls=':', lw=2)
       
 
typ = 'tests1'
# if not 'data_explo' in globals():
#     data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')
# if not 'data_explo' in globals():
data_explo1 = pd.read_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')
data_explo1['k0k1'] = pd.to_numeric(data_explo1['k0k1'])
data_explo1['Doptim'] = (data_explo1['D_so']+data_explo1['D_os'])/2

typ = 'nearest1'
# if not 'data_explo' in globals():
#     data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')
# if not 'data_explo' in globals():
data_explo2 = pd.read_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')
data_explo2['k0k1'] = pd.to_numeric(data_explo2['k0k1'])
data_explo2['Doptim'] = (data_explo2['D_so']+data_explo2['D_os'])/2

# ax.plot(data_explo2['k0k1'], 
#            data_explo2['RMSE']/(0.7092-0.7041),
#            color='darkviolet', marker='s', lw=2, mec='k', mfc='darkviolet', mew=1)
ax.set_xscale('log')
# ax.set_yscale('log')
# ax.axhline(y=1, c='k', ls='--')
# ax.set_xlim(1e-3,2e4)
ax.set_ylim(0, 1)
# ax.set_xlabel('K1 / K2 [-]')
ax.set_ylabel('$RMSE_{norm}$ $^{87}$Sr/$^{86}$Sr [-]', c='k')
# ax.grid()

data_explo3 = data_explo2.append(data_explo1,ignore_index = True)
data_explo3 = data_explo3.sort_values('k0k1')

ax.plot(data_explo3['k0k1'], 
            data_explo3['RMSE_R']/(0.7092-0.7041),
            color='forestgreen', marker='s', lw=2, mec='k', mfc='forestgreen', mew=1)
ax.set_xscale('log')
# ax.set_yscale('log')
# ax.axhline(y=1, c='k', ls='--')
# ax.set_xlim(5e-4,2e4)
ax.set_ylim(0, 1)
ax.set_xlabel('K1 / K2 [-]')
ax.set_ylabel('RMSE* $^{87}$Sr/$^{86}$Sr [-]', c='k')
# ax.grid()

ax = axs[2]
ax.axvline(x=1, c='grey', ls=':', lw=2)

ax.plot(data_explo3['k0k1'], 
            data_explo3['RMSE_C'],
            color='darkorange', marker='s', lw=2, mec='k', mfc='darkorange', mew=1)
ax.set_xscale('log')
ax.set_yscale('log')
# ax.axhline(y=1, c='k', ls='--')
ax.set_xlim(5e-4,2e4)
ax.set_ylim(5e-4, 2e-1)
# ax.set_xlabel('K1 / K2 [-]')
ax.set_ylabel('RMSE Sr [ppm]', c='k')
# ax.grid()

# fig.savefig(fig_path+'PLOT CALIB SR'+'.png', dpi=300, bbox_inches='tight')

# fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/'+
#             'PLOT CALIB ALL'+'.png', dpi=300, bbox_inches='tight')

#%% S1 - PLOT PROP

typ = 'tests1'

# if not 'data_explo' in globals():
data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')

# if not 'data_explo' in globals():
    # data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')

data_explo['k0k1'] = pd.to_numeric(data_explo['k0k1'])
data_explo['Doptim'] = (data_explo['D_so']+data_explo['D_os'])/2

fig, ax = plt.subplots(1,1, figsize=(4.5,3))
ax.plot(data_explo['k0k1'], data_explo['k0']/3600/24,
        color='dodgerblue', marker='o', lw=2, mec='dodgerblue', mfc='w', mew=1.5, label='K1')
ax.plot(data_explo['k0k1'], data_explo['k1']/3600/24,
        color='red', marker='o', lw=2, mec='red', mfc='w', mew=1.5, label='K2')
ax.plot(data_explo['k0k1'], (data_explo['k0']/3600/24*40 + data_explo['k1']/3600/24*360)/400,
        color='k', marker='|', lw=2, mec='k', mfc='w', ms=10, mew=2, label='Keq', zorder=-1)
# ax.legend(loc='lower right')
ax.set_xscale('log')
ax.set_yscale('log')
ax.axvline(x=1, c='grey', ls='--', zorder=-1)
# ax.set_ylim(-3, 100)
ax.set_xlabel('K1 / K2 [-]')
ax.set_ylabel('K [m/s]', c='k')
# import matplotlib
# ax.get_yaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, p: format(int(x), ',')))
# from matplotlib.ticker import ScalarFormatter
# plt.gca().yaxis.set_major_formatter(ScalarFormatter()) 
# ax.ticklabel_format(axis='y', scilimits=(0,0))

# fig.savefig(fig_path+'PLOT PROP'+".PNG", dpi=300, bbox_inches='tight')

fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/'+
            'PLOT PROP'+".PNG", dpi=300, bbox_inches='tight')

#%% S2 - PLOT CALIB STREAMS MAPS

streams = gpd.read_file("C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2.shp")
contour = gpd.read_file("C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_contour.shp")

import rasterio
from osgeo import gdal
from rasterio.plot import show

dem = rasterio.open("C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem.tif")
# dem = path+site+'/gis/'+'watershed_extent.tif'
# gdal.Translate(dem, gdal.Open(path+'_data/'+tif), 
#                 projWin=[xlim[0],ylim[1],xlim[1],ylim[0]], noData=-99999)
# hill = path+site+'/gis/'+'watershed_extent_hill.tif'
# wbt.hillshade(dem, hill, azimuth=315.0, altitude=45.0, zfactor=2)
# dem = rasterio.open(path+site+'/gis/'+'watershed_extent.tif')
# hill = rasterio.open(path+site+'/gis/'+'watershed_extent_hill.tif')

lims = []

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

cs = 0

for model_name in list_selects[:]:
    
    fig, axs = plt.subplots(1,2, figsize=(6,3))
    axs = axs.ravel()

    simflow_path = simulations_folder+model_name+'/'+'_streams/simflow.shp'
    obsflow_path = simulations_folder+model_name+'/'+'_streams/obsflow.shp'
    
    simflow = gpd.read_file(simflow_path)
    obsflow = gpd.read_file(obsflow_path)
    
    bounds = simflow.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    
    if cs==0:
        vmax = simflow.VALUE.max()
            
    ax=axs[0]
    ax.axis('off')
    mnt = rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.25, zorder=0, aspect="auto")
    colori = "RdYlGn_r"
    streams.plot(ax=ax, lw=1, color='navy', zorder=0)
    simflow.plot(ax=ax, alpha=1, column='VALUE1', cmap=colori, 
                 marker='s', markersize=2, lw=0.1, edgecolor='none',
                 scheme="User_Defined", 
                 classification_kwds=dict(bins=[0, 5, 10, 20, 40, 80]),
                 zorder=1)
    contour.plot(ax=ax, lw=1.5, color='k', zorder=2)
    ax.set_title('Sim. to Obs.', fontsize=8)

    ax=axs[1]
    ax.axis('off')
    colori = "RdYlGn_r"
    ax.axis('off')    
    mnt = rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.25, zorder=0, aspect="auto")
    streams.plot(ax=ax, lw=1, color='navy', zorder=1)
    obsflow.plot(ax=ax, alpha=1, column='VALUE1', cmap=colori, 
                 marker='s', markersize=2, lw=0.1, edgecolor='none',
                 scheme="User_Defined", 
                 classification_kwds=dict(bins=[0, 5, 10, 20, 40, 80]),
                 zorder=2)
    contour.plot(ax=ax, lw=1.5, color='k', zorder=3)
    ax.set_title('Obs. to Sim.', fontsize=8)
        
    lims.append(simflow.VALUE1.max())
    lims.append(simflow.VALUE1.min())
    lims.append(obsflow.VALUE1.max())
    lims.append(obsflow.VALUE1.min())
    
    cs += 1

    # fig.subplots_adjust(wspace=-0.3, hspace=-0.55)
    fig.suptitle(model_name.upper(), fontsize=8, y=0.9)
    
    # fig.savefig(fig_path+'PLOT CALIB STREAMS MAPS_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/_paper_v1/_raw/streamaps_calib/'+
                'PLOT CALIB STREAMS MAPS_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
# fig.subplots_adjust(wspace=0, hspace=-0.3)

#%% S3 - PLANCHAS

#%% CALCUL LAME D'EAU

list_selects = list_model_name

wbt.verbose = False


for model_name in list_selects[1:2]:
    
    cpt = int(model_name.split('_')[1]) - 1
    
    out_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    out_data = imageio.imread(out_path)
    
    mask_dem = imageio.v2.imread('C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem.tif') 
    
    for samp_name in ['subbasin_Flowrate',
                      'subbasin_Samp1',
                      'subbasin_Samp2',
                      'subbasin_Samp3',
                      'subbasin_Samp4',
                      'subbasin_Samp5'
                      ]:
    
        mask_sub = imageio.v2.imread('C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/subbasin/'+samp_name+'/watershed.tif')
        # toolbox.export_tif('C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem.tif',
        #                    mask_sub, -99999,
        #                    'C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/subbasin/subbasin_Flowrate/watershed_up.tif')
        # mask_sub = imageio.imread('C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/subbasin/subbasin_Flowrate/watershed_up.tif')
        
        wbt.vector_polygons_to_raster(
            'C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/subbasin/'+samp_name+'/watershed.shp', 
            'C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/subbasin/'+samp_name+'/watershed_up.tif', 
            field="FID", 
            nodata=True, 
            cell_size=None, 
            base='C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem.tif')
        
        mask_sub = imageio.v2.imread('C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/subbasin/'+samp_name+'/watershed_up.tif')
        
        sub_area = gpd.read_file('C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/subbasin/'+samp_name+'/watershed.shp')
        sub_area = sub_area.area
        
        sub_out = gpd.read_file('C:/Users/ronan/Simulations/GUADELOUPE/Quiock3/results_stable/geographic/watershed.shp')
        sub_out = sub_out.area
        
        out_dem = np.ma.masked_where(mask_dem<0, out_data)
        out_sub = np.ma.masked_where(mask_sub<0, out_data)
        
        sum_out = 365 * 1000 * out_dem.sum() #/ sub_out
        sum_sub = 365 * 1000 *  out_sub.sum() #/ sub_area
        print(sum_out, sub_out[0], sub_area[0], sum_sub)

    # out_dem 
    

#%% ---- NOTES    

#%% ARCH - PLOT ONLY Q SEEPAGE

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

for model_name in list_selects[:]:
    
    resume = pd.read_csv(BV.simulations_folder+'/'+model_name+'/resume.csv',
                         sep=';')
    
    print(resume['distance_riv'].min())
    resume['distance_riv'] = resume['distance_riv'] - resume['distance_riv'].min()
    
    fig, ax = plt.subplots(1,1, figsize=(5.5,3))
    axb = ax.twinx()
    s = ax.scatter(resume['distance_riv'],
                   resume['accumul_riv'] * 1000 / 3600 / 24,
                   marker='_', lw=2, c='k',
                    s=20,
                    # norm=matplotlib.colors.LogNorm()
                    )
    # sb = axb.bar(resume['distance_riv'],
    #              resume['Qriv_shal'] * 1000 / 3600 / 24,
    #              width=5, lw=0, color='dodgerblue', zorder=-1)
    # sb = axb.bar(resume['distance_riv'],
    #              resume['Qriv_deep'] * 1000 / 3600 / 24,
    #              width=5, lw=0, color='red', zorder=-1)
    s = axb.scatter(resume['distance_riv'],
                   resume['Qriv_shal'] * 1000 / 3600 / 24,
                   marker='|', lw=2, c='dodgerblue',
                    s=5,
                    # norm=matplotlib.colors.LogNorm()
                    )
    s = axb.scatter(resume['distance_riv'],
                   resume['Qriv_deep'] * 1000 / 3600 / 24,
                   marker='|', lw=2, c='red',
                    s=5,
                    # norm=matplotlib.colors.LogNorm()
                    )
    ax.set_xlabel('Distance to outlet [m]')
    ax.set_ylabel('$Q_{river}$ [L/s]')
    # cb = fig.colorbar(s)
    # cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)
    ax.plot(471, 2.8, lw=2, marker='s', color='white', mew=2, markeredgecolor='k')
    ax.set_xlim(-20,800)
    ax.set_ylim(0,10)
    axb.set_ylim(0,0.1)
    axb.set_ylabel('$Q_{seepage}$ [L/s]', rotation=270, labelpad = 40)
    ax.invert_xaxis()
    ax.patch.set_visible(False)
    ax.set_zorder(axb.get_zorder()+1)
    
    ax.set_title(model_name, fontsize=8)
    
    plt.tight_layout()
    
    # fig.savefig(fig_path+'PLOT CLEAN Q'+'_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% ARCH - PLOT ONLY SR 

# typ = 'tests1'
# typ = 'nearest1'
data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')

field = pd.read_csv('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_data/Field_data.csv',
                    sep=';')
field['d_mouth'] = pd.to_numeric(field['d_mouth'])
# field = field.dropna(subset=['87Sr_86Sr'])

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)

list_selects = list_model_name

for model_name in list_selects[:]:
    
    cpt = int(model_name.split('_')[1]) - 1

    # resume_mask = resume_mask.reset_index()
    
    resume_mask = pd.read_csv(BV.simulations_folder+'/'+model_name+'/resume_clean.csv',
                         sep=';')
    
    print(resume_mask['distance_mask_riv'].min())
    resume_mask['distance_mask_riv'] = resume_mask['distance_mask_riv'] - resume_mask['distance_mask_riv'].min()

    Srp = 4.5
    Srr = 110
    RSrp = 0.7092
    RSrr = 0.7041

    resume_mask['Csr_riv_calc'] = ''
    resume_mask['Rsr_riv_calc'] = ''

    for i in resume_mask.index:
        if i == 0:
            resume_mask.loc[i,'Csr_riv_calc'] = Srp
            resume_mask.loc[i,'Rsr_riv_calc'] = RSrp
        else:
            resume_mask.loc[i,'Csr_riv_calc'] = ( resume_mask.loc[i-1,'Csr_riv_calc']*resume_mask.loc[i-1,'accumul_mask_riv'] + \
                                                  Srr*(resume_mask.loc[i,'Qriv_mask_deep']-resume_mask.loc[i-1,'Qriv_mask_deep']) + \
                                                  Srp*(resume_mask.loc[i,'Qriv_mask_shal']-resume_mask.loc[i-1,'Qriv_mask_shal']) ) / \
                                                  resume_mask.loc[i,'accumul_mask_riv']
                                             
            resume_mask.loc[i,'Rsr_riv_calc'] = ( resume_mask.loc[i-1,'Rsr_riv_calc']*resume_mask.loc[i-1,'Csr_riv_calc']*resume_mask.loc[i-1,'accumul_mask_riv'] + \
                                                  RSrr*Srr*(resume_mask.loc[i,'Qriv_mask_deep']-resume_mask.loc[i-1,'Qriv_mask_deep']) + \
                                                  RSrp*Srp*(resume_mask.loc[i,'Qriv_mask_shal']-resume_mask.loc[i-1,'Qriv_mask_shal']) ) / \
                                                  (resume_mask.loc[i,'accumul_mask_riv']*resume_mask.loc[i,'Csr_riv_calc'])

    fig, ax = plt.subplots(1,1, figsize=(6.5,3.5))
    axb = ax.twinx()
    # s = ax.scatter(resume_mask['distance_mask_riv'],
    #                resume_mask['accumul_mask_riv'] * 1000 / 3600 / 24,
    #                marker='_', lw=3, c='k',
    #                 s=10,
    #                 # norm=matplotlib.colors.LogNorm()
    #                 )
    # sb = axb.bar(resume['distance_riv'],
    #              resume['Qriv_shal'] * 1000 / 3600 / 24,
    #              width=5, lw=0, color='dodgerblue', zorder=-1)
    # sb = axb.bar(resume['distance_riv'],
    #              resume['Qriv_deep'] * 1000 / 3600 / 24,
    #              width=5, lw=0, color='red', zorder=-1)
    s = ax.plot(resume_mask['distance_mask_riv'],
                   resume_mask['Csr_riv_calc']/1000,
                   marker='|', ms=0, lw=3, c='darkorange',
                    # s=10,
                    # norm=matplotlib.colors.LogNorm()
                    zorder=-10
                    )
    s = axb.plot(resume_mask['distance_mask_riv'],
                   resume_mask['Rsr_riv_calc'],
                   marker='|', ms=0, lw=3, c='forestgreen',
                    # s=10,
                    # norm=matplotlib.colors.LogNorm()
                    zorder=-10
                    )
    ax.set_xlim(-20,750)
    ax.set_xlabel('Distance to outlet [m]')
    ax.set_ylabel('Sr [ppm]', c='k')
    # ax.axvline(x=130, c='dimgray', ls=':', lw=3)
    axb.set_ylabel('$^{87}$Sr/$^{86}$Sr [-]', c='k', rotation=270, labelpad = 40)
    ax.set_ylim(0.003, 0.013)
    ax.set_yticks([0.004, 0.006, 0.008, 0.010, 0.012])
    axb.set_ylim(0.705, 0.710)
    axb.ticklabel_format(style='plain')
    axb.ticklabel_format(useOffset=False, style='plain')
    ax.set_title(model_name, fontsize=8)
    ax.invert_xaxis()
    ax.patch.set_visible(False)
    ax.set_zorder(axb.get_zorder()+1)
    
    samp = field[field['Date']=='June 2016']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[1],
                   facecolor='forestgreen',
                   marker='<', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppm'],
                   # facecolor=colors[1],
                   facecolor='darkorange',
                   marker='<', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )
    
    """
    samp = field[field['Date']=='May 2019']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[0],
                   facecolor='forestgreen',
                   marker='^', lw=0.5,
                    s=20,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppm'],
                   # facecolor=colors[0],
                   facecolor='darkorange',
                   marker='^', lw=0.5,
                    s=20,
                    # norm=matplotlib.colors.LogNorm()
                    )
    """
    
    samp = field[field['Date']=='June 2019']
    axb.scatter(samp['d_mouth'],
                   samp['87Sr_86Sr'],
                   # facecolor=colors[2],
                   facecolor='forestgreen',
                   marker='>', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )    
    ax.scatter(samp['d_mouth'],
                   samp['Sr_ppm'],
                   # facecolor=colors[2],
                   facecolor='darkorange',
                   marker='>', lw=0.5,
                    s=50,
                    # norm=matplotlib.colors.LogNorm()
                    )
    
    for ix, dm in zip(field.index, field.d_mouth):
        index = np.argmin(np.abs(resume_mask['distance_mask_riv']-dm))
        print(index)
        resume_mask.loc[index,'SrR_obs'] = field.loc[ix,'87Sr_86Sr']
        resume_mask.loc[index,'SrC_obs'] = field.loc[ix,'Sr_ppm']
    
    resume_mask_dropna = resume_mask.dropna(subset=['SrR_obs'])
    
    the_diff = resume_mask_dropna['Rsr_riv_calc'] - resume_mask_dropna['SrR_obs']
    value=np.sqrt(np.sum((the_diff)**2)/len(resume_mask_dropna))
    if value == 0:
        value = np.nan
    print(value)
    data_explo.loc[cpt,'RMSE'] = value
              
    plt.tight_layout()
    
    fig.savefig(fig_path+'PLOT ACCUMUL SR'+'_'+model_name+'.png', dpi=300, bbox_inches='tight')

    cpt+=1

data_explo.to_csv(BV.simulations_folder+'/results_'+typ+'_rmse'+'.csv', sep=';')

#%% ARCH - PLOT ONLY RTD

dem = rasterio.open("C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_box_buff_dem.tif")

list_selects = list_model_name

shp_contour = gpd.read_file(BV.geographic.watershed_shp)
shp_box = gpd.read_file(stable_folder+'geographic/box_buff.shp')
stre = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2.shp')

wt_mask = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/watershed_mask.shp')
subwt_flow = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/subbasin/subbasin_Flowrate/watershed_contour.shp')
subwt_point = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/snap_flowrate.shp')

wbt.raster_to_vector_points(
    BV.geographic.watershed_dem, 
    'C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp')
wbt.extract_raster_values_at_points(down_path, 
                                    'C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp', 
                                    out_text=False)
dem_down = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_dem_pts.shp')

wbt.extract_raster_values_at_points('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/geographic/watershed_box_buff_dem.tif', 
                                    'C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp', 
                                    out_text=False)
wbt.extract_raster_values_at_points(down_path, 
                                    'C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp', 
                                    out_text=False)
riv_pts = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/L_Quiock_creek2_pt.shp')
riv_pts = gpd.read_file('C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/Quiock3/results_stable/hydrology/test.shp')

dem_data = imageio.imread(BV.geographic.watershed_dem)
dem_data[dem_data<0] = np.nan

for model_name in list_selects[:]:
    
    resume_mask = pd.read_csv(BV.simulations_folder+'/'+model_name+'/resume_clean.csv',
                         sep=';')
    
    print(resume_mask['distance_mask_riv'].min())
    resume_mask['distance_mask_riv'] = resume_mask['distance_mask_riv'] - resume_mask['distance_mask_riv'].min()
    
    # shp_ending = gpd.read_file(simulations_folder+
    #                               model_name+'/'+'_pathlines/'+
    #                               'ending_years_masked.shp') # time in years !
    
    # shp_starting_shal = gpd.read_file(simulations_folder+
    #                           model_name+'/'+'_pathlines/'+
    #                           'shp_starting_shal.shp') # time in years !
    
    # shp_starting_deep = gpd.read_file(simulations_folder+
    #                           model_name+'/'+'_pathlines/'+
    #                           'shp_starting_deep.shp') # time in years !
    
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    wbt.extract_raster_values_at_points(down_path, 
                                        simulations_folder+model_name+'/'+'_pathlines/'+'shp_ending_shal.shp', 
                                        out_text=False)
    wbt.extract_raster_values_at_points(down_path, 
                                        simulations_folder+model_name+'/'+'_pathlines/'+'shp_ending_deep.shp', 
                                        out_text=False)
    
    shp_ending_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    shp_ending_shal = shp_ending_shal[shp_ending_shal['VALUE1']>0]
    shp_ending_shal = shp_ending_shal.clip(shp_contour)
    
    shp_ending_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    shp_ending_deep = shp_ending_deep[shp_ending_deep['VALUE1']>0]
    shp_ending_deep = shp_ending_deep.clip(shp_contour)
    
    fig, ax = plt.subplots(1,1, figsize=(5.5,3))
    axb = ax.twinx()
    
    # ax.scatter(shp_ending_shal['VALUE1'],shp_ending_shal['time'])
    # ax.scatter(shp_ending_deepl['VALUE1'],shp_ending_deepl['time'])
    
    ax.vlines(x=shp_ending_shal['VALUE1']-83.28427,
              ymin=shp_ending_shal['time']*0,
              ymax=shp_ending_shal['time'], color='dodgerblue', lw=0.25)
    ax.vlines(x=shp_ending_deep['VALUE1']-83.28427,
              ymin=shp_ending_deep['time']*0,
              ymax=shp_ending_deep['time'], color='red', lw=0.25)

    ax.set_xlabel('Distance to outlet [m]')
    ax.set_ylabel('Time [y]')
    # cb = fig.colorbar(s)
    # cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)
    # ax.plot(471, 2.8, lw=2, marker='s', color='white', mew=2, markeredgecolor='k')
    ax.set_xlim(-20,800)
    ax.set_ylim(1,1000)
    # axb.set_ylim(0,0.1)
    ax.invert_xaxis()
    ax.patch.set_visible(False)
    # ax.set_zorder(axb.get_zorder()+1)
    ax.set_yscale('log')
    
    ax.set_title(model_name, fontsize=8)
    
    # axb.plot(dem_down['VALUE1']-83.28427, dem_down['VALUE'], c='saddlebrown')
    # axb.plot(riv_pts['VALUE1_1']-83.28427, riv_pts['VALUE1'])
    thev = pd.Series(np.nanmin(dem_data, axis=0))
    thev.index = thev.index*5
    # thev.iloc[-1] = 0
    thedem = pd.Series(np.nanmin(dem_data, axis=0))
    # thedem.iloc[-1] = 200
    # thedem = thedem.dropna()
    # thev = thev.dropna()
    axb.plot(thev.index[::-1], thedem, c='saddlebrown', lw=2)
    axb.set_ylabel('Elevation [m]', rotation=270, labelpad=25)
    axb.set_ylim(200,325)
    axb.set_yticks([200, 225, 250, 275, 300, 325])
    # axb.set_yticklabels([220, 260, 300])
    # axb.invert_xaxis()
    
    # ax.patch.set_visible(False)
    axb.set_zorder(ax.get_zorder()+10)
        
    plt.tight_layout()
    
    # fig.savefig(fig_path+'PLOT CLEAN RTD'+'_'+model_name+'.png', dpi=300, bbox_inches='tight')


