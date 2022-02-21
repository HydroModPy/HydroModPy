# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé
"""

# self.masked_folder = os.path.join(self.simulations_folder, '_masked')
# file_adds.create_folder(self.masked_folder)

"""
méthode numérique de calibration: simplex, dichotomie...

function objectif définie vers un minimum
"""

import geopandas as gpd
from glob import glob
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import shutil
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

from tools import toolbox

class Dichotomy:
    def __init__(self, 
                 geographic, 
                 type_river='streams',
                 hydrology_stable=None,                 
                 simulations_folder=None):
        
        self.geographic = geographic
        self.type_river=type_river
        self.hydrology_stable=hydrology_stable
        self.simulations_folder=simulations_folder
        
        self.results_folder=os.path.join(self.simulations_folder, '_watershed/_tifs/')
        
        self.watershed_dem = geographic.watershed_dem
        self.watershed_shp = geographic.watershed_shp
        self.watershed_fill = geographic.watershed_fill
        self.watershed_direc = geographic.watershed_direc
              
        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()
        
    def prepare_files(self):
        print ('Dichotomy calibration') 
        # Clip raw observed
        streams = self.hydrology_stable + self.type_river +'.shp'
        tif_streams = self.hydrology_stable + self.type_river + '.tif'
        wbt.vector_lines_to_raster(streams, tif_streams, field="FID", base=self.watershed_dem)
        pt_streams = self.hydrology_stable + self.type_river + '_pt.shp'
        wbt.raster_to_vector_points(tif_streams, pt_streams)
        # New folder results
        self.dichotomy_folder = os.path.join(self.simulations_folder, '_dichotomy')
        toolbox.create_folder(self.dichotomy_folder)
        # Observed buff data
        self.buff_tif_obs = os.path.join(self.hydrology_stable,self.type_river+'.tif')
        self.buff_pt_obs = os.path.join(self.hydrology_stable,self.type_river+'.shp')
        # Mask observed
        self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, True)
        # Obs to points
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)  
        # Mask seepage simulation
        tif_sim = os.path.join(self.results_folder, 'seepage_areas_t(0).tif')
        self.tif_sim = os.path.join(self.dichotomy_folder,'sim.tif')
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, True)
        # Trace downslope obs
        self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
       
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

    def mean_distances(self):
        obs_to_sim = gpd.read_file(self.pt_obs_flow)
        obs_to_sim = obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        obs_to_sim = obs_to_sim[obs_to_sim['distance'] >= 0]
        self.mean_obs_to_sim = np.nanmean(obs_to_sim['distance'])
        sim_to_obs = gpd.read_file(self.pt_sim_flow)
        sim_to_obs = sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        sim_to_obs = sim_to_obs[sim_to_obs['distance'] >= 0]
        self.mean_sim_to_obs = np.nanmean(sim_to_obs['distance'])
        
        self.condition = round(self.mean_sim_to_obs / self.mean_obs_to_sim, 2)  
        return (self.mean_obs_to_sim, self.mean_sim_to_obs, self.condition)
    