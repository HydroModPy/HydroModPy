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
data_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/USERS/QUIOCK/"
out_path = "C:/Users/ronan/Documents/SIMULATIONS/GUADELOUPE/"
# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/v1/raw/"
fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/GUADELOUPE/_figures/v1/explor/"
  
print("Define a well-validated name of user")

#%% PATHS

watershed_name = 'Quiock2'

library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

if watershed_name == 'Quiock2':
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
BV.add_subbasin()

#%% DATA

BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

BV.add_oceanic('None')
BV.add_hydrodynamic()
BV.add_forcing()
    
watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% ---- DICHOTOMY

#%% LAUNCH

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
case = 'k0k1'
case = 'calib'
case = 'inter1'
case = 'best1'
case = 'explor1'
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

#%% ---- POST-PROCESS

#%% LOAD MODELS

modpath_sim

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
                                                        calibration_folder=os.path.join(BV.simulations_folder, model_name))
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
            data_explo.loc[cp,'Qsub_obs'] =  2.8 / 1000 * 3600 * 24 # L/s to m3/j            

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

#%% ---- PLOT 1

#%% MULTIOBJECTIVE FUNCTIONS

if not 'data_explo' in globals():
    data_explo = pd.read_csv(BV.simulations_folder+'/results_'+typ+'.csv', sep=';')

fig, ax_l0 = plt.subplots(1,1, figsize=(4,3))
ax_r0 = ax_l0.twinx()

# ax_l1 = ax_l0.twinx()
# ax_l2 = ax_l0.twinx()
# ax_l3 = ax_l0.twinx()

ax_r1 = ax_l0.twinx()
# ax_r2 = ax_l0.twinx()
# ax_r3 = ax_l0.twinx()

# ax_l1.spines["left"].set_position(("axes", -0.2)) # red one
# ax_l2.spines["left"].set_position(("axes", -0.4)) # green one
# ax_l3.spines["left"].set_position(("axes", -0.6)) # red one

# ax_r1.spines["right"].set_position(("axes", 1.2)) # green one
# ax_r2.spines["right"].set_position(("axes", 1.5)) # red one
# ax_r3.spines["right"].set_position(("axes", 1.7)) # green one

def make_patch_spines_invisible(ax):
    ax.set_frame_on(True)
    ax.patch.set_visible(False)
    for sp in ax.spines.values():
        sp.set_visible(False)

# make_patch_spines_invisible(ax_l1)
# make_patch_spines_invisible(ax_l2)
# make_patch_spines_invisible(ax_l3)
# make_patch_spines_invisible(ax_r1)
# make_patch_spines_invisible(ax_r2)
# make_patch_spines_invisible(ax_r3)

# ax_l1.spines["left"].set_visible(True)
# ax_l1.yaxis.set_label_position('left')
# ax_l1.yaxis.set_ticks_position('left')

# ax_l2.spines["left"].set_visible(True)
# ax_l2.yaxis.set_label_position('left')
# ax_l2.yaxis.set_ticks_position('left')

# ax_l3.spines["left"].set_visible(True)
# ax_l3.yaxis.set_label_position('left')
# ax_l3.yaxis.set_ticks_position('left')

# ax_r1.spines["right"].set_visible(True)
# ax_r1.yaxis.set_label_position('right')
# ax_r1.yaxis.set_ticks_position('right')

# ax_r2.spines["right"].set_visible(True)
# ax_r2.yaxis.set_label_position('right')
# ax_r2.yaxis.set_ticks_position('right')

# ax_r3.spines["right"].set_visible(True)
# ax_r3.yaxis.set_label_position('right')
# ax_r3.yaxis.set_ticks_position('right')

# ax_l0.plot(data_explo['k0k1'], (data_explo['D_so']),
#            color='forestgreen', marker='o', lw=3)
# ax_l0.plot(data_explo['k0k1'], (data_explo['D_os']),
#            color='', marker='o', lw=3)
ax_l0.plot(data_explo['k0k1'], (abs(1-(data_explo['D_so']/data_explo['D_os']))),
           color='red', marker='o', lw=2)
ax_l0.set_xscale('log')
ax_l0.set_yscale('log')
# ax_l0.axhline(y=1, c='k', ls='--')
# ax_l0.set_xlim(0.01, 1e3)
ax_l0.set_xlabel('K upper layer / K lower layer')
ax_l0.set_ylabel('Stream network indicator', c='red')
ax_l0.set_title('Calibration criteria')
# ax_l0.axvline(x=6e-1, c='k', ls='--')
ax_l0.axvline(x=2, c='limegreen', ls='--', lw=2)

ax_r0.plot(data_explo['k0k1'], ((data_explo['Qout_sim']/data_explo['Qsub_obs'])),
           color='dodgerblue', marker='o', lw=2)
# ax_r0.set_yscale('log')
# ax_l0.set_ylim(0.1, 30)
ax_r0.set_ylabel('Streamflow indicator', c='dodgerblue', rotation=270, labelpad=+25,)
ax_r0.set_ylim(1, 2)

# ax_r1.plot(data_explo['k0k1'], (data_explo['t_sim']),
#            color='red', marker='o', lw=3)
# ax_r0.set_yscale('log')

ax_r1.spines["right"].set_visible(True)
ax_r1.yaxis.set_label_position('right')
ax_r1.yaxis.set_ticks_position('right')
ax_r1.spines['right'].set_position(('outward', 60))

ax_r1.plot(data_explo['k0k1'], 
           data_explo['RMSE'],
           color='darkorange', marker='o', lw=2)

ax_r1.set_ylabel('RMSE Sr ratio', c='darkorange', rotation=270, labelpad=+25,)

fig.savefig(fig_path+'multiobjective_'+'allcases'+'.png', dpi=300, bbox_inches='tight')

#%% GENERAL DATA PLOT

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
    
    cond_lay = 38 # ==> approx. 40 meters
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
                                        
#%% ---- PLOT 2

#%% ## PATHLINES - CROSS SECTION

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

for model_name in list_selects[:1]:

    ### MODEL ###

    mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')

    fig, ax = plt.subplots(1,1, figsize=(7, 3))
    # modelmap = flopy.plot.PlotMapView(model=mf)
    # linecollection = modelmap.plot_grid(linewidth=0.5, color='royalblue')
    # line_cross = np.array([(40, 80), (100, 50)])
    # xsect = flopy.plot.PlotCrossSection(model=mf, line={'line': line_cross})
    xsect = flopy.plot.PlotCrossSection(model=mf, line={'row': 50})
    xsect.plot_grid()
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
    ax.set_ylim(0,400)
    xlims = ax.get_xlim()
    # ax.set_xlim(150,1000)
    
    head_profile = pc.get_array()[0:170]
    
    # xsect.plot_pathline(pth_data[3000:3001], method='all', colors='k',
    #                     head=pc.get_array())
    # xsect.plot_endpoint(e, direction='ending')
    
    for a, b in enumerate(pth_data):
        b_xmin = b.x.min()/5
        b_xmax = b.x.max()/5
        head_restr = head_profile[int(b_xmin):int(b_xmax)]
        # if b.particleid[0] in np.random.choice(indices_layers[0], 100):
        # if b.particleid[0] in indices_layers[0]:
        if b.particleid[0] in indices_layers_rdm[1]:
            # if len(head_restr)>0:
            #     head_max = head_restr.max()
            #     if b.z.max()<head_max:
            ax.plot(b.x, b.z, color='red', lw=0.5)
        # if b.particleid[0] in np.random.choice(indices_layers[1], 100):
        # if b.particleid[0] in indices_layers[1]:
        if b.particleid[0] in indices_layers_rdm[0]:
            # if len(head_restr)>0:
            #     head_max = head_restr.max()
            #     if b.z.max()<head_max:
            ax.plot(b.x, b.z, color='blue', lw=0.5)

#%% ## ELEVATION DISCHARGE ALL - ALONG RIVERS

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

for model_name in list_selects[:]:
    
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
    ###########################################################################

    acc_masked = np.ma.masked_where(acc <= acc.mean(), acc)
    down_masked = np.ma.masked_array(down, mask=acc_masked.mask)
    
    fig, (ax1, ax2) = plt.subplots(1,2, figsize=(8,3))
    ax1.imshow(acc_masked)
    ax1.set_title('Cumulated flux')
    ax2.imshow(down_masked)
    ax2.set_title('Downslope lengths')
    
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    s = ax.scatter(down, dem_masked, marker='_', lw=3, c=acc_masked,
                   s=20,
                   # norm=matplotlib.colors.LogNorm()
                   )
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')
    cb = fig.colorbar(s)
    cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)
    ax.invert_xaxis()

#%% DISCHARGE RED/BLUE - ALONG RIVERS

# indices_layers = [deepid, shalid]

"""
acc_masked = np.ma.masked_where(acc <= 0, acc)
down_masked = np.ma.masked_array(down, mask=acc_masked.mask)

fig, ax = plt.subplots(1,1, figsize=(6,3))
s = ax.scatter(down, acc_masked, marker='_', lw=3, color='k',
               s=20,
               # norm=matplotlib.colors.LogNorm()
               )
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Disharge [m3/J]')
# cb = fig.colorbar(s)
# cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)
ax.invert_xaxis()
"""

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
    ###########################################################################
    
    # acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
    #                           'accumulation_flux_t(0).tif')
    acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                              'outflow_drain_t(0).tif')
    acc_mask = np.ma.masked_where(dem.read(1) < -100, acc_flux)
    acc_mask = acc_mask.filled(np.nan)
    acc_mask[acc_mask<=0] = np.nan
    
    def flatten_on_xy(x):
        XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
        table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
        return table
    
    ### ACCUMULATION TOTAL
    flat_acc = flatten_on_xy(acc_mask)
    flat_acc = pd.DataFrame(flat_acc)
    flat_acc = flat_acc.dropna()
    flat_acc[0] = flat_acc[0] / 24 / 3600 * 1000
    # plt.plot(flat_acc[0], c='k')
    flat_cum_acc = flat_acc.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
    flat_cum_acc[3] = flat_cum_acc[0].cumsum() # 3 is cumulated on sum xaxis in 1
    
    ### ACCUMULATION DEEP
    h = 0
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    res_time = np.ma.masked_where(dem_data <= -100, res_time)
    res_time = res_time.filled(np.nan)
    res_time[res_time<=0] = np.nan
    res_time[dem_data<=0] = np.nan
    # res_count = res_count - 1
    res_count = np.ma.masked_where(res_count <= 0, res_count)
    res_count = np.ma.masked_where(dem_data <= -100, res_count)
    res_count = res_count.filled(np.nan)
    res_count[res_count<=0] = np.nan
    res_count[dem_data<=0] = np.nan
    res_count = np.ma.masked_invalid(res_count)
    
    acc_deep = np.ma.array(acc_mask, mask=res_count.mask)
    acc_deep = acc_deep.filled(np.nan)
    flat_deep = flatten_on_xy(acc_deep)
    flat_deep = pd.DataFrame(flat_deep)
    flat_deep = flat_deep.dropna()
    flat_deep[0] = flat_deep[0] / 24 / 3600 * 1000
    # plt.plot(flat_deep[0], c='r')
    flat_cum_deep = flat_deep.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
    flat_cum_deep[3] = flat_cum_deep[0].cumsum()
    
    ### ACCUMULATION SHAL
    h = 1
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    res_time = np.ma.masked_where(dem_data <= -100, res_time)
    res_time = res_time.filled(np.nan)
    res_time[res_time<=0] = np.nan
    res_time[dem_data<=0] = np.nan
    res_count = res_count - 1
    res_count = np.ma.masked_where(res_count <= 0, res_count)
    res_count = np.ma.masked_where(dem_data <= -100, res_count)
    res_count = res_count.filled(np.nan)
    res_count[res_count<=0] = np.nan
    res_count[dem_data<=0] = np.nan
    res_count = np.ma.masked_invalid(res_count)
    
    acc_shal = np.ma.array(acc_mask, mask=res_count.mask)
    acc_shal = acc_shal.filled(np.nan)
    flat_shal = flatten_on_xy(acc_shal)
    flat_shal = pd.DataFrame(flat_shal)
    flat_shal = flat_shal.dropna()
    flat_shal[0] = flat_shal[0] / 24 / 3600 * 1000 # m3/j to L/s
    # plt.plot(flat_shal[0], c='b')
    flat_cum_shal = flat_shal.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
    flat_cum_shal[3] = flat_cum_shal[0].cumsum()
    
    # plt.plot(flat_acc[0], c='k', lw=0, marker='.')
    # plt.plot(flat_shal[0], c='b', lw=0, marker='.')
    # plt.plot(flat_deep[0], c='r', lw=0, marker='.')
    
    ### PREPARE
    flat_acc = flat_acc.reset_index()
    flat_acc = flat_acc.set_index(flat_acc[1])
    flat_shal = flat_shal.reset_index()
    flat_shal = flat_shal.set_index(flat_shal[1])
    flat_deep = flat_deep.reset_index()
    flat_deep = flat_deep.set_index(flat_deep[1])

    ### FIGURE
    fig, ax = plt.subplots(1,1, figsize=(4.5,2.5))
    axb = ax.twinx()
    ax.set_zorder(10)
    ax.patch.set_visible(False)
    
    axb.plot(dem_data.min(axis=0), color='saddlebrown', ls='-', lw=2, zorder=-1)
    
    axb.set_ylabel('Elevation [m]', rotation=270, labelpad=25)
    axb.set_ylim(200,330)
    axb.set_yticks([220, 260, 300])
    axb.set_yticklabels([220, 260, 300])
    
    # axb.set_zorder(ax.get_zorder() - 1)
    ax.patch.set_visible(False)
    # axb.plot(flat_cum_acc.index, flat_cum_acc[0], c='k', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
    # axb.plot(flat_cum_shal.index, flat_cum_shal[0], c='b', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
    # axb.plot(flat_cum_deep.index, flat_cum_deep[0], c='r', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
    # ax.plot(flat_cum_acc.index, flat_cum_acc[3], c='k', lw=1, marker='.', ms=5, zorder=1)
    # ax.plot(flat_cum_shal.index, flat_cum_shal[3], c='b', lw=1, marker='.', ms=5, zorder=1)
    # ax.plot(flat_cum_deep.index, flat_cum_deep[3], c='r', lw=1, marker='.', ms=5, zorder=1)
    
    ax.step(flat_cum_acc.index, flat_cum_acc[3], c='k', lw=2, marker='.', ms=0, zorder=10)
    ax.step(flat_cum_shal.index, flat_cum_shal[3], c='b', lw=2, marker='.', ms=0, zorder=10)
    ax.step(flat_cum_deep.index, flat_cum_deep[3], c='r', lw=2, marker='.', ms=0, zorder=10)
    
    # ax.set_xlim(60, 160)
    ax.set_ylim(-0.5, 10)
    ax.set_xlabel('*5 Distance [m]')
    ax.set_ylabel('Discharge [L/s]')
    
    ax.axvline(x=130, c='dimgray', ls=':', lw=3)
    
    ax.set_xlim(0,160)
    
    ax.set_xticks([0,40,80,120,160])
    
    # plt.tight_layout()
    
    ax.set_title(model_name, fontsize=8)
    
    fig.savefig(fig_path+'discharge_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FLOWPATHS RED/BLUE - ALONG RIVERS

# indices_layers = [deepid, shalid]

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
    ###########################################################################

    color_layers = ['darkred', 'blue']
    
    fig, ax = plt.subplots(1,1, figsize=(4.5,2.5))   
    axb = ax.twinx()
    
    h = 1
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
            
    res_time = np.ma.masked_where(res_time < 0, res_time)
    res_time = np.ma.masked_where(dem_data < -100, res_time)
    res_time = res_time.filled(np.nan)
    res_time[res_time<0] = np.nan
    res_time[dem_data<0] = np.nan
    flat_res = flatten_on_xy(res_time)
    flat_res = pd.DataFrame(flat_res)
    flat_res = flat_res.dropna()
    
    res_count = np.ma.masked_where(res_count < 0, res_count)
    res_count = np.ma.masked_where(dem_data < -100, res_count)
    res_count = res_count.filled(np.nan)
    res_count[res_count<0] = np.nan
    res_count[dem_data<0] = np.nan
    flat_cts = flatten_on_xy(res_count)
    flat_cts = pd.DataFrame(flat_cts)
    flat_cts = flat_cts.dropna()
    flat_cts = flat_res.groupby(1)
    flat_cts = flat_cts.agg({0: "nunique"})
    
    ax = ax
    # ax.plot(flat_acc[:,1], flat_acc[:,0], color='k', lw=2)
    # ax.step(flat_acc[:,1], flat_acc[:,0], color='k', lw=3)
    # ax.fill_between(flat_acc.iloc[:][1], 0, flat_acc.iloc[:][0], lw=2)
    # ax.scatter(flat_res[1], flat_res[0], c='dodgerblue', lw=0, s=20,
    #            alpha=0.2, marker='o')
    ax.bar(flat_res[1], flat_res[0], width=1,
            color='skyblue', lw=0, zorder=10)
    # ax.step(flat_res[1], flat_res[0],
    #         color='dodgerblue',
    #                 marker=None, markeredgecolor='none',
    #                 markersize=5, lw=1, label='upstream',
    #                 where='pre', zorder=10)
    # axb.plot(flat_cts.index, flat_cts[0], c='navy', lw=2,
    #            alpha=1)
    
    h = 0
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
            
    res_time = np.ma.masked_where(res_time < 0, res_time)
    res_time = np.ma.masked_where(dem_data < -100, res_time)
    res_time = res_time.filled(np.nan)
    res_time[res_time<0] = np.nan
    res_time[dem_data<0] = np.nan
    flat_res = flatten_on_xy(res_time)
    flat_res = pd.DataFrame(flat_res)
    flat_res = flat_res.dropna()
    
    res_count = np.ma.masked_where(res_count < 0, res_count)
    res_count = np.ma.masked_where(dem_data < -100, res_count)
    res_count = res_count.filled(np.nan)
    res_count[res_count<0] = np.nan
    res_count[dem_data<0] = np.nan
    flat_cts = flatten_on_xy(res_count)
    flat_cts = pd.DataFrame(flat_cts)
    flat_cts = flat_cts.dropna()
    flat_cts = flat_res.groupby(1)
    flat_cts = flat_cts.agg({0: "nunique"})

    # fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))   
    # axb = ax.twinx()
    
    ax = ax
    # ax.plot(flat_acc[:,1], flat_acc[:,0], color='k', lw=2)
    # ax.step(flat_acc[:,1], flat_acc[:,0], color='k', lw=3)
    # ax.fill_between(flat_acc.iloc[:][1], 0, flat_acc.iloc[:][0], lw=2)
    # ax.scatter(flat_res[1], flat_res[0], c='red', lw=0, s=20,
    #            alpha=0.2, marker='o')
    # ax.step(flat_res[1], flat_res[0],
    #         color='red',
    #                 marker=None, markeredgecolor='none',
    #                 markersize=5, lw=1, label='upstream',
    #                 where='pre', zorder=0)
    ax.bar(flat_res[1], flat_res[0], width=1,
            color='tomato', lw=0, zorder=0)
    # axb.plot(flat_cts.index, flat_cts[0], c='darkred', lw=2,
    #            alpha=1)
    
    # ax.set_xlim(60, 160)
    ax.set_ylim(1, 1000)
    ax.set_xlabel('*5 Distance [m]')
    ax.set_ylabel('t [y]')
    
    # axb.plot(dem_data.min(axis=0), color='saddlebrown', lw=2)
    axb.set_ylabel('Elevation [m]', rotation=270, labelpad=25)
    # axb.set_xlim(60, 160)
    # axb.set_ylim(1, None)
    # axb.set_ylabel('Count flowpaths', rotation=270, labelpad=30)
    
    ax.axvline(x=130, c='dimgray', ls=':', lw=3)
    
    ax.set_xlim(0,160)
    # plt.xticks(ticks=plt.xticks()[0][0:], labels=5 * np.array(plt.xticks()[0][0:], dtype=np.int))
    # ax.set_xticks([0,200/5,400/5,600/5,800/5])
    
    ax.set_xticks([0,40,80,120,160])
    
    ax.set_yscale('log')
    
    # ax.set_xlim(0,150)
    
    # plt.tight_layout()
    
    # fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
    #             'Times and counts'+'.png', dpi=300, bbox_inches='tight')
    
    # fig.savefig(fig_path+'residence_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
    ax.set_title(model_name, fontsize=8)
    
    fig.savefig(fig_path+'residence_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% CONCENTRATION SR - ALON RIVERS

# idx_x = list(pd.DataFrame(flatten_on_xy(acc_flux)).index)
# idx_x = pd.DataFrame(flatten_on_xy(acc_flux))

# indices_layers = [deepid, shalid]

list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
list_selects = list_model_name

cp = 0

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
    ###########################################################################
    
    # acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
    #                           'accumulation_flux_t(0).tif')
    acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                              'outflow_drain_t(0).tif')
    acc_mask = np.ma.masked_where(dem.read(1) < -100, acc_flux)
    acc_mask = acc_mask.filled(np.nan)
    acc_mask[acc_mask<=0] = np.nan
    
    def flatten_on_xy(x):
        XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
        table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
        return table
    
    ### ACCUMULATION TOTAL
    flat_acc = flatten_on_xy(acc_mask)
    flat_acc = pd.DataFrame(flat_acc)
    flat_acc = flat_acc.dropna()
    flat_acc[0] = flat_acc[0] / 24 / 3600 * 1000
    # plt.plot(flat_acc[0], c='k')
    flat_cum_acc = flat_acc.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
    flat_cum_acc[3] = flat_cum_acc[0].cumsum() # 3 is cumulated on sum xaxis in 1
    
    ### ACCUMULATION DEEP
    h = 0
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    res_time = np.ma.masked_where(dem_data <= -100, res_time)
    res_time = res_time.filled(np.nan)
    res_time[res_time<=0] = np.nan
    res_time[dem_data<=0] = np.nan
    # res_count = res_count - 1
    res_count = np.ma.masked_where(res_count <= 0, res_count)
    res_count = np.ma.masked_where(dem_data <= -100, res_count)
    res_count = res_count.filled(np.nan)
    res_count[res_count<=0] = np.nan
    res_count[dem_data<=0] = np.nan
    res_count = np.ma.masked_invalid(res_count)
    
    acc_deep = np.ma.array(acc_mask, mask=res_count.mask)
    acc_deep = acc_deep.filled(np.nan)
    flat_deep = flatten_on_xy(acc_deep)
    flat_deep = pd.DataFrame(flat_deep)
    flat_deep = flat_deep.dropna()
    flat_deep[0] = flat_deep[0] / 24 / 3600 * 1000
    # plt.plot(flat_deep[0], c='r')
    flat_cum_deep = flat_deep.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
    flat_cum_deep[3] = flat_cum_deep[0].cumsum()
    
    ### ACCUMULATION SHAL
    h = 1
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    res_time = np.ma.masked_where(dem_data <= -100, res_time)
    res_time = res_time.filled(np.nan)
    res_time[res_time<=0] = np.nan
    res_time[dem_data<=0] = np.nan
    res_count = res_count - 1
    res_count = np.ma.masked_where(res_count <= 0, res_count)
    res_count = np.ma.masked_where(dem_data <= -100, res_count)
    res_count = res_count.filled(np.nan)
    res_count[res_count<=0] = np.nan
    res_count[dem_data<=0] = np.nan
    res_count = np.ma.masked_invalid(res_count)
    
    acc_shal = np.ma.array(acc_mask, mask=res_count.mask)
    acc_shal = acc_shal.filled(np.nan)
    flat_shal = flatten_on_xy(acc_shal)
    flat_shal = pd.DataFrame(flat_shal)
    flat_shal = flat_shal.dropna()
    flat_shal[0] = flat_shal[0] / 24 / 3600 * 1000 # m3/j to L/s
    # plt.plot(flat_shal[0], c='b')
    flat_cum_shal = flat_shal.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
    flat_cum_shal[3] = flat_cum_shal[0].cumsum()
    
    # plt.plot(flat_acc[0], c='k', lw=0, marker='.')
    # plt.plot(flat_shal[0], c='b', lw=0, marker='.')
    # plt.plot(flat_deep[0], c='r', lw=0, marker='.')
    
    ### PREPARE
    flat_acc = flat_acc.reset_index()
    flat_acc = flat_acc.set_index(flat_acc[1])
    flat_shal = flat_shal.reset_index()
    flat_shal = flat_shal.set_index(flat_shal[1])
    flat_deep = flat_deep.reset_index()
    flat_deep = flat_deep.set_index(flat_deep[1])
    
    ### SPECIFIC
    idx_x = np.arange(0, dem_data.shape[1], 1)
    flat_flux = pd.DataFrame(index=idx_x)
    flat_flux['Qriv'] = flat_cum_acc[3]
    flat_flux['Qdeep'] = flat_cum_deep[0]
    flat_flux['Qshal'] = flat_cum_shal[0]
    first_index = flat_flux['Qriv'].first_valid_index()
    flat_flux = flat_flux[first_index:]
    flat_flux = flat_flux.fillna(0)
    
    for i in flat_flux.index:
        if i == first_index:
            print(i)
            nomin = (0.02*flat_flux.loc[i,'Qriv'])+ \
                    (1.1*flat_flux.loc[i,'Qdeep'])+ \
                    (0.02*flat_flux.loc[i,'Qshal'])
            denom = flat_flux.loc[i,'Qriv'] + flat_flux.loc[i,'Qdeep'] + flat_flux.loc[i,'Qshal']
            if denom == 0 :
                denom = 1
            flat_flux.loc[i,'Csr_riv'] = nomin / denom
        else:
            nomin = (flat_flux.loc[i-1,'Csr_riv']*flat_flux.loc[i-1,'Qriv'])+ \
                                           (1.1*flat_flux.loc[i,'Qdeep'])+ \
                                           (0.02*flat_flux.loc[i,'Qshal'])
            denom = flat_flux.loc[i-1,'Qriv'] + flat_flux.loc[i,'Qdeep'] + flat_flux.loc[i,'Qshal']
            if denom == 0 :
                denom = 1
            flat_flux.loc[i,'Csr_riv'] = nomin / denom
    
    for i in flat_flux.index:
        if i == first_index:
            print(i)
            nomin = (0.7092*flat_flux.loc[i,'Csr_riv']*flat_flux.loc[i,'Qriv'])+ \
                    (0.7041*1.1*flat_flux.loc[i,'Qdeep'])+ \
                    (0.7092*0.02*flat_flux.loc[i,'Qshal'])
            denom = (flat_flux.loc[i,'Qriv']*flat_flux.loc[i,'Csr_riv']) + \
                    (flat_flux.loc[i,'Qdeep']*1.1) + \
                    (flat_flux.loc[i,'Qshal']*0.02)
            if denom == 0 :
                denom = 1
            flat_flux.loc[i,'Rsr_riv'] = nomin / denom
        else:
            nomin = (flat_flux.loc[i-1,'Rsr_riv']*flat_flux.loc[i-1,'Csr_riv']*flat_flux.loc[i-1,'Qriv']) + \
                    (0.7041*1.1*flat_flux.loc[i,'Qdeep']) + \
                    (0.7092*0.02*flat_flux.loc[i,'Qshal'])
            denom =  (flat_flux.loc[i-1,'Qriv']*flat_flux.loc[i-1,'Csr_riv']) + \
                     (flat_flux.loc[i,'Qdeep']*1.1) + \
                     (flat_flux.loc[i,'Qshal']*0.02)
            if denom == 0 :
                denom = 1
            flat_flux.loc[i,'Rsr_riv'] = nomin / denom
     
    fig, ax = plt.subplots(1,1, figsize=(4.5,2.5))    
    axb = ax.twinx()
                                  
    ax.plot(flat_flux['Csr_riv'], c='tomato', marker='o', lw=0, mec='darkorange', mew=1, mfc='none')
    axb.plot(flat_flux['Rsr_riv'], c='grey', marker='o', lw=0, mec='darkviolet', mew=1, mfc='none')
    # ax.step(flat_flux.index, flat_flux['Csr_riv'], color='tomato',
    #         # marker=None, markeredgecolor='none',
    #         # markersize=5, lw=1, label='upstream',
    #         # where=step
    #         )
    # axb.step(flat_flux.index, flat_flux['Rsr_riv'], c='grey')
    # plt.yscale('log')
    
    # ax.set_xlim(60, 160)
    # ax.set_ylim(1, None)
    ax.set_xlabel('*5 Distance [m]')
    ax.set_ylabel('Sr Concenration', c='darkorange')
    ax.axvline(x=130, c='dimgray', ls=':', lw=3)
    ax.set_ylim(0, 1)
    
    ax.set_xlim(0,160)
    # plt.xticks(ticks=plt.xticks()[0][0:], labels=5 * np.array(plt.xticks()[0][0:], dtype=np.int))
    # ax.set_xticks([0,200/5,400/5,600/5,800/5])
    
    ax.set_xticks([0,40,80,120,160])
    # ax.set_xticklabels([0,40*5,80*5,120*5,160*5])
    
    # axb.set_xlim(0,150)
    # axb.set_ylim(1, None)
    axb.set_ylabel('Sr Ratio', c='darkviolet', rotation=270, labelpad = 30)
    axb.set_ylim(0.704, 0.710)
    axb.ticklabel_format(style='plain')
    axb.ticklabel_format(useOffset=False, style='plain')
    # axb.ticklabel_format(style='plain', axis='y')
    
    # flat_flux.to_csv(simulations_folder + '/' + model_name + '/' +'_figures/' + 
    #             'q c r'+'.csv', sep=';')
    
    # fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
    #             'Concentration and Ratio Sr'+'.png', dpi=300, bbox_inches='tight')
    
    ax.set_title(model_name, fontsize=8)
    
    do_u = [70,80,90,100,110]
    o_u = [0.7090]*5
    do_d = [130,140]
    o_d = [0.7060]*2
    axb.plot(do_u, o_u, color='k', lw=0, marker='o', ms=5)
    axb.plot(do_d, o_d, color='k', lw=0, marker='o', ms=5)
        
    fig.savefig(fig_path+'concentration_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
    d = do_u + do_d
    o = o_u + o_d
    list_sim = []
    for i in flat_flux.index:
        if i in d:
            while flat_flux.loc[i,'Rsr_riv'] == 0:
                i += 1
            else:
                list_sim.append(flat_flux.loc[i,'Rsr_riv'])
    
    value = np.sqrt(np.nansum((np.array(list_sim)-np.array(o))**2)/len(o))
    data_explo.loc[cp,'RMSE'] = value
    
    fig, ax = plt.subplots(1,1, figsize=(4,4))
    ax.plot(o, list_sim, marker='o', c='forestgreen', lw = 0, ms=13)
    ax.set_xlim(0.704, 0.710)
    ax.set_ylim(0.704, 0.710)
    ax.ticklabel_format(style='plain')
    ax.ticklabel_format(useOffset=False, style='plain')
    ax.plot((0.704, 0.710),(0.704, 0.710), c='k', ls='--', zorder=-1)
    ax.set_xlabel('Observed Sr ratio')
    ax.set_ylabel('Simulated Sr ratio')
    
    fig.savefig(fig_path+'obsVSsim_'+model_name+'.png', dpi=300, bbox_inches='tight')

    cp += 1

#%% ---- PLOT 3

#%% STARTING ENDING PATHLINES

list_selects = list_model_name

shp_contour = gpd.read_file(BV.geographic.watershed_shp)
shp_box = gpd.read_file(stable_folder+'geographic/box_buff.shp')

for model_name in list_selects[:]:
    
    shp_ending = gpd.read_file(simulations_folder+
                                  model_name+'/'+'_pathlines/'+
                                  'ending_years_masked.shp') # time in years !
    
    shp_starting_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_starting_shal.shp') # time in years !
    shp_starting_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_starting_deep.shp') # time in years !
    
    shp_ending_shal = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_shal.shp') # time in years !
    shp_ending_deep = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'shp_ending_deep.shp') # time in years !
    
    shp_pathlines_spings = gpd.read_file(simulations_folder+
                              model_name+'/'+'_pathlines/'+
                              'pathlines_1000_springs.shp')

    fig, axs = plt.subplots(2,1, figsize=(6,3))
    axs.ravel()
    
    ax=axs[0]
    shp_contour.plot(ax=ax, facecolor='none', lw=2, zorder=10)
    shp_box.plot(ax=ax, facecolor='none', lw=2, zorder=10)
    # ax.set_title('Pathlines deep vs. shallow', fontsize=10)
    shp_starting_shal.plot(ax=ax, color='dodgerblue', lw=0, markersize=4)
    shp_starting_deep.plot(ax=ax, color='tomato', lw=0, markersize=4)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')
    
    ax=axs[1]
    shp_contour.plot(ax=ax, facecolor='none', lw=2, zorder=10)
    shp_box.plot(ax=ax, facecolor='none', lw=2, zorder=10)
    # ax.set_title('Pathlines deep vs. shallow', fontsize=10)
    shp_ending_shal[shp_ending_shal.time>0].plot(ax=ax, color='dodgerblue', lw=0, markersize=4)
    shp_ending_deep.plot(ax=ax, color='tomato', lw=0, markersize=4)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')
    
    fig.suptitle( model_name, y=0.95, fontsize=5)
    fig.tight_layout()
    
    fig.savefig(fig_path+'starting_ending_'+model_name+'.png', dpi=300, bbox_inches='tight')
    
    fig, ax = plt.subplots(1,1, figsize=(3,3))
    shp_contour.plot(ax=ax, facecolor='none', lw=2, zorder=10)
    shp_box.plot(ax=ax, facecolor='none', lw=2, zorder=10)
    ep = shp_ending.plot(ax=ax, column='time', cmap='jet', lw=0, markersize=4,
                              norm=mpl.colors.LogNorm(vmin=1, vmax=10))
    shp_pathlines_spings.plot(ax=ax, column='time', cmap='jet', lw=0.5,
                              norm=mpl.colors.LogNorm(vmin=1, vmax=100))
    # shp_ending.plot(ax=ax, column='time', cmap='jet', lw=0, markersize=4,
    #                           vmin=1, vmax=30)
    # shp_pathlines_spings.plot(ax=ax, column='time', cmap='jet', lw=0.5,
    #                           vmin=1, vmax=30)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')
    fig = ax.get_figure()
    cax = fig.add_axes([1, 0.2, 0.02, 0.6])
    sm = plt.cm.ScalarMappable(cmap='jet', norm=mpl.colors.LogNorm(vmin=1, vmax=100))
    # fake up the array of the scalar mappable. Urgh...
    sm._A = []
    fig.colorbar(sm, cax=cax)
    fig.suptitle( model_name, y=0.85, fontsize=5)
    fig.tight_layout()
    
    fig.savefig(fig_path+'pathlines_knickpoint_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% ---- MODPATH FILES OLD

#%% CREATE SAPEFILE MODPATH

### MODEL ###
list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
model_name = list_path[-1].split('\\')[-1]
mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
fname = simulations_folder+model_name+'/'+model_name+'.hds'
gridname = simulations_folder+model_name+'/'+model_name+'.dis'
grid_model = flopy.discretization.grid.Grid(mf)
grid_model = mf.modelgrid
# sr_model = flopy.utils.reference.SpatialReference()

bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
ext_mod = bv_box.geometry.total_bounds

def reproj_approx_points(shp_name):
    shp = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        shp_name+'.shp')
    ext_shp = shp.geometry.total_bounds
    crs_code = 32620
    shp.set_crs(epsg=crs_code, inplace=True, allow_override=True)
    # shp.to_crs(utm_crs)
    print(ext_shp)
    x = (shp.geometry.x) + ext_mod[0] # - ext_shp[0] # 6.39e5 
    y = (shp.geometry.y) + ext_mod[1] # - ext_shp[3] # 1.78e6 
    gdf = gpd.GeoDataFrame(shp, geometry=gpd.points_from_xy(x, y))
    gdf.to_file(simulations_folder+
                model_name+'/'+'_pathlines/'+
                shp_name+'.shp')

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
                        mg=grid_model, epsg=32620, sr=None)
endobj.write_shapefile(endpoint_data=e,
                        shpname=simulations_folder+
                                model_name+'/'+'_pathlines/'+
                                'starting.shp',
                        direction='starting',
                        mg=grid_model, epsg=32620, sr=None)
# reproj_approx_points('ending')
# reproj_approx_points('starting')

### PATHLINES ###
print('Create shapefile particules and pathlines')
pthobj = flopy.utils.PathlineFile(simulations_folder+
                                  model_name+'/'+model_name+'.mppth')
pth_data = pthobj.get_alldata()

pthobj.write_shapefile(pathline_data=pth_data,
                        shpname=simulations_folder+
                                model_name+'/'+'_pathlines/'+
                                'particlues.shp',
                        one_per_particle=False, 
                        direction='ending',
                        mg=grid_model, epsg=32620, sr=None)

pthobj.write_shapefile(pathline_data=pth_data,
                        shpname=simulations_folder+
                                model_name+'/'+'_pathlines/'+
                                'pathlines.shp',
                        one_per_particle=True, 
                        direction='ending',
                        mg=grid_model, epsg=32620, sr=None)

#%% OPEN SAPEFILE MODPATH

shp_starting = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'starting.shp')
shp_ending = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'ending.shp')
shp_pathlines = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'pathlines.shp')
shp_particules = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'particlues.shp')

#%% DISTINCTION OF PARTICULES

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

#%% SELECTION BETWEEN LAYERS

if not os.path.exists(simulations_folder+'id_layers_random.data'):
    id_layers_random = [random.sample(shalid, 500),
                        random.sample(deepid, 500)]
    with open(simulations_folder+'id_layers_random.data', 'wb') as f:
        pickle.dump(id_layers_random, f)
else:
    with open(simulations_folder+'id_layers_random.data', 'rb') as f:
        id_layers_random = pickle.load(f)

#%% SHAPEFILES TREATMENT

shp_starting['time_year'] = shp_starting['time'] / 365
shp_ending['time_year'] = shp_ending['time'] / 365
shp_particules['time_year'] = shp_particules['time'] / 365
shp_pathlines['time_year'] = shp_pathlines['time'] / 365

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

#%% ---- PLOT 4

#%% PATHLINES QUICK

fig, ax = plt.subplots(1,1, figsize=(3,3))
ax = ax
# ax.set_title('Pathlines deep vs. shallow', fontsize=10)

shp_particules_deep.plot(ax=ax, column='time_year', cmap='jet', lw=0.5,
                         norm=mpl.colors.LogNorm(vmin=1, vmax=100))

ax.imshow(np.ma.masked_where(streams<=0, streams), cmap=mpl.colors.ListedColormap('navy'), 
          extent=[bv_box.bounds.minx[0],bv_box.bounds.maxx[0],
                  bv_box.bounds.miny[0],bv_box.bounds.maxy[0]], zorder=4)
ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
          extent=[bv_box.bounds.minx[0],bv_box.bounds.maxx[0],
                  bv_box.bounds.miny[0],bv_box.bounds.maxy[0]], zorder=5)

shp_ending[shp_ending.time_year>0].plot(ax=ax, column='time_year', lw=0, zorder=1000,
                                        markersize=1,
                                        norm=mpl.colors.LogNorm(vmin=1, vmax=100))

ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  
fig.tight_layout()

#%% ----- BULK

#%% RESIDENCE

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'

path_res = folder_results+'residence_times_t(0).tif'
path_obs = data_path+'targets_pathlines_points.shp'
path_shp = simulations_folder + '/' + model_name + '/' + '_watershed/_shp/'
toolbox.create_folder(path_shp)
path_dat = path_shp+'residence_times_data.shp'

res_time = rasterio.open(path_res)
res_time_data = res_time.read(1)

shp_obs = gpd.read_file(path_obs)
shp_obs['geometry'] = shp_obs.geometry.buffer(100)
shp_obs.to_file(path_dat, encoding='utf-8') # mode a

# Method 1
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
    mask = (intersect[intersect['id']==ID]['VALUE'] !=0)
    mean_ID = np.nanmean(intersect[intersect['id']==ID]['VALUE'][mask])
    res_dat['RES_TIME'][res_dat['id']==ID] = mean_ID
    std_ID = np.nanstd(intersect[intersect['id']==ID]['VALUE'][mask])
    res_dat['STD_TIME'][res_dat['id']==ID] = std_ID
    
# Method 2
"""
from rasterstats import zonal_stats
stats = zonal_stats(path_dat, path_res)
# print(stats[0].keys())
# print(stats)
means = [f['mean'] for f in stats]
res_dat = gpd.read_file(path_dat)
res_dat['RES_TIME'] = means
"""

res_dat['RES_TIME'][res_dat['RES_TIME']==-np.inf] = np.nan
res_dat['STD_TIME'][res_dat['STD_TIME']==-np.inf] = np.nan
res_dat.to_file(path_shp + 'extract_RTD.shp', encoding = 'utf-8')

vmin = 0
vmax = 100

fig, ax = plt.subplots(1,1, figsize=(5,5))

res_time_data = np.ma.masked_where(res_time_data < 0, res_time_data)
show(res_time_data, ax=ax, transform=dem.transform, 
      cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=vmin, vmax=vmax)
shp_obs.plot(ax=ax, color='none', marker='o', markersize=10,
              edgecolor='k', lw=3, zorder=30)
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
contour_shp = gpd.read_file(BV.geographic.watershed_contour_shp)
contour_shp.plot(ax=ax, lw=1.5, color='k', zorder=20, legend=False, label='Watershed')
cbar.set_ticks(list(cbar.get_ticks()))
# cbar.set_ticklabels(list(cbar.get_ticks())[::-1]) # invert
cbar.set_label('Residence times [years]', rotation=270, labelpad=25)

res_dat['coords'] = res_dat['geometry'].apply(lambda x: x.representative_point().coords[:])
res_dat['coords'] = [res_dat[0] for res_dat in res_dat['coords']]
# for idx, row in res_dat.iterrows():
#     row['coords'] = (row['coords'][0], row['coords'][1]+100)
#     ax.annotate(s=row['id'], xy=row['coords'],
#                  horizontalalignment='center')

compt = 0
if compt==0:
    all_dat = res_dat.copy()
all_dat[model_name] = res_dat['RES_TIME']

# all_dat['coords'] = np.nan
# all_dat.to_file(simulations_folder+'residence_times_all.shp', sep=';', encoding='utf-8')

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'map_residence_time_all'+'.png', dpi=300, bbox_inches='tight')

#%% VTK

import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is a deprecated alias.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.character` to a dtype is deprecated.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")

#import required packages
import itertools
import pyvista as pv
#for windows users
from shapely import speedups
speedups.disable()

#create geodataframes from all shapefiles

if not 'shp_particlues' in locals():
    shp_particlues = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'particlues.shp')
    # shp_particlues = gpd.read_file(simulations_folder+
    #                     model_name+'/'+'_pathlines/'+
    #                     'pathlines.shp')
    # shp_particlues['time'] = shp_particlues['time'] / 365
lineDf = shp_particlues
# lineDf = shp_particlues[shp_particlues['particleid'].isin(indices_layers_select[0])]
lineDf = lineDf.iloc[0:1000]

#create emtpy dict to store the partial unstructure grids
lineTubes = {}

#iterate over the points
for index, values in lineDf.iterrows():
    
    print(index, len(lineDf))
    
    cellSec = []
    linePointSec = []

    #iterate over the geometry coords
    zipObject = zip(values.geometry.xy[0],values.geometry.xy[1],itertools.repeat(values.z))
    for linePoint in zipObject:
        linePointSec.append([linePoint[0],linePoint[1],linePoint[2]])

    #get the number of vertex from the line and create the cell sequence
    nPoints = len(list(lineDf.loc[index].geometry.coords))
    cellSec = [nPoints] + [i for i in range(nPoints)]

    #convert list to numpy arrays
    cellSecArray = np.array(cellSec)
    cellTypeArray = np.array([4])
    linePointArray = np.array(linePointSec)

    partialLineUgrid = pv.UnstructuredGrid(cellSecArray,cellTypeArray,linePointArray)   
    #we can add some values to the point
    partialLineUgrid.cell_arrays["z"] = values.z
    partialLineUgrid.cell_arrays["time"] = values.time
    lineTubes[str(index)] = partialLineUgrid

#merge all tubes and export resulting vtk
lineBlocks = pv.MultiBlock(lineTubes)
lineGrid = lineBlocks.combine()
lineGrid.save(simulations_folder+model_name+'/'+'_pathlines/'+
              'particules.vtk', binary=False)
# lineGrid.save(simulations_folder+model_name+'/'+'_pathlines/'+
#               'pathlines.vtk', binary=False)
# lineGrid.plot()
import vedo

#https://hatarilabs.com/ih-en/tutorial-to-convert-geospatial-data-shapefile-to-3d-data-vtk-with-python-geopandas-pyvista

#%% NOTES

vtk.VTK(BV, model_name)
