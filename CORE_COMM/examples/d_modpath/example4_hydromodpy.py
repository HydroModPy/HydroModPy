# -*- coding: utf-8 -*-
"""
Created on Fri Jan  6 16:15:34 2023

@author: ronan
"""

#%% INFO
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

from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from calibration import calib_root, calib_analysis, calib_basis
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display

#%% USERS

# user_path = "Martin"
user_path = "Ronan"

if user_path=="Alexandre":
    data_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy/'
    
elif user_path=="Jean-Raynald":
    data_path= "D:/codes-data/HydroModPy_Data/"
    out_path = "D:/results/HydroModPy/"
    
elif user_path=="Ronan":
    data_path= "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/QUIOCK/"
    out_path = "D:/Users/abherve/EXAMPLES/"
  
elif user_path=="Martin":
    data_path= "C:/Users/Martin Le Mesnil/Travail/data/CALIB/"
    out_path = "C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/"

else:
    print("Define a well-validated name of user")

#%% ASSIGNED PATHS

watershed_name = 'Quiock'

library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

if watershed_name == 'Quiock':
    dem_name = "BasseTerre_dem_clip.tif"
    from_shp = None
    types_obs = ['L_Quiock_creek2']
    fields_obs = ['fid']
    
from_dem = False
cell_size = None
    
climate_path =  None
dem_path = os.path.join(data_path,dem_name)
geology_path = None
hydrology_path = os.path.join(data_path)
hydrometry_path = None # add hydrometry data for automatic download
intermittency_path = None # add intermittency data for automatic download
modflow_path = os.path.join(data_path,'modflow')
oceanic_path = None
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

#%% LOAD WATERSHED

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

#%% ADD DATA IN THE WATERSHED

BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

BV.add_oceanic('None')
BV.add_hydrodynamic()
BV.add_forcing()
    
watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% DICHOTOMY STREAMS

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

area = BV.geographic.area
    
recharge = 2 / 365  # m/y to m/d

BV.forcing.update_recharge(recharge, sim_state='steady') #

BV.hydrodynamic.update_porosity(0.01)
BV.hydrodynamic.update_hyd_cond(2)
BV.hydrodynamic.update_nlay(1)
BV.hydrodynamic.update_thickness(300)
BV.hydrodynamic.update_bottom(-100)
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

#%% AQUIFER CASES

# Import K calibrated
df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
Koptim = float('{:.1e}'.format(df.loc[0][1]))

######################
case = 1
######################

# Aquifer
thick = 300 # m
bottom = -100 # aquifer flat or not

# Discretization
nlay = 50 # vertical discrtization
thick_exp = 1.2 # exponential decay of nlay with depth

# Climate
recharge = 2 / 365 # mm/s to m/j

# Porosity
Sy = 0.1

if case == 1:
    # Hydraulic cond.
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    k1 = Koptim * 3600 * 24 # lower layer
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'case1'

if case == 2:
    # Hydraulic cond.
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    k1 = Koptim * 3600 * 24 * 10 # lower layer
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'case2'

if case == 3:
    # Hydraulic cond.
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    k1 = Koptim / 10 * 3600 * 24 # lower layer
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'case3'

if case == 4:
    # Hydraulic cond.
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0.02 # exponential decay of K with depth : 0.02
    # Vertical
    k1 = None # lower layer
    verti_k = None # "k1", or None
    # Name
    typ = 'case4'

#%% RUN MODEL

# Option
sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = True # run modpath particle tracking if True
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
BV.forcing.update_recharge(recharge, sim_state=sim_state) #

# Label
list_model_name = []
list_of_success = []
list_flow_model = []

# Update properties
compt = 1

BV.hydrodynamic.update_nlay(nlay) # 1
BV.hydrodynamic.update_bottom(bottom) # None
BV.hydrodynamic.update_cond_decay(cond_decay) # 0
BV.hydrodynamic.update_thick_exp(thick_exp) # 1
BV.hydrodynamic.update_thickness(thick) # 30 / intervient pas si bottom != None

BV.hydrodynamic.update_hyd_cond(k1) 
BV.hydrodynamic.update_porosity(Sy)
  
date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
date_today = date_today.replace('/','-')
date_today = date_today.replace(':','-')
date_today = date_today.replace(' ','_')

model_name = typ+'_'+str(compt)+'_'+\
                 str(Sy*100)+'-'+str(round(k1,2))+'-'+str(thick)+'_'+str(nlay)

if run == True:
    # try:
    print('SIM - ' + model_name)
    success, flow_model = BV.run_modflow(ident=model_name,
                                         modpath_sim=modpath_sim,
                                         sink_fill=sink_fill,
                                         box=box,
                                         verbose=verbose,
                                         post_process=post_process, 
                                         init_rech=init_rech,
                                         verti_k=verti_k)
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

#%%