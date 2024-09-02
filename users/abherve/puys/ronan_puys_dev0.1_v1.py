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

#%% HYDROMODPY

# Import HydroModPy modules
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
sys.path.append(DIR)

import src
import importlib
importlib.reload(src)

from src import watershed_root
from src.watershed import climatic, driasclimat, driaseau, geographic, geology, geometric, hydraulic, \
                          hydrography, hydrometry, intermittency, oceanic, \
                          piezometry, safransurfex, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% USERS

user_path = "Ronan"
data_path = "C:/Users/ronan/OneDrive/UNINE/11_Paper/PUYS/_data/"
out_path = "C:/Users/ronan/Simulations/PUYS/"
# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/PUYS/figures/"

user_path = "Ronan"
data_path = "D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/11_Paper/PUYS/_data/"
out_path = "E:/_RONAN/_E_SIMULATIONS/PUYS/"
# fig_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/PROJECTS/PUYS/figures/"

fig_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/11_Paper/PUYS/_figures2/'
  
print("Define a well-validated name of user")

#%% PATHS

dem_name = 'DEM_TOPO_Tiretaine_25.tif' # EUDTM_Alps_30m_vallon
soc_name = 'DEM_BOTTOM_Tiretaine_25.tif' # EUDTM_Alps_30m_vallon

dem_path = data_path + dem_name
soc_path = data_path + soc_name

# wbt.set_nodata_value(
#     dem_path, 
#     dem_path,
#     back_value=np.nan)
wbt.modify_no_data_value(
    dem_path, 
    new_value="-99999")
x = imageio.imread(dem_path)
x[x<0] = np.nan

# wbt.set_nodata_value(
#     socle_path, 
#     socle_path,
#     back_value=np.nan)
wbt.modify_no_data_value(
    soc_path, 
    new_value="-99999")
y = imageio.imread(soc_path)
y[y<0] = np.nan 

fig, ax = plt.subplots(1,1, figsize=(6,3))
neg = x - y
neg[neg<0] = 0
im = ax.imshow(neg)
fig.colorbar(im)

ym = np.where(neg==0, x, y)

r = 150
fig, ax = plt.subplots(1,1, figsize=(6,3))
ax.plot(x[r,200:1200], color='k')
ax.plot(y[r,200:1200], color='red')
ax.plot(ym[r,200:1200], color='darkorange')
# ax.invert_xaxis()

subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
# from_shp = [data_path + 'BV_Tiretaine_HydromodPy_manmod.shp', 100]
from_shp = None

watershed_names = ['Tiretaine_socle','Tiretaine']

# toolbox.export_tif(dem_path, 
#                     x, -9999, data_path + 'DEM_TOPO_Tiretaine_25_mod.tif')
# toolbox.export_tif(soc_path, 
#                     ym, -9999, data_path + 'DEM_BOTTOM_Tiretaine_25_mod.tif')

# from_xyvs = [701724.007,6518671.537,50,10,'EPSG:2154'] 
from_xyv = None

ras_paths = [ data_path+'DEM_BOTTOM_Tiretaine_25_mod_proj.tif', data_path+'DEM_TOPO_Tiretaine_25_mod_proj.tif']

#%% LOAD

load = True
load = False

for watershed_name, ras_path in zip(watershed_names[:], ras_paths[:]):
        
    print('##### '+watershed_name.upper()+' #####')
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=ras_path, 
                                  out_path=out_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=[ras_path,25],
                                  from_xyv=from_xyv)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
      
    # print(BV.geographic.area.round(2))
    # print(BV.geographic.slope.round(2))
    
    try:
        visualization_watershed.watershed_local(dem_path, BV)
        visualization_watershed.watershed_dem(BV)
    except:
        pass

    # SUBBASIN
    
    # BV.add_intermittency('None','None')
    # BV.add_subbasin(data_path+'_coordinates_additional/', sub_snap_dist=100)
    
    BV.geographic.watershed_shp = data_path + 'BV_Tiretaine_HydromodPy_manmod.shp'
    BV.geographic.watershed_contour_shp = data_path + 'BV_Tiretaine_HydromodPy_manmod.shp'

#%% DATA

hydrography_path = data_path

types_obs = ['Streams_Tiretaine_Peren','Streams_Tiretaine_Fully']
fields_obs = ['fid','fid']

wbt.polygons_to_lines(out_path+watershed_name+"/results_stable/geographic/watershed.shp",
                      out_path+watershed_name+"/results_stable/geographic/watershed_contour.shp")

for type_obs, field_obs in zip(types_obs, fields_obs):
    
    # print('##### '+watershed_name.upper()+' #####')
               
    BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])

    visualization_watershed.watershed_local(dem_path, BV)
    visualization_watershed.watershed_dem(BV)
    
#%% ---- DICHOTOMY KEQ

#%% DICHOTOMY - FUNCTION

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
                 for_calib=True):
        
        self.geographic = watershed.geographic
        self.hydrography = watershed.hydrography
        
        if for_calib == True:
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

#%% DICHOTOMY - RUN

run_model = True

types_obs = ['Streams_Tiretaine_Fully']

hydrography_path = data_path  # add hydrographic shapefiles
fields_obs = ['fid']

for watershed_name in watershed_names[1:]:
            
    for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):
   
        print('##### '+watershed_name.upper()+' #####')
        
        df = pd.DataFrame()
        
        BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
        # area = BV.geographic.area

        shp = gpd.read_file(BV.geographic.watershed_shp)

        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
        BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
        toolbox.create_folder(BV.calibration_folder)
        
        if not os.path.exists(stable_folder + 'hydrography/' + type_obs + '.tif'):
            BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
        else:
            BV.hydrography.streams = stable_folder + 'hydrography/' + type_obs + '.shp'
            BV.hydrography.tif_streams = stable_folder + 'hydrography/' + type_obs + '.tif'
                
        box = True # or False
        split_temp = False
        sink_fill = False # or True
        sim_state = 'steady' # 'steady' or 'transient'
        plot_cross = True
        first_clim = 'mean' # or 'first or value
        nlay = 1
        lay_decay = 1 # 1 for no decay
        cond_decay = 0
        
        # verti_k_thetero = [ [K*1000, [d-d, v]] ] # [ [k2, [array1, array2]] ]

        topo_init = imageio.imread('E:/_RONAN/_E_SIMULATIONS/PUYS/Tiretaine/results_stable/geographic/watershed_box_buff_dem.tif')
        bottom_init = imageio.imread('E:/_RONAN/_E_SIMULATIONS/PUYS/Tiretaine_socle/results_stable/geographic/watershed_box_buff_dem.tif')
        bottom_custom = bottom_init - 30

        # r = 150
        # fig, ax = plt.subplots(1,1, figsize=(6,3))
        # ax.plot(topo_init[r,200:1200], color='brown')
        # ax.plot(bottom_init[r,200:1200], color='red')
        # ax.plot(bottom_custom[r,200:1200], color='darkorange')
        
        bottom = bottom_custom
        thick = None # if bottom is None, aquifer thickness
        
        recharge = 360 / 365 / 1000
        
        verti_cond = None # or [ [1e-5, [0, 20]],
        verti_poro = None
        cond_drain = None # or value of conductance
        porosity = 5 / 100 # -
        poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
        bc_left = None # or value
        bc_right = None # or value
        sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
        zone_partic = 'domain' # or watershed
        
        BV.add_settings()
        BV.add_climatic()
        BV.add_geometric() # soon
        BV.add_hydraulic()
        BV.settings.update_box_model(box)
        BV.settings.update_sink_fill(sink_fill)
        BV.settings.update_simulation_state(sim_state)
        BV.settings.update_active_plot(plot_cross=plot_cross)
        BV.climatic.update_recharge(recharge, sim_state=sim_state)
        BV.climatic.update_first_clim(first_clim)
        BV.hydraulic.update_nlay(nlay) # 1
        BV.hydraulic.update_lay_decay(lay_decay) # 1
        BV.hydraulic.update_porosity(porosity)
        BV.hydraulic.update_cond_vertical(verti_cond)
        BV.hydraulic.update_poro_vertical(verti_poro)
        BV.hydraulic.update_cond_drain(cond_drain)
        BV.hydraulic.update_poro_decay(poro_decay)
        BV.settings.update_bc_sides(bc_left, bc_right)
        BV.add_oceanic(sea_level)
        BV.settings.update_input_particules(zone_partic=zone_partic)
        BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
        BV.hydraulic.update_cond_decay(cond_decay) # 0
        BV.hydraulic.update_bottom(bottom) # 0
        BV.settings.update_split_temporal(split_temp)
                       
        params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
        params_df.loc[0] = ['k1','?',1e-9*3600*24,1e-4*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
     
        # params_df.loc[0] = ['k1','?',1e-9*3600*24,1e-4*3600*24,'m/j','lin']
        params_file = 'calib_dicot_hom_1v_k1'
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
        p_min = params_df['lower_bounds'].values[0]
        p_max = params_df['higher_bounds'].values[0]
        diff = p_max - p_min
        half = (p_min + p_max) / 2
        # print(half)
        
        # gap = 1.0
        gap = 0.5
        # gap = 0.1
        
        compt = 0
        
        id_mod = 'keq'
        
        while (diff > ((gap/100) * half)):
            
            half = (p_min + p_max) / 2
            hyd_cond = half.copy() # if K in calib_params.csv
            kr = hyd_cond / BV.climatic.recharge
                        
            BV.hydraulic.update_hyd_cond(hyd_cond)
            
            now = datetime.now()
            oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss") 
            
            model_name = str('model_t2')+'-'+str(id_mod)+'_'+str(compt)+'_'+str("{:.2e}".format(hyd_cond/24/3600)) 

            BV.settings.update_model_name(model_name)
            # print(model_name)
                        
            model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
            success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=run_model)
            
            BV.postprocessing_modflow(model_modflow,
                                      watertable_elevation = True,
                                      watertable_depth= True, 
                                      seepage_areas = True,
                                      outflow_drain = True,
                                      groundwater_flux = True,
                                      groundwater_storage = True,
                                      accumulation_flux = True,
                                      export_all_tif = False)

            timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                              model_modpath=None,
                                                              actual_date=True, 
                                                              subbasin_results=True) # or None
        
            iter_results = MatchingStreams(BV, iteration_label=model_name)
            
            # obs_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
            # obs_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
            # obsf_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
            obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflowf.shp'))
            obsf_to_simf = obsf_to_simf.clip(shp)
            
            # sim_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
            # sim_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
            # simf_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
            simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))
            simf_to_obsf = simf_to_obsf.clip(shp)
        
            # mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
            # mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
            # mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
            # if (len(obsf_to_simf[obsf_to_simf['VALUE1']<=0]) / len(obsf_to_simf)) < 0.1:
            #     mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])
            # else:
            #     obsf_to_simf['VALUE1'][obsf_to_simf['VALUE1']<0] = 2000
            #     mean_obsf_to_simf = np.nanmean(obsf_to_simf['VALUE1'])
            obsf_to_simf['VALUE1'][obsf_to_simf['VALUE1']<0] = 1000
            mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])

            
            # mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
            # mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
            # mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
            # if (len(simf_to_obsf[simf_to_obsf['VALUE1']<=0]) / len(simf_to_obsf)) < 0.1:
            #     mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])
            # else:
            #     simf_to_obsf['VALUE1'][simf_to_obsf['VALUE1']<0] = 2000
            #     mean_simf_to_obsf = np.nanmean(simf_to_obsf['VALUE1'])
            simf_to_obsf['VALUE1'][simf_to_obsf['VALUE1']<0] = 1000
            mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])

            ### v8 simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year) ==> isba
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
            
            print('==> Simulation : '+str(compt))
            print('    K/R = '+str(round(kr, 4)))
            print('    Gap = '+str(round((gap/100) * kr, 4)))
            print('    Indicator = '+str(round(indicator, 4)))
            
            df.loc[compt,'id_mod'] = id_mod
            df.loc[compt,'compt'] = compt
            
            df.loc[compt,'model_name'] = model_name
            df.loc[compt,'type_obs'] = type_obs
            df.loc[compt,'oclock'] = oclock
            
            df.loc[compt,'KR'] = round(kr, 4)
            df.loc[compt,'K'] = round(hyd_cond, 4)
            df.loc[compt,'R'] = round(BV.climatic.recharge*1000, 4) # mm
            df.loc[compt,'K_decay'] = round(cond_decay, 4) # mm
            # if bottom == None:
            #     df.loc[compt,'bottom'] = round(thick, 4) 
            # else:
            # df.loc[compt,'bottom'] = round(bottom, 4)
    
            df.loc[compt,'Obs'] = round(obs, 4)
            df.loc[compt,'Sim'] = round(sim, 4)
            df.loc[compt,'Indicator'] = round(indicator, 4)
            
            # df.loc[compt,'mean_obs_to_sim'] = round(mean_obs_to_sim, 4)
            # df.loc[compt,'mean_obs_to_simf'] = round(mean_obs_to_simf, 4)
            # df.loc[compt,'mean_obsf_to_sim'] = round(mean_obsf_to_sim, 4)
            df.loc[compt,'mean_obsf_to_simf'] = round(mean_obsf_to_simf, 4)
            
            # df.loc[compt,'mean_sim_to_obs'] = round(mean_sim_to_obs, 4)
            # df.loc[compt,'mean_sim_to_obsf'] = round(mean_sim_to_obsf, 4)
            # df.loc[compt,'mean_simf_to_obs'] = round(mean_simf_to_obs, 4)
            df.loc[compt,'mean_simf_to_obsf'] = round(mean_simf_to_obsf, 4)
            
            compt += 1
                        
        df.to_csv(BV.calibration_folder+'/'+str('model')+str(id_mod)+'_dichotomy.csv', sep=';')

        # id_mod += 1
        
#%% DICHOTOMY - GRAPH K

id_mod = 'keq'

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfp = pd.read_csv(BV.calibration_folder+'/'+str('model')+str(id_mod)+'_dichotomy.csv', sep=';')

dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2)

fig, ax = plt.subplots(1,1, figsize=(6,5), dpi=600)

# ax.scatter(dfp['K']/24/3600, dfp['Doptim'], s=100, 
#             marker='o', lw=1.5, color='None', ec='k', zorder=1000
#             # cmap=mpl.colors.ListedColormap('k'),
#             # label=dfz['1/K_decay'].values[0]
#             )

dfpp = dfp.sort_values('K')
ax.plot(dfpp['K']/24/3600, dfpp['Doptim'],
            marker='o', ms=6, lw=1, color='k'
            )

# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('$K_{eq}$ [m/s]')
ax.set_xlim(1e-5, 1e-4)
# ax.set_ylim(30 , 90)
ax.set_ylabel('$D_{optim}$ [m]')
# cb = plt.colorbar()

ax.axvline(x=(dfp[-1:]['K']/24/3600).values, c='darkgreen', zorder=-1000, ls='-', lw=1)
ax.axhline(y=(dfp[-1:]['Doptim']).values, c='darkgreen', zorder=-1000, ls='-', lw=1)

# ax.grid()

# ax.set_yscale('log')

# fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/02_fig_dichotomy/'+
#             'DICHOTOMY_K_2'+'.png',
#             bbox_inches='tight')

#%% DICHOTOMY - MAPS

id_mod = 'keq'

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.read_csv(BV.calibration_folder+'/'+str('model')+str(id_mod)+'_dichotomy.csv', sep=';')

dfp = dfs.copy()
dfp['1/K_decay'] = 1/dfp['K_decay']
dfp['1/K_decay'][dfp['1/K_decay'] == np.inf] = 0
dfp['Doptim'] = (dfp['Obs'] + dfp['Sim'])/2

shp_bv = gpd.read_file(BV.geographic.watershed_shp)
shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'Streams_Tiretaine_Fully.shp')    

# types_obs = ['stream_perennial_wetlands_points']

model_name = dfp[-1:]['model_name'].values[0]
print(model_name)

fig, ax = plt.subplots(1,1, figsize=(10,10))

dem = rasterio.open(stable_folder + 'geographic/watershed_dem.tif')
# hil = rasterio.open('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/hillshade_classic.tif')

# rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
#                           ax=ax, transform=dem.transform,
#                           cmap='Greys_r', alpha=1, zorder=-5)

rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                          ax=ax, transform=dem.transform,
                          cmap='Greys', alpha=0.25, zorder=-5)

shp = gpd.read_file(BV.calibration_folder+'/'+str(model_name)+'/'+'_matchingstreams/'+'sim_pt.shp')

shp_bv.plot(ax=ax, facecolor='None', lw=3)
shp_hydro.plot(ax=ax, color='navy', lw=2)
shp.plot(ax=ax, color='darkorange', lw=0)

plt.yticks(rotation=90, ha='right')

ax.set_title(model_name, fontsize=7)

# fig.savefig('C:/Users/ronan/Downloads/figs/'+'MAPS_'+model_name+'.png',
#             bbox_inches='tight')

# fig.savefig('C:/Users/ronan/Downloads/figs_'+vers+'/'+'MAPS_'+model_name+'.png',
#             bbox_inches='tight')

# ax.get_xaxis().set_visible(False)
# ax.get_yaxis().set_visible(False)
# ax.axis('off')

    # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/02_fig_dichotomy/maps2/'+
    #             model_name+'_DICHOTOMY_MAP'+'.png',
    #             bbox_inches='tight')

#%% ---- UPDATE MODEL PARAMETERS

id_mod = 'keq'
iD_explo = 'e_test0' # with isba recharge ==> change ss with decay factor (details for bad models)

apel = str('model')+str(id_mod)

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
df_eq = pd.read_csv(BV.calibration_folder+'/'+apel+'_dichotomy.csv', sep=';')

box = True # or False
split_temp = False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True
first_clim = 'mean' # or 'first or value
nlay = 10
lay_decay = 1 # 1 for no decay
cond_decay = 0

# verti_k_thetero = [ [K*1000, [d-d, v]] ] # [ [k2, [array1, array2]] ]

topo_init = imageio.imread('E:/_RONAN/_E_SIMULATIONS/PUYS/Tiretaine/results_stable/geographic/watershed_box_buff_dem.tif')
bottom_init = imageio.imread('E:/_RONAN/_E_SIMULATIONS/PUYS/Tiretaine_socle/results_stable/geographic/watershed_box_buff_dem.tif')
bottom_custom = bottom_init - 30

scorie_init = np.ma.masked_where(topo_init<1030, topo_init)
scorie_init = (scorie_init * 0) + 1050
scorie_init = np.ma.filled(scorie_init, topo_init)
# plt.imshow(scorie_init)

# r = 150
# fig, ax = plt.subplots(1,1, figsize=(6,3))
# ax.plot(topo_init[r,200:1200], color='brown')
# ax.plot(bottom_init[r,200:1200], color='red')
# ax.plot(bottom_custom[r,200:1200], color='darkorange')

bottom = bottom_custom
thick = None # if bottom is None, aquifer thickness

recharge = 360 / 365 / 1000

# verti_cond = None # or [ [1e-5, [0, 20]],
verti_poro = None
cond_drain = None # or value of conductance
porosity = 1 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
ss_decay = 0
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed

BV.add_settings()
BV.add_climatic()
BV.add_geometric() # soon
BV.add_hydraulic()
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_poro_decay(poro_decay)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_input_particules(zone_partic=zone_partic)
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_cond_decay(cond_decay) # 0
BV.hydraulic.update_bottom(bottom) # 0
BV.settings.update_split_temporal(split_temp)
BV.hydraulic.update_ss_decay(ss_decay)

Keq = 2.45e-5 * 24 * 3600

list_K1 = [
           # Keq/1000,
           # Keq/100,
           Keq/10,
           Keq*1,
           Keq*10,
           # Keq*100,
           # Keq*1000
           ]
list_K2 = [
           # Keq/1000,
           # Keq/100,
           Keq/10,
           Keq*1,
           Keq*10,
           # Keq*100,
           # Keq*1000
           ]
list_K3 = [
           # Keq/1000,
           # Keq/100,
           Keq/10,
           Keq*1,
           Keq*10,
           # Keq*100,
           # Keq*1000
           ]

shp = gpd.read_file(BV.geographic.watershed_shp)

# Syeq = 1 / 100

list_Sy1 = np.array([
                     0.1,
                     1,
                     2,
                     ]) / 100
list_Sy2 = np.array([
                     2,
                     5,
                     10,
                     ]) / 100
list_Sy3 = np.array([
                     30,
                     40,
                     60,
                     ]) / 100

#%% ---- EXPLORATION K1 K2 K3

#%% MODFLOW PRE+PRO

run_model = True
# run_model = False

id_mod_val = 0

k1_cp = 0
for K1 in list_K1[:]:
    k2_cp = 0
    for K2 in list_K2[:]:
        k3_cp = 0
        for K3 in list_K3[:]:
            BV.hydraulic.update_hyd_cond(K1)
            verti_k_thetero = [ [K2, [topo_init-scorie_init, topo_init-bottom_init]],
                                [K3, [topo_init-topo_init, topo_init-scorie_init]],
                                ] # [ [k2, [array1, array2]] ] # verti_k_tconst = None # [ [k2, [0, thick_k2]] ]
            BV.hydraulic.update_cond_vertical(verti_k_thetero)
            
            if K1==K2==K3 :
                id_H='HOMOG'
            else:
                id_H='HETER'
                
            model_name = iD_explo+'_'+str('model')+'-'+str(id_mod_val)+'_'+\
                         str(id_H)+'_'+\
                         str(k1_cp)+'-'+str(k2_cp)+'-'+str(k3_cp)+'_'+\
                         str("{:.2e}".format(K1/24/3600))+'-'+str("{:.2e}".format(K2/24/3600))+'-'+str("{:.2e}".format(K3/24/3600))

            print(model_name)
            
            BV.settings.update_model_name(model_name)
            
            # now = datetime.now()
            # oclock = now.strftime("%Y%m%d-%Hh%Mm%Ss")
    
            model_modflow = BV.preprocessing_modflow(for_calib=False)
            
            hk = model_modflow.hk
            # mf = model_modflow.mf
            # modelmap = flopy.plot.ModelMap(model=mf)
            # modelmap.plot_array(hk[0], cmap='tab10', norm=mpl.colors.LogNorm(vmin=0.002, vmax=200))
            fig, ax = plt.subplots(1,1)
            im = ax.imshow(hk[0], cmap='rainbow', norm=mpl.colors.LogNorm(vmin=hk.min(), vmax=hk.max()))
            fig.colorbar(im)
            
            model_success = True
            try:
                model_success = BV.processing_modflow(model_modflow, write_model=True, run_model=run_model)
            except:
                model_success = False
                pass
            
            dictio = {}
            list_model_name = []
            list_model_success = []
            list_model_modflow = []
            list_model_results = [] 

            list_model_name.append(model_name)
            model_modflow = BV.preprocessing_modflow(for_calib=False)
            
            model_results = pd.DataFrame()
            
            model_results.loc[0,'iD_explo'] = iD_explo
            model_results.loc[0,'id_mod_val'] = id_mod_val
            model_results.loc[0,'k1_cp'] = k1_cp
            model_results.loc[0,'k2_cp'] = k2_cp
            model_results.loc[0,'k3_cp'] = k3_cp
            model_results.loc[0,'id_H'] = id_H
            model_results.loc[0,'model_name'] = model_name
            model_results.loc[0,'Keq'] = round(Keq, 4)
            model_results.loc[0,'K1'] = round(K1, 4)
            model_results.loc[0,'K2'] = round(K1, 4)
            model_results.loc[0,'K3'] = round(K1, 4)
            model_results.loc[0,'R'] = round(BV.climatic.recharge, 4) # mm
            
            list_model_results.append(model_results)
            
            list_model_modflow.append(model_modflow)
            list_model_success.append(model_success)
            
            dictio['list_model_modflow'] = list_model_modflow
            dictio['list_model_name'] = list_model_name
            dictio['list_model_success'] = list_model_success
            dictio['list_model_results'] = list_model_results
            h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
            if os.path.exists(h5file):
                os.remove(h5file)
            dd.io.save(h5file, dictio)
                            
            id_mod_val += 1
        
            k3_cp += 1
        k2_cp += 1    
    k1_cp += 1
        
#%% MODFLOW POST

list_id_mod = np.arange(0,27,1)

df = pd.DataFrame()

for id_mod_val in list_id_mod[:]:

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    list_model_results = d['list_model_results'][:]
    
    # for model_name, model_success, model_modflow in zip(list_model_name[8:],
    #                                                     list_model_success[8:],
    #                                                     list_model_modflow[8:]):

    for model_name, model_success, model_modflow, model_results in zip(list_model_name[:],
                                                                       list_model_success[:],
                                                                       list_model_modflow[:],
                                                                       list_model_results[:]):
        
        df.loc[id_mod_val,'iD_explo'] = model_results['iD_explo'][0]
        df.loc[id_mod_val,'id_mod_val'] = model_results['id_mod_val'][0]
        df.loc[id_mod_val,'k1_cp'] = model_results['k1_cp'][0]
        df.loc[id_mod_val,'k2_cp'] = model_results['k2_cp'][0]
        df.loc[id_mod_val,'k3_cp'] = model_results['k3_cp'][0]
        df.loc[id_mod_val,'id_H'] = model_results['id_H'][0]
        df.loc[id_mod_val,'model_name'] = model_results['model_name'][0]
        df.loc[id_mod_val,'Keq'] = round(model_results['Keq'][0], 4)
        df.loc[id_mod_val,'K1'] = round(model_results['K1'][0], 4)
        df.loc[id_mod_val,'K2'] = round(model_results['K2'][0], 4)
        df.loc[id_mod_val,'K3'] = round(model_results['K3'][0], 4)
        df.loc[id_mod_val,'R'] = round(model_results['R'][0], 4) # mm
        
        if model_success == True :
                        
            BV.postprocessing_modflow(model_modflow,
                                      watertable_elevation = True,
                                      watertable_depth = True, 
                                      seepage_areas = True,
                                      outflow_drain = True,
                                      groundwater_flux = True,
                                      groundwater_storage = True,
                                      accumulation_flux = True,
                                      persistency_index = False,
                                      intermittency_monthly = False,
                                      intermittency_weekly = False,
                                      intermittency_daily = False,
                                      export_all_tif = False)

            timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                              model_modpath=False,
                                                              actual_date=True, 
                                                              subbasin_results=True,
                                                              freq_time='D')
            
            iter_results = MatchingStreams(BV, iteration_label=model_name, for_calib=False)

            obsf_to_simf = gpd.read_file(os.path.join(BV.simulations_folder, model_name, '_matchingstreams','obsflowf.shp'))
            obsf_to_simf = obsf_to_simf.clip(shp)

            simf_to_obsf = gpd.read_file(os.path.join(BV.simulations_folder, model_name, '_matchingstreams','simflowf.shp'))
            simf_to_obsf = simf_to_obsf.clip(shp)
        
            obsf_to_simf['VALUE1'][obsf_to_simf['VALUE1']<0] = 1000
            mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])

            simf_to_obsf['VALUE1'][simf_to_obsf['VALUE1']<0] = 1000
            mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])

            obs = mean_obsf_to_simf
            sim = mean_simf_to_obsf
            indicator = sim/obs
            
            print('    Indicator = '+str(round(indicator, 4)))
            
            df.loc[id_mod_val,'Obs'] = round(obs, 4)
            df.loc[id_mod_val,'Sim'] = round(sim, 4)
            df.loc[id_mod_val,'Indicator'] = round(indicator, 4)
            df.loc[id_mod_val,'mean_obsf_to_simf'] = round(mean_obsf_to_simf, 4)            
            df.loc[id_mod_val,'mean_simf_to_obsf'] = round(mean_simf_to_obsf, 4)
        
        else:
                   
            indicator = np.nan
            print('    Indicator = '+str(indicator))
            
            df.loc[id_mod_val,'Obs'] = np.nan
            df.loc[id_mod_val,'Sim'] = np.nan
            df.loc[id_mod_val,'Indicator'] = indicator
            df.loc[id_mod_val,'mean_obsf_to_simf'] = np.nan       
            df.loc[id_mod_val,'mean_simf_to_obsf'] = np.nan
                
df.to_csv(BV.simulations_folder+'/'+str(iD_explo)+'_exploration results.csv', sep=';')
                
#%% ---- PLOT  K1 K2 K3

#%% 2D MAP VIEW

list_id_mod = np.arange(0,27,1)

df = pd.DataFrame()

for id_mod_val in list_id_mod[:]:

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    list_model_results = d['list_model_results'][:]
    
    # plt.imshow(imageio.imread(BV.geographic.watershed_box_buff_dem))
    
    for model_name, model_success, model_modflow, model_results in zip(list_model_name[:],
                                                                       list_model_success[:],
                                                                       list_model_modflow[:],
                                                                       list_model_results[:]):
            
        visu = visualization_results.Visualization(BV, model_name)
        visu.visual2D(object_list = ['map','grid',
                                     'watertable', 'watertable_depth',
                                     'drain_flow','surface_flow',
                                     # 'pathlines', 'residence_times'
                                     ],
                      color_scale = [(None,None),(None,None),
                                     (None,None),(0,10),
                                     (None,None),(None,None),
                                     # (0,100),(None,None),
                                     ], 
                      lines=500)

#%% CROSS SECTION

list_id_mod = np.arange(0,27,1)

df = pd.DataFrame()

for id_mod_val in [ list_id_mod[13] ]:

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    list_model_results = d['list_model_results'][:]
    
    for model_name, model_success, model_modflow, model_results in zip(list_model_name[:],
                                                                       list_model_success[:],
                                                                       list_model_modflow[:],
                                                                       list_model_results[:]):
        print(model_name)
        # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
        # try:
            
        id_model = int(model_name.split('_')[2].split('-')[-1])
                
        ### MODEL ###
        # list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
        # model_name = list_path[-1].split('\\')[-1]
        # mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
        mf = model_modflow.mf
        
        fname = simulations_folder+model_name+'/'+model_name+'.hds'
        gridname = simulations_folder+model_name+'/'+model_name+'.dis'
        # grid_model = flopy.discretization.grid.Grid(mf)
        grid_model = mf.modelgrid
        hk_grid = mf.upw.hk
        
        hk = model_modflow.hk
        # mf = model_modflow.mf
        # modelmap = flopy.plot.ModelMap(model=mf)
        # modelmap.plot_array(hk[0], cmap='tab10', norm=mpl.colors.LogNorm(vmin=0.002, vmax=200))
        
        ps = model_modflow.ps
        
        fig0, ax0 = plt.subplots(1,2)
        ax0 = ax0.ravel()
        im = ax0[0].imshow(hk[0], cmap='rainbow', norm=mpl.colors.LogNorm(vmin=hk.min(), vmax=hk.max()))
        fig.colorbar(im)
        
        # sy_grid = mf.upw.sy
        sy_grid = model_modflow.ps
        # sr_model = flopy.utils.reference.SpatialReference()
        
        imp = ax0[1].imshow(ps[0], cmap='rainbow',
                            # norm=mpl.colors.LogNorm(vmin=hk.min(), vmax=hk.max())
                            )
        fig.colorbar(imp)
        
        fig, axs = plt.subplots(1, 2, figsize=(15, 5))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        
        ax = axs[0]
        # fig, ax = plt.subplots(1, 1, figsize=(6, 3))
        # ax = fig.add_subplot(1, 1, 1)
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
        
        # linecollection = modelxsect.plot_grid()
        hdobj = flopy.utils.HeadFile(fname)
        head_data = hdobj.get_data()
        
        val = hk_grid.array/24/3600
        for i in range(val.shape[0]):
            # mask = val[i] == 0
            # val[i][mask] = 1e-100
            val[i][val[i] <= np.nanmin(val[i])] = np.nanmin(val[i][np.nonzero(val[i])])
        cb = modelxsect.plot_array(val, ax=ax, cmap='rainbow', lw=0.1,
                                    norm=mpl.colors.LogNorm(vmin=(Keq/3600/24)/10, 
                                                            vmax=(Keq/3600/24)*10)
                                    )
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=ax,)
        ax.set_title('Meshgrid West to East, K [m/s]')
        # ax.set_xlim(150, 350)
        # ax.set_ylim(150, 350)
        # ax.set_xticks([0,1000,2000,3000])
        ax.set_ylim(600, 1500)
        fig.suptitle(model_name.upper(), x=0.5, y=1.0, fontsize=10)
        fig.colorbar(cb)
        plt.tight_layout()
        # fig.set_size_inches(6, 3, forward=True)
        
        
        ax = axs[1]
        # fig, ax = plt.subplots(1, 1, figsize=(6, 3))
        # ax = fig.add_subplot(1, 1, 1)
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[2])/2)})
        # linecollection = modelxsect.plot_grid()
        # hdobj = flopy.utils.HeadFile(fname)
        # head_data = hdobj.get_data()
        cb = modelxsect.plot_array(sy_grid*100, ax=ax, cmap='plasma', lw=0.1,
                                   # vmin=0, vmax=50
                                   )
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=axs[1])
        ax.set_title('Meshgrid North to South, Φ [%]')
        ax.set_ylim(600, 1500)
        # ax.set_xticks([0,1000,2000,3000,4000])
        fig.suptitle(model_name.upper(), x=0.5, y=1.0, fontsize=8)
        fig.colorbar(cb)
        plt.tight_layout()
        # fig.set_size_inches(6, 3, forward=True)
        
    
        # for i in range(len(flow_model.zbot)):
        #     fig, ax = plt.subplots(1, 1, figsize=(5, 5))
        #     zbotval = flow_model.zbot[i]
        #     hkval = hk_grid.array/24/3600
        #     a=ax.imshow(hkval[i], cmap='viridis',
        #               norm=mpl.colors.LogNorm(vmin=2e-5, vmax=2e-5*100))
        #     ax.set_title(str(i))
        #     fig.colorbar(a)
        
        # ###
        
        # modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
        # fig2, ax2 = plt.subplots(1, 1, figsize=(6, 3))
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=ax2)
        # ax2.set_title(model_name, fontsize=10)
        # ax2.set_ylim(450)

#%% GRAPH K BEST

df = pd.read_csv(BV.simulations_folder+'/'+str(iD_explo)+'_exploration results.csv', sep=';')

fig, ax = plt.subplots(1, 1, figsize=(6, 5))
ax.plot(df['id_mod_val'], abs(1-df['Indicator']), marker='o')
ax.set_yscale('log')

#%% ---- EXPLORATION S1 S2 S3

#%% MODPATH PRE+PRO+POST

X = 13

df = pd.read_csv(BV.simulations_folder+'/'+str(iD_explo)+'_exploration results.csv', sep=';')

pathlines_shp = False
particules_shp = False

# list_id_mod = np.arange(0,27,1)
list_id_mod = [X]

for id_mod_val in list_id_mod[:]:

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    list_model_results = d['list_model_results'][:]
    
    # for model_name, model_success, model_modflow in zip(list_model_name[8:],
    #                                                     list_model_success[8:],
    #                                                     list_model_modflow[8:]):

    for model_name, model_success, model_modflow, model_results in zip(list_model_name[:],
                                                                       list_model_success[:],
                                                                       list_model_modflow[:],
                                                                       list_model_results[:]):
                
        K1 = df.loc[X,'K1']
        K2 = df.loc[X,'K2']
        K3 = df.loc[X,'K3']
        
        BV.hydraulic.update_hyd_cond(K1)
        verti_k_thetero = [ [K2, [topo_init-scorie_init, topo_init-bottom_init]],
                            [K3, [topo_init-topo_init, topo_init-scorie_init]],
                            ] # [ [k2, [array1, array2]] ] # verti_k_tconst = None # [ [k2, [0, thick_k2]] ]
        BV.hydraulic.update_cond_vertical(verti_k_thetero)
        
        if K1==K2==K3 :
            id_H='HOMOG'
        else:
            id_H='HETER'
        
        id_mod_val = X
        cp_each = 0
        
        Sy1_cp = 0
        for Sy1 in list_Sy1[:]:
            Sy2_cp = 0
            for Sy2 in list_Sy2[:]:
                Sy3_cp = 0
                for Sy3 in list_Sy3[:]:
                    
                    BV.hydraulic.update_porosity(Sy1)
                    verti_sy_thetero = [ [Sy2, [topo_init-scorie_init, topo_init-bottom_init]],
                                         [Sy3, [topo_init-topo_init, topo_init-scorie_init]],
                                         ] # [ [k2, [array1, array2]] ] # verti_k_tconst = None # [ [k2, [0, thick_k2]] ]
                    BV.hydraulic.update_poro_vertical(verti_sy_thetero)
                    
                    def Ss_formula(Sy):
                        Ss_value = 1000*9.8*(1e-10+(Sy*4.4e-10)) # rho*g*(alpha+nBeta)
                        return Ss_value
                    
                    BV.hydraulic.update_ss(Ss_formula(Sy1))
                    verti_ss_thetero = [ [Ss_formula(Sy2), [topo_init-scorie_init, topo_init-bottom_init]],
                                         [Ss_formula(Sy3), [topo_init-topo_init, topo_init-scorie_init]],
                                         ] # [ [k2, [array1, array2]] ] # verti_k_tconst = None # [ [k2, [0, thick_k2]] ]
                    BV.hydraulic.update_ss_vertical(verti_ss_thetero)
                    
                    # Ss_value = 1e-5 # rho*g*(alpha+nBeta)
                    # BV.hydraulic.update_ss(Ss_value)
                    
                    if Sy1==Sy2==Sy3 :
                        id_H_Sy ='HOMOG'
                    else:
                        id_H_Sy ='HETER'
                    
                    # model_name = iD_explo+'_'+str('model_MP')+'-'+str(id_mod_val)+'_'+\
                    #              str(id_H)+'_'+'modelK_'+str(X)+'_'+\
                    #              str(id_H_Sy)+'_'+\
                    #              str(Sy1_cp)+'-'+str(Sy2_cp)+'-'+str(Sy3_cp)+'_'+\
                    #              str(Sy1*100)+'-'+str(Sy2*100)+'-'+str(Sy3*100)
                                 
                    model_name = iD_explo+'_'+str('model')+'-'+str(id_mod_val)+'_'+\
                                 str(id_H)+'_'+\
                                 str(1)+'-'+str(1)+'-'+str(1)+'_'+\
                                 str("{:.2e}".format(K1/24/3600))+'-'+str("{:.2e}".format(K2/24/3600))+'-'+str("{:.2e}".format(K3/24/3600))
                                 # str(k1_cp)+'-'+str(k2_cp)+'-'+str(k3_cp)+'_'+\
                                     
                    print(model_name)
                    
                    BV.settings.update_model_name(model_name)

                    model_modflow = BV.preprocessing_modflow(for_calib=False)
                    
                    hk = model_modflow.hk
                    ps = model_modflow.ps
                    
                    # fig0, ax0 = plt.subplots(1,2)
                    # ax0 = ax0.ravel()
                    # im = ax0[0].imshow(hk[0], cmap='rainbow', norm=mpl.colors.LogNorm(vmin=hk.min(), vmax=hk.max()))
                    # fig.colorbar(im)
                    # sy_grid = model_modflow.ps
                    # imp = ax0[1].imshow(ps[0], cmap='rainbow',
                    #                     # norm=mpl.colors.LogNorm(vmin=hk.min(), vmax=hk.max())
                    #                     )
                    # fig.colorbar(imp)
                    
                    model_modpath = BV.preprocessing_modpath(model_modflow)
                    success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
                    
                    if success_modpath == True:
                        BV.postprocessing_modpath(model_modpath,
                                                  ending_point=True,
                                                  starting_point=True,
                                                  pathlines_shp=pathlines_shp,
                                                  particules_shp=particules_shp,
                                                  random_id=None) # None
                        
                        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                                          model_modpath=model_modpath,
                                                                          actual_date=True, 
                                                                          subbasin_results=True,
                                                                          freq_time='D')
                    
                        path_pathlines = simulations_folder+model_name+'/'+'_postprocess/_particules/'
                        shp_sim = gpd.read_file(path_pathlines+'ending.shp')
                        shp_sim.time = shp_sim.time / 365
                        shp_sim.to_file(simulations_folder+
                                             model_name+'/'+'_postprocess/_particules/'+
                                             'ending_years.shp') # time in years !
                        
                        path_pathlines = simulations_folder+model_name+'/'+'_postprocess/_particules/'
                        shp_sim = gpd.read_file(path_pathlines+'starting.shp')
                        shp_sim.time = shp_sim.time / 365
                        shp_sim.to_file(simulations_folder+
                                             model_name+'/'+'_postprocess/_particules/'+
                                             'starting_years.shp') # time in years !
                        
                        ########################################## BEGIN WEIGHTED ##########################################
                        modeldir = simulations_folder+model_name+'/'
                        namepath = model_name
                        recharge = BV.climatic.recharge
                        mf = model_modflow.mf
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
                        toolbox.export_tif(BV.geographic.watershed_box_buff_dem, sflows, -9999,
                                           simulations_folder+model_name+'/'+'_postprocess/_particules/'+'sflows_weighted.tif')
                        wbt.extract_raster_values_at_points(simulations_folder+model_name+'/'+'_postprocess/_particules/'+'sflows_weighted.tif', 
                                                            simulations_folder+model_name+'/'+'_postprocess/_particules/'+'starting_years.shp', 
                                                            out_text=False)                        
                        start = gpd.read_file(simulations_folder+model_name+'/'+'_postprocess/_particules/'+'starting_years.shp')
                        end = gpd.read_file(simulations_folder+model_name+'/'+'_postprocess/_particules/'+'ending_years.shp')
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
                                             model_name+'/'+'_postprocess/_particules/'+
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
                                             model_name+'/'+'_postprocess/_particules/'+
                                             'ending_years_masked.shp') # time in years !
                        keep_particules = masked.particleid
                        keep_particules = keep_particules.tolist()
                            
                        #### SELECT PARTICLUES ####
                        if not os.path.exists(simulations_folder+'_id_particules_random.data'):
                            id_particules_random = random.sample(keep_particules[:-1], 1000)
                            with open(simulations_folder+'_id_particules_random.data', 'wb') as f:
                                pickle.dump(id_particules_random, f)

                        crs_code = 2154
                        
                        ### PATHLINES ###
                        print('Create shapefile particules and pathlines')
                        pthobj = flopy.utils.PathlineFile(simulations_folder+model_name+'/'+model_name+'.mppth')
                        pth_data = pthobj.get_alldata()
                        
                        for k in range(len(pth_data)):
                            pth_data[k].time = pth_data[k].time / 365

                        with open(simulations_folder+'_id_particules_random.data', 'rb') as f:
                            id_particules_random = pickle.load(f)
                        
                        pth_data_save = []
                        for o, i in enumerate(id_particules_random):
                            print(o, i, len(id_particules_random))
                            for j in pth_data:
                                if i == j.particleid[0]:
                                    pth_data_save.append(j)
                                        
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
                        
                        grid_model = mf.modelgrid
                        
                        ### 1000 pathlines
                        print('1000 pathlines')
                        pthobj.write_shapefile(pathline_data=pth_data_save,
                                                shpname=simulations_folder+
                                                        model_name+'/'+'_postprocess/_particules/'+
                                                        'pathlines_1000.shp',
                                                one_per_particle=True, 
                                                direction='ending',
                                                mg=grid_model, epsg=crs_code, sr=None)
                        
                        ### 1000 particules
                        # print('1000 particules')
                        # pthobj.write_shapefile(pathline_data=pth_data_save,
                        #                         shpname=simulations_folder+
                        #                                 model_name+'/'+'_postprocess/_particules/'+
                        #                                 'particules_1000.shp',
                        #                         one_per_particle=False,
                        #                         direction='ending',
                        #                         mg=grid_model, epsg=crs_code, sr=None)
                        
                        ### FOR SPRINGS
                        path_pathlines = simulations_folder+model_name+'/'+'_postprocess/_particules/'

                        path_obs = data_path+'_CFC/'+'target_cfc_v1.shp'
                        shp_obs = gpd.read_file(path_obs)
                        shp_obs['geometry'] = shp_obs.geometry.buffer(75)
                        shp_obs.to_file(simulations_folder+
                                        model_name+'/'+'_postprocess/_particules/'+
                                        'targets_pathlines_points.shp', encoding='utf-8')
                        
                        masked = gpd.read_file(simulations_folder+
                                              model_name+'/'+'_postprocess/_particules/'+
                                              'ending_years_masked.shp') # time in years !
                        intersect = gpd.overlay(masked, shp_obs, how='intersection')
                        
                        sp_particules = intersect.particleid
                        sp_particules = sp_particules.tolist()
                        
                        # pth_data_springs = [pth_data[i] for i in sp_particules[:]]
                        
                        shp_all_pathlines = gpd.read_file(simulations_folder+
                                                  model_name+'/'+'_postprocess/_particules/'+
                                                  'pathlines_1000.shp')
                        keep = np.isin(shp_all_pathlines, sp_particules)
                        shp_springs = shp_all_pathlines[keep]
                        shp_springs.to_file(simulations_folder+
                                                  model_name+'/'+'_postprocess/_particules/'+
                                                  'pathlines_1000_springs.shp')
                        
                        print(shp_springs['time'].mean(), shp_springs['time'].median())
                        
                        # from distutils.dir_util import copy_tree
                        # toolbox.create_folder(simulations_folder+model_name+'/'+'_matchingstreams'+'_'+str(cp_each)+'/')
                        # toolbox.create_folder(simulations_folder+model_name+'/'+'_postprocess'+'_'+str(cp_each)+'/')
                        # copy_tree(simulations_folder+model_name+'/'+'_matchingstreams/', simulations_folder+model_name+'/'+'_matchingstreams'+'_'+str(cp_each)+'/')
                        # copy_tree(simulations_folder+model_name+'/'+'_postprocess/', simulations_folder+model_name+'/'+'_postprocess'+'_'+str(cp_each)+'/')
                        
                        # path_match = simulations_folder+model_name+'/'+'_matchingstreams'+'_'+str(cp_each)+'/'
                        # path_post = simulations_folder+model_name+'/'+'_postprocess'+'_'+str(cp_each)+'/'
                        # if os.path.exists(path_match):
                        #     os.remove(path_match)
                            
                        import shutil
                        if not os.path.exists(simulations_folder+model_name+'/'+'_matchingstreams'+'_'+str(cp_each)+'/'):
                            shutil.copytree(simulations_folder+model_name+'/'+'_matchingstreams/', simulations_folder+model_name+'/'+'_matchingstreams'+'_'+str(cp_each)+'/')
                        if not os.path.exists(simulations_folder+model_name+'/'+'_postprocess'+'_'+str(cp_each)+'/'):
                            shutil.copytree(simulations_folder+model_name+'/'+'_postprocess/', simulations_folder+model_name+'/'+'_postprocess'+'_'+str(cp_each)+'/')
                        
                    cp_each += 1
                
                    Sy3_cp += 1
                Sy2_cp += 1    
            Sy1_cp += 1  

#%% MODPATH EXTRACT

#%% ---- PLOT S1 S2 S3

#%% GRAPH Φ BEST


#%% ---- NOTES

            # df.loc[id_mod_val,'iD_explo'] = iD_explo
            # df.loc[id_mod_val,'id_mod_val'] = id_mod_val
            # df.loc[id_mod_val,'k1_cp'] = model_name.split('_')[4].split('-')[0]
            # df.loc[id_mod_val,'k2_cp'] = model_name.split('_')[4].split('-')[1]
            # df.loc[id_mod_val,'k3_cp'] = model_name.split('_')[4].split('-')[2]
            # df.loc[id_mod_val,'id_H'] = model_name.split('_')[3][0]
            # df.loc[id_mod_val,'model_name'] = model_name
            # df.loc[id_mod_val,'Keq'] = round(Keq, 4)
            # df.loc[id_mod_val,'K1'] = round(K1, 4)
            # df.loc[id_mod_val,'K2'] = round(K1, 4)
            # df.loc[id_mod_val,'K3'] = round(K1, 4)
            # df.loc[id_mod_val,'R'] = round(BV.climatic.recharge, 4) # mm
            # df.loc[id_mod_val,'Obs'] = round(obs, 4)
            # df.loc[id_mod_val,'Sim'] = round(sim, 4)
            # df.loc[id_mod_val,'Indicator'] = round(indicator, 4)
            # df.loc[id_mod_val,'mean_obsf_to_simf'] = round(mean_obsf_to_simf, 4)            
            # df.loc[id_mod_val,'mean_simf_to_obsf'] = round(mean_simf_to_obsf, 4)
            