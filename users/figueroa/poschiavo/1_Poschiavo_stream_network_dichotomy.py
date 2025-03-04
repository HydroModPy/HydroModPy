# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
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
import glob

# Libraries need to be installed if not
import numpy as np
import pandas as pd
import datetime

import matplotlib as mpl
import matplotlib.pyplot as plt
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# # Libraries added from 'pip install' procedure
import deepdish as dd
import imageio
import geopandas as gpd
import rasterio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True

#%% ROOT

# Import HydroModPy modules
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
sys.path.append(DIR)


# from os.path import dirname, abspath
# root_dir = dirname(dirname(dirname(abspath(__file__))))
# sys.path.append(root_dir)
print("Root path directory is: {0}".format(DIR.upper()))

#%% HYDROMODPY

import flopy
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

#%% FUNCTIONS

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
                 iteration_label=None):
        
        self.geographic = watershed.geographic
        self.hydrography = watershed.hydrography
        self.calibration_folder = watershed.calibration_folder
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


#%% ---- PATHS

#%% PERSONAL

data_path = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/Data_temporal/Hydromodpy/'
gis_path = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/Raster/'

# The folder out_path is created in the example_path root directory:

# Or define it manually
out_path = 'D:/Hydromodpy/Geomechanic/'

print('The results of the example will be saved here :', out_path)

#%% ---- WATERSHED

#%% OPTIONS
KB4_loc = [2796960.102,1133328.361]
dem_path = os.path.join(gis_path, 'eu_dem_clipp_ursa_v2.tif')
# dem_path = 'C:/Users/ronan/OneDrive/UNINE/12_Data/_GIS/dem/BDALTI_fr_75m.tif'
load = False
watershed_names = ['Urse_StreamNetwork']
# watershed_name ='Strengbach'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = ['D:/Hydromodpy/examples/valdUrsa_v2/Poschiavino/results_stable/geographic/watershed.shp', 10]
from_xyv = [327816.965, 6777886.670, 150, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
bottom_path = None # path
save_object = True

#%% DICHOTOMY - RUN

vers = 'aniso2'
types_obs = ['stream_network_perenial']
fields_obs = ['fid']
hydrography_path = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/Shapes/stream_network_perenial.shp' # add hydrographic shapefiles
hydrography_path = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/Shapes/' # add hydrographic shapefiles

box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False
check_grid = True
dis_perlen = True
nlay = 1
lay_decay = 1 # 1 for no decay
thick = 50 # if bottom is None, aquifer thickness
recharge = 1/365
#print((recharge).mean()*365*1000)
first_clim = 'mean' # or 'first or value
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-2 
Klog_transf = False
sy = 1 / 100 # -
sy_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
# ss = 1e-5
ss_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1

for watershed_name in watershed_names[:]:
            
    for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):
   
        print('##### '+watershed_name.upper()+' #####')
        
        df = pd.DataFrame()
        
        BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
        area = BV.geographic.area

        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
        BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
        toolbox.create_folder(BV.calibration_folder)
        
        if not os.path.exists(stable_folder + 'hydrography/' + type_obs + '.tif'):
            BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
        else:
            BV.hydrography.streams = stable_folder + 'hydrography/' + type_obs + '.shp'
            BV.hydrography.tif_streams = stable_folder + 'hydrography/' + type_obs + '.tif'
                
        BV.add_settings()
        BV.add_climatic()
        BV.add_hydraulic()
        
        BV.settings.update_box_model(box)
        BV.settings.update_sink_fill(sink_fill)
        BV.settings.update_simulation_state(sim_state)
        BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)
        BV.climatic.update_recharge(recharge, sim_state=sim_state)
        BV.climatic.update_first_clim(first_clim)
        BV.hydraulic.update_nlay(nlay) # 1
        BV.hydraulic.update_lay_decay(lay_decay) # 1
        BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

        BV.hydraulic.update_cond_drain(cond_drain)
        BV.hydraulic.update_sy(sy)
        BV.hydraulic.update_sy_decay(sy_decay)
        # BV.hydraulic.update_ss(ss)
        # BV.hydraulic.update_ss_decay(ss_decay)
        BV.hydraulic.update_vka(vka)

        BV.hydraulic.update_hk_vertical(verti_hk)
        BV.hydraulic.update_sy_vertical(verti_sy)
        BV.hydraulic.update_ss_vertical(verti_ss)
        
        BV.add_oceanic(sea_level)
        BV.settings.update_dis_perlen(dis_perlen)
        BV.settings.update_bc_sides(bc_left, bc_right)
        BV.settings.update_input_particles(zone_partic=zone_partic)

        # Aquifer bottom
        list_bottom = [None] * 9 # aquifer flat or not
        # Decay of K
        list_d_values = [0, 300, 200, 100, 50, 40, 30, 20, 10]
        list_cond_decay = list(1/np.array(list_d_values))      
        list_cond_decay[0] = 0
        list_cond_decay = list([1,1,1,1,1,1,1,1,1]) 
        list_id_mod = [1,2,3,4,5,6,7,8,9]
        
        # for hk_decay, bottom, id_mod in zip(list_cond_decay[12:13], list_bottom[12:13], list_id_mod[12:13]):
        # for hk_decay, bottom, id_mod in zip(list_cond_decay[10:11], list_bottom[10:11], list_id_mod[10:11]):
        # for hk_decay, bottom, id_mod in zip(list_cond_decay[11:12], list_bottom[11:12], list_id_mod[11:12]):
        # for hk_decay, bottom, id_mod in zip(list_cond_decay[9:10], list_bottom[9:10], list_id_mod[9:10]):
        for hk_decay, bottom, id_mod in zip(list_cond_decay[-1:], list_bottom[-1:], list_id_mod[-1:]):

        # for cond_decay, bottom, id_mod in zip([1/25], [0], [4.5]):
            
            BV.hydraulic.update_hk_decay(hk_decay, min_value=Kmin, log_transf=Klog_transf) # 0
            BV.hydraulic.update_bottom(bottom) # 0
            
            params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
            params_df.loc[0] = ['k1','?', 1e-10*3600*24, 1e-3*3600*24, 'm/d','lin'] ### K/R 0.36 to 36 000
            params_file = 'calib_dicot_hom_1v_k1'
            params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
            
            p_min = params_df['lower_bounds'].values[0]
            p_max = params_df['higher_bounds'].values[0]
            diff = p_max - p_min
            half = (p_min + p_max) / 2
            
            gap = 1.0
            
            compt = 0
            
            while (diff > ((gap/100) * half)):
                
                half = (p_min + p_max) / 2
                hyd_cond = half.copy() # if K in calib_params.csv
                kr = hyd_cond / BV.climatic.recharge
                            
                BV.hydraulic.update_hk(hyd_cond)
                
                now = datetime.datetime.now()
                oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss") 
                
                if id_mod <=1 :
                    str_hk_decay = hk_decay
                else:
                    str_hk_decay = 1/hk_decay
                if bottom==None:
                    model_name = vers+'_'+str('model')+str(id_mod)+'_'+str(round(str_hk_decay,4))+'-'+str(round(thick,4))+'_'+str(compt)+'-'+str("{:.2e}".format(hyd_cond)) #+'-'+oclock
                else:
                    model_name = vers+'_'+str('model')+str(id_mod)+'_'+str(round(str_hk_decay,4))+'-'+str(round(bottom,4))+'_'+str(compt)+'-'+str("{:.2e}".format(hyd_cond)) #+'-'+oclock
                BV.settings.update_model_name(model_name)
                print(model_name)
                                
                model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
                success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
                
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
                                                                  datetime_format=False, 
                                                                  subbasin_results=True) # or None
            
                iter_results = MatchingStreams(BV, iteration_label=model_name)
                
                obs_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
                obs_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
                obsf_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
                obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflowf.shp'))
                
                sim_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
                sim_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
                simf_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
                simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))
            
                mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
                mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
                mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
                mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])
                
                mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
                mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
                mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
                mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])
                
                ### v1 simf/obsf - with : gap=1, streams : RNF, rec : 1000 (year)
                # obs = mean_obsf_to_simf
                # sim = mean_simf_to_obsf
                # indicator = sim/obs
                
                ### v2 simf/obs - with : gap=1, streams : RNF, rec : 1000 (year)
                # obs = mean_obs_to_simf
                # sim = mean_simf_to_obs
                # indicator = sim/obs
                # indicator = (np.log(self.mean_sim_to_obs/self.mean_obs_to_sim))**2
                
                ### v3 simf/obsf - with : gap=0.5, streams : RNF, rec : 600 (summer)
                # obs = mean_obsf_to_simf
                # sim = mean_simf_to_obsf
                # indicator = sim/obs
                
                ### v4 simf/obsf - with : gap=0.5, streams : RNF+OSM, rec : 600 (summer)
                # obs = mean_obsf_to_simf
                # sim = mean_simf_to_obsf
                # indicator = sim/obs
                
                ### v6 simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year)
                # obs = mean_obsf_to_simf
                # sim = mean_simf_to_obsf
                # indicator = sim/obs
                
                ### vf simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year) ==> isba
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
                df.loc[compt,'K_decay'] = round(hk_decay, 4) # mm
                if bottom == None:
                    df.loc[compt,'bottom'] = round(thick, 4) 
                else:
                    df.loc[compt,'bottom'] = round(bottom, 4) 
        
                df.loc[compt,'Obs'] = round(obs, 4)
                df.loc[compt,'Sim'] = round(sim, 4)
                df.loc[compt,'Indicator'] = round(indicator, 4)
                
                df.loc[compt,'mean_obs_to_sim'] = round(mean_obs_to_sim, 4)
                df.loc[compt,'mean_obs_to_simf'] = round(mean_obs_to_simf, 4)
                df.loc[compt,'mean_obsf_to_sim'] = round(mean_obsf_to_sim, 4)
                df.loc[compt,'mean_obsf_to_simf'] = round(mean_obsf_to_simf, 4)
                
                df.loc[compt,'mean_sim_to_obs'] = round(mean_sim_to_obs, 4)
                df.loc[compt,'mean_sim_to_obsf'] = round(mean_sim_to_obsf, 4)
                df.loc[compt,'mean_simf_to_obs'] = round(mean_simf_to_obs, 4)
                df.loc[compt,'mean_simf_to_obsf'] = round(mean_simf_to_obsf, 4)
                
                compt += 1
                            
            df.to_csv(BV.calibration_folder+'/'+vers+'_'+str('model')+str(id_mod)+'_dichotomy.csv', sep=';')

            id_mod += 1
            
#%% DICHOTOMY - APPEND

vers = 'aniso2'

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.DataFrame()

raws_model = glob.glob(BV.calibration_folder+'/'+vers+'_'+'*.csv')
paths_model = sorted(raws_model,
                     key=lambda item: float(item.split('\\')[-1].split('_')[1].split('model')[-1]))

for path_model in paths_model:
    print(path_model)

    df = pd.read_csv(path_model, sep=';')
        
    dfs = pd.concat([dfs, df], ignore_index = True).drop_duplicates()

dfs['Doptim'] = (dfs['Obs'] + dfs['Sim'])/2
dfs['1/K_decay'] = 1/dfs['K_decay']
dfs['1/K_decay'][dfs['1/K_decay'] == np.inf] = 0

dfs.to_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

list_id_mod = [1,2,3,4,5,6,7,8,9]

#%% DICHOTOMY - GRAPH K

dfp = dfs.copy()

dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2)

# list_id_mod = [7]
dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])
 
dfz.to_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# dfz = dfz.drop(index=dfz.iloc[:1,:].index.tolist())

# fig, ax = plt.subplots(1,1, figsize=(3.6,2.6), dpi=600)
fig, ax = plt.subplots(1,1, figsize=(4.2,4), dpi=600)

# dfz.loc[93,'Doptim'] = dfz.loc[93,'Doptim']+2

# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
# ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'], s=100, 
#             marker='s', lw=1.5, color='white', ec='k', zorder=1000
#             # cmap=mpl.colors.ListedColormap('k'),
#             # label=dfz['1/K_decay'].values[0]
#             )

ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'],
            c=dfz[:1]['1/K_decay'],
            s=100, 
              marker='s', lw=1.5,
              cmap=mpl.colors.ListedColormap('gray'), zorder=1000
            # label='0'
            )
im = ax.scatter(dfz[1:]['K']/24/3600, dfz[1:]['Doptim'], c=1/dfz[1:]['1/K_decay'], s=100, 
                cmap='plasma',
                norm=mpl.colors.LogNorm(vmin=1/300, vmax=1/10),
                lw=1.5,
                # label=df['1/cond_decay'] 
                )

dftempo = dfz.sort_values('K')
ax.plot(dftempo[:]['K']/24/3600, dftempo[:]['Doptim'],
             # c=dfz[2:]['1/K_decay'], s=100, 
             #    cmap='plasma_r',
                  # norm=mpl.colors.LogNorm(vmin=1/300, vmax=1/10),
                lw=1, c='k', zorder=-10, ls='-'
                # label=df['1/cond_decay'] 
                )

# ax.plot(dftempo[:]['K']/24/3600, dftempo[:]['Sim'],
#              # c=dfz[2:]['1/K_decay'], s=100, 
#              #    cmap='plasma_r',
#              #    norm=mpl.colors.LogNorm(vmin=10, vmax=300),
#                 lw=1, c='grey', zorder=-10, ls='-'
#                 # label=df['1/cond_decay'] 
#                 )

# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('$K_{max}$ [m/s]')
ax.set_xlim(1e-7, 1e-5)
ax.set_ylim(25 , 100)
ax.set_ylabel('$D_{optim}$ [m]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.10, 0.03, 0.8]))
# for t in cb.ax.get_yticklabels():
#      t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticks((1/np.array([300, 200, 100, 50, 40, 30])).round(4))
# cb.set_ticklabels((1/np.array([300, 200, 100, 50, 40, 30])).round(3), fontsize=8)

# cb.ax.tick_params(direction='out', length=5, width=1, colors='k',
#                   grid_color='k', grid_alpha=0.5)
for t in cb.ax.get_yticklabels():
     t.set_fontsize(9)
# cb.minorticks_off(False)
cb.ax.tick_params(direction='out', which = 'minor', length = 2, color = 'k')
cb.ax.tick_params(direction='out', which = 'major', length = 4, color = 'k' )
cb.ax.minorticks_on()
cb.ax.set_ylabel('1/α [m]', rotation=270, labelpad=25)

# ax.axvline(x=(dfz[5:6]['K']/24/3600).values, c='darkgreen', zorder=-1000, ls='-', lw=1.5)
# ax.axhline(y=(dfz[5:6]['Doptim']).values, c='darkgreen', zorder=-1000, ls='-', lw=1.5)

# ax.grid()

# ax.set_yscale('log')

# fig.savefig(fig_path+'/02_fig_dichotomy/'+
#             'DICHOTOMY_K_3'+'.png',
#             bbox_inches='tight')

#%% DICHOTOMY - MAPS

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

dfp = dfs.copy()
dfp['1/K_decay'] = 1/dfp['K_decay']
dfp['1/K_decay'][dfp['1/K_decay'] == np.inf] = 0
dfp['Doptim'] = (dfp['Obs'] + dfp['Sim'])/2

shp_bv = gpd.read_file(BV.geographic.watershed_shp)
  
if vers == 'aniso2':
    shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'hydrographic_mix_peren_upv2_pt.shp')    

dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    

for index, row in dfz[:].iterrows():
    model_name = row['model_name']
    print(model_name)
    
    mf = flopy.modflow.Modflow.load(BV.calibration_folder+'/'+model_name+'/'+model_name+'.nam')
            
    # fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    
    fig, ax = plt.subplots(1,1, figsize=(10,10))
    
    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    # hil = rasterio.open('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/hillshade_classic.tif')

    # rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
    #                           ax=ax, transform=dem.transform,
    #                           cmap='Greys_r', alpha=1, zorder=-5)

    rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.25, zorder=-5)
    
    shp = gpd.read_file(BV.calibration_folder+'/'+str(model_name)+'/'+'_matchingstreams/'+'sim_pt.shp')
    
    shp_bv.plot(ax=ax, facecolor='None', lw=3)
    # shp_hydro.plot(ax=ax, color='navy', lw=0)
    shp.plot(ax=ax, color='darkorange', lw=0)
    
    plt.yticks(rotation=90, ha='right')
    
    ax.set_title(model_name, fontsize=7)
    
    # fig.savefig('C:/Users/ronan/Downloads/figs/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    # fig.savefig('C:/Users/ronan/Downloads/figs_'+vers+'/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')

    # fig.savefig(fig_path+'/02_fig_dichotomy/maps3/'+
    #             model_name+'_DICHOTOMY_MAP'+'.png',
    #             bbox_inches='tight')

#%%
os.chdir(DIR)
