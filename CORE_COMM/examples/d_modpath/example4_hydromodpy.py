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

#%% PATHS

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

#%% DICHOTOMY

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

df.loc[0,types_obs[0]] = koptim / 24 / 3600
df.loc[1,types_obs[0]] = kr
df.loc[2,types_obs[0]] = obj_func

df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

#%% CASES

# Import K calibrated
df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
Koptim = float('{:.1e}'.format(df.loc[0][1]))

######################
case = 'k0k1'
# case = 1
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
    k1s = [Koptim * 3600 * 24] # lower layer
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'case1'

if case == 2:
    # Hydraulic cond.
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    k1s = [Koptim * 3600 * 24 * 10] # lower layer
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'case2'

if case == 3:
    # Hydraulic cond.
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    k1s = [Koptim / 10 * 3600 * 24] # lower layer
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'case3'

if case == 4:
    # Hydraulic cond.
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0.02 # exponential decay of K with depth : 0.02
    # Vertical
    k1s = [None] # lower layer
    verti_k = None # "k1", or None
    # Name
    typ = 'case4'
    
if case == 'k0k1':
    k0 = Koptim * 3600 * 24 # upper layer
    thick_k0 = 50 # thickness of the upper layer
    cond_decay = 0 # exponential decay of K with depth : 0.02
    # Vertical
    k1s =[
          # Koptim * 3600 * 24 / 1000,
          Koptim * 3600 * 24 / 100,
          Koptim * 3600 * 24 / 10,
          Koptim * 3600 * 24,
          Koptim * 3600 * 24 * 10,
          Koptim * 3600 * 24 * 100,
          # Koptim * 3600 * 24 * 1000
          ]
    verti_k = [ [k0, [0, thick_k0]] ] # "k1", or None
    # Name
    typ = 'casek0k1'

#%% OPTIONS

# Option
sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = True # run modpath particle tracking if True
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
BV.hydrodynamic.update_cond_decay(cond_decay) # 0
BV.hydrodynamic.update_thick_exp(thick_exp) # 1
BV.hydrodynamic.update_thickness(thick) # 30 / intervient pas si bottom != None

BV.hydrodynamic.update_porosity(Sy)
  
date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
date_today = date_today.replace('/','-')
date_today = date_today.replace(':','-')
date_today = date_today.replace(' ','_')

for k1 in k1s:
    BV.hydrodynamic.update_hyd_cond(k1) 

    model_name = typ+'_'+str(compt)+'_'+\
                     str(Sy*100)+'-'+str(round(k0/k1,3))+'-'+str(thick)+'_'+str(nlay)

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

#%% POST-PROCESS

modpath_sim

h5file = simulations_folder+'/'+'list_'+typ
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_of_success = d['list_of_success'][:]
list_flow_model = d['list_flow_model'][:]

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
            data_explo.loc[cp,'Dos'] = obs
            data_explo.loc[cp,'Dso'] = sim
            data_explo.loc[cp,'Dind'] = ind
            
            # Discharge calib
            sub_res_path = os.path.join(BV.simulations_folder, model_name, '_subbasins', 'subbasin_Flowrate')
            sub_res = pd.read_csv(os.path.join(sub_res_path, '_simulated_results.csv'), ';',
                                  index_col='date', parse_dates=True)
            data_explo.loc[cp,'Qsim'] = sub_res['accumulation_flux'].values[0]
            
            # Residence times
            res_path = os.path.join(BV.simulations_folder, model_name, '_watershed')
            res = pd.read_csv(os.path.join(res_path, '_simulated_results.csv'), ';',
                              index_col='date', parse_dates=True)
            data_explo.loc[cp,'ts'] = res['residence_times'].values[0]
            
            cp+=1

#%% CLASS

class Streams:

    def __init__(self, 
                 watershed, 
                 hydrology_stable=None,
                 simulation_folder=None):
        
        self.geographic = watershed.geographic
        self.hydrology = watershed.hydrology
        self.simulation_folder = simulation_folder
        
        self.results_folder=os.path.join(self.simulation_folder, '_watershed')
        
        self.watershed_shp = watershed.geographic.watershed_shp
        self.watershed_fill = watershed.geographic.watershed_fill
        self.watershed_direc = watershed.geographic.watershed_direc
              
        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()
    
    #%% COMPARE SIMULATED TO OBSERVED
    
    def prepare_files(self):
        #files are necessary for whiteboxtool
        # New folder results
        self.dichotomy_folder = os.path.join(self.calibration_folder, '_streams')
        toolbox.create_folder(self.dichotomy_folder)
        # Observed buff data
        self.buff_tif_obs = self.hydrology.tif_streams
        # Mask observed: raster of observed river occurency
        self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, True)
        # Obs to points: vector (points) of river occurency from raster
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)  
        # Mask seepage simulation: raster of simulated river occurency
        tif_sim = os.path.join(self.results_folder,'_tifs', 'seepage_areas_t(0).tif')
        self.tif_sim = os.path.join(self.dichotomy_folder,'sim.tif')
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, True)
        # Trace downslope obs: drawing of flow path from observed river to simulated ones with whitebox tool
        self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
       
        # STREAMS: RONAN
    def sim_to_obs(self):
        # Distance of sim
        self.dist_sim_obs = os.path.join(self.dichotomy_folder, 'dist_sim_obs.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_sim_obs)        
        # Sim to points
        self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)        
        # Trace downslope sim
        self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)        
        # Simflow to points
        self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)       
        # Extra
        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_sim_obs, self.pt_sim_flow)
    
    def obs_to_sim(self):
        # Distance of sim
        self.dist_obs_sim = os.path.join(self.dichotomy_folder, 'dist_obs_sim.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_obs_sim)   
        # Obsflow to points
        self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        # Extra
        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_obs_sim, self.pt_obs_flow)

    def get_indicator(self):
        obs_to_sim = gpd.read_file(self.pt_obs_flow)
        obs_to_sim = obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        obs_to_sim = obs_to_sim[obs_to_sim['distance'] >= 0]
        self.mean_obs_to_sim = np.nanmean(obs_to_sim['distance'])
        sim_to_obs = gpd.read_file(self.pt_sim_flow)
        sim_to_obs = sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        sim_to_obs = sim_to_obs[sim_to_obs['distance'] >= 0]
        self.mean_sim_to_obs = np.nanmean(sim_to_obs['distance'])
        
        indicator = (np.log(self.mean_sim_to_obs/self.mean_obs_to_sim))**2
        return indicator, self.mean_obs_to_sim, self.mean_sim_to_obs

#%% ---- LOAD DATA

#%% GENERAL

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

#%% PLOT

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

#%% MODPATH

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

#%% SELECT

cond_lay = 50 # ==> tickness of the first layer

compt = 0
indices_layers = []
shal_p = []
shal_id = []
deep_p = []
deep_id = []
for idx, pline in enumerate(pth_data):
    if all(x < cond_lay for x in pline.k):
        compt += 1
        # print(compt)
        shal_p.append(pline)
        shal_id.append(pline['particleid'][0])
    else:
        deep_p.append(pline)
        deep_id.append(pline['particleid'][0])
        
if len(shal_id) == 0:
    shal_id = [np.nan]
if len(deep_id) == 0:
    deep_id = [np.nan]
    
indices_layers = [shal_id, deep_id]

rdm_id = True
if rdm_id == True:
    num_rdm = [100, 100]
    if num_rdm[0]>len(shal_id):
        num_rdm[0] = len(shal_id)
    if num_rdm[1]>len(deep_id):
        num_rdm[1] = len(deep_id)
else:
    num_rdm = [len(shal_id), len(deep_id)]

indices_layers_select = [random.sample(indices_layers[0], num_rdm[0]),
                         random.sample(indices_layers[1], num_rdm[1])]
with open(simulations_folder+'indices_layers_select.data', 'wb') as f:
    pickle.dump(indices_layers_select, f)

#%% INDICE

with open(simulations_folder+'indices_layers_select.data', 'rb') as f:
    indices_layers_select = pickle.load(f)
    
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

#%% PATHLINES

shp_pathlines = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'pathlines.shp')
shp_pathlines['time'] = shp_pathlines['time'] / 365

keep_shal = np.isin(shp_pathlines.particleid, indices_layers_select[0])
shp_shal = shp_pathlines[keep_shal]
keep_deep = np.isin(shp_pathlines.particleid, indices_layers_select[1])
shp_deep = shp_pathlines[keep_deep]

color_layers = ['red', 'dodgerblue']

fig, ax = plt.subplots(1,1, figsize=(3,3))    
ax = ax
ax.set_title('Pathlines deep vs. shallow', fontsize=10)

# shp_deep.plot(ax=ax, color=color_layers[0], lw=1, alpha=0.5, zorder=2)
# shp_shal.plot(ax=ax, color=color_layers[1], lw=1, alpha=0.5, zorder=3)

shp_pathlines.plot(ax=ax, column='time', cmap='jet', lw=0.1, alpha=1, zorder=0)

# ax.imshow(np.ma.masked_where(streams<=0, streams), cmap=mpl.colors.ListedColormap('navy'), 
#           extent=[0,dem_data.shape[1]*5,
#                   0,dem_data.shape[0]*5], zorder=4)
# ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
#           extent=[0,dem_data.shape[1]*5,
#                   0,dem_data.shape[0]*5], zorder=5)

ax.imshow(np.ma.masked_where(streams<=0, streams), cmap=mpl.colors.ListedColormap('navy'), 
          extent=[bv_box.bounds.minx[0],bv_box.bounds.maxx[0],
                  bv_box.bounds.miny[0],bv_box.bounds.maxy[0]], zorder=4)
ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
          extent=[bv_box.bounds.minx[0],bv_box.bounds.maxx[0],
                  bv_box.bounds.miny[0],bv_box.bounds.maxy[0]], zorder=5)

ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  
fig.tight_layout()
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Pathlines in shallow layer from starting points'+'.png', dpi=300, bbox_inches='tight')

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
