# -*- coding: utf-8 -*-
"""
Created on Tue Jan 02 09:25:00 2021

@author: Ronan Abhervé
"""

import os
import sys
import geopandas as gpd
from glob import glob
import numpy as np
import imageio
import topography
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

### Method 1
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
### Method 2
# from WBT.whitebox_tools import WhiteboxTools
# wbt = WhiteboxTools()

class extract_observed:
    def __init__(self, dir_path=os.path.dirname(os.getcwd()) + '\\outcalib\\', watershed='default', 
                 type_obs='streams', tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\'):
        self.ws = os.getcwd()
        self.dir_path = dir_path
        self.watershed = watershed
        self.type_obs = type_obs
        self.data_path = self.dir_path + '\\data\\'
        self.obs_path = self.dir_path + self.watershed + '\\' + self.watershed
        self.tmp_path = tmp_path
        self.watershed_shp = self.tmp_path + 'watershed.shp'
        self.watershed_fill = self.tmp_path + 'watershed_fill.tif'
        self.sections = self.data_path + 'sections.shp'
        self.streams = self.data_path + 'streams.shp'
        self.clip_observed()
        
    def clip_observed(self):
        if self.type_obs == 'streams':
            self.clip_streams = self.obs_path + '_streams.shp'
            wbt.clip(self.streams, self.watershed_shp, self.clip_streams)
            self.tif_streams = self.obs_path + '_streams.tif'
            wbt.vector_lines_to_raster(self.clip_streams, self.tif_streams, field="FID", base=self.watershed_fill)
            self.pt_streams = self.obs_path + '_streams_pt.shp'
            wbt.raster_to_vector_points(self.tif_streams, self.pt_streams)
        if self.type_obs == 'persistent':    
            self.clip_sections = self.obs_path + '_sections.shp'
            wbt.clip(self.sections, self.watershed_shp, self.clip_sections)
            self.clip_sections_persist = gpd.read_file(self.clip_sections)
            self.clip_sections_persist = self.clip_sections_persist[self.clip_sections_persist['Persistanc'] == '4']
            self.clip_persistent = self.obs_path + '_persistent.shp'
            self.clip_sections_persist.to_file(self.clip_persistent)
            self.tif_persistent = self.obs_path + '_persistent.tif'
            wbt.vector_lines_to_raster(self.clip_persistent, self.tif_persistent, field="Persistanc", base=self.dem_path)
            self.pt_persistent = self.obs_path + '_persistent_pt.shp'
            wbt.raster_to_vector_points(self.tif_persistent, self.pt_persistent)
        return self, os.chdir(self.ws)

class generate_distances:
    def __init__(self, dir_path=os.path.dirname(os.getcwd()) + '\\outcalib\\', watershed='default',
                 sim_id=0, type_time='s', type_obs='streams', tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\'):
        self.ws = os.getcwd()
        self.dir_path = dir_path
        self.watershed = watershed
        self.sim_id = sim_id
        self.type_obs = type_obs
        self.type_time = type_time
        self.data_path = self.dir_path + '\\data\\'
        self.tmp_path = tmp_path
        self.obs_path = self.dir_path + self.watershed + '\\' + self.watershed
        self.sim_fold = self.dir_path + self.watershed + '\\' + self.sim_id + '\\'
        self.sim_path = self.dir_path + self.watershed + '\\' + self.sim_id + '\\' + self.watershed
        self.not_path = self.dir_path + self.watershed + '\\notneed\\' + self.watershed
        if not os.path.exists(self.dir_path + self.watershed + '\\notneed\\'):
            os.makedirs(self.dir_path + self.watershed + '\\notneed\\')
        self.watershed_shp = self.tmp_path + 'watershed.shp'
        self.watershed_fill = self.tmp_path + 'watershed_fill.tif'
        self.watershed_direc = self.tmp_path + 'watershed_direc.tif'  
        self.tif_obs = self.obs_path + '_streams.tif'
        self.pt_obs = self.obs_path + '_streams_pt.shp'
        self.tif_persist = self.obs_path + '_persistent.tif'
        self.pt_persist = self.obs_path + '_persistent_pt.shp'
        self.tif_sim = self.sim_fold + 'seepage.tif'
        self.tif_sim_mask = self.sim_path + '_seepage.tif'
        self.drn_sim = self.sim_fold + 'outflow.tif'
        self.drn_sim_mask = self.sim_path + '_outflow.tif'
        
        self.clip_sim()
        self.sim_to_obs()
        self.obs_to_sim()

    def clip_sim(self):
        wbt.clip_raster_to_polygon(self.tif_sim, self.watershed_shp, self.tif_sim_mask)
        wbt.clip_raster_to_polygon(self.drn_sim, self.watershed_shp, self.drn_sim_mask)
        return self, os.chdir(self.ws)

    def sim_to_obs(self):
        if self.type_obs == 'streams':
            self.dist_sim_obs = self.not_path + '_dist_sim_obs.tif'
            wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_sim_obs)
        if self.type_obs == 'persistent':
            self.dist_sim_obs = self.not_path + '_dist_sim_obs.tif'
            wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_persistent, self.dist_sim_obs)    
        self.sim_shp = self.sim_path + '_sim.shp'
        wbt.raster_to_vector_points(self.tif_sim_mask, self.sim_shp)
        self.sim_flow = self.not_path + '_simflow.tif'
        wbt.trace_downslope_flowpaths(self.sim_shp, self.watershed_direc, self.sim_flow)
        self.pt_sim_flow = self.sim_path + '_simflow.shp'
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_sim_obs, self.pt_sim_flow)
        return self, os.chdir(self.ws)
                
    def obs_to_sim(self):
        self.dist_obs_sim = self.not_path + '_dist_obs_sim.tif'
        wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_obs_sim)        
        if self.type_obs == 'streams':
            self.obs_flow = self.not_path + '_obsflow.tif'
            wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
        if self.type_obs == 'persistent':
            self.obs_flow = self.not_path + '_obsflow.tif'
            wbt.trace_downslope_flowpaths(self.pt_persistent, self.watershed_direc, self.obs_flow)        
        self.pt_obs_flow = self.sim_path + '_obsflow.shp'
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_obs_sim, self.pt_obs_flow)
        return self, os.chdir(self.ws)

class store_dataframe:
    def __init__(self, dir_path=os.path.dirname(os.getcwd()) + '\\outcalib\\', watershed='default',
                 sim_id=0, type_time='s', tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\'):
        self.ws = os.getcwd()
        self.dir_path = dir_path
        self.watershed = watershed
        self.sim_id = sim_id
        self.type_time = type_time
        self.tmp_path = tmp_path
        self.sim_list = glob(self.dir_path + self.watershed + '\\' + self.type_time + '*')
        self.sim_fold = self.dir_path + self.watershed + '\\' + self.sim_id + '\\'
        self.sim_path = self.dir_path + self.watershed + '\\' + self.sim_id + '\\' + self.watershed
        self.watershed_shp = self.tmp_path + 'watershed.shp'
        self.watershed_fill = self.tmp_path + 'watershed_fill.tif'
        self.watershed_direc = self.tmp_path + 'watershed_direc.tif'  
        self.dem = topography.dem(self.watershed_fill)	
        self.pt_obs_flow = self.sim_path + '_obsflow.shp'
        self.pt_sim_flow = self.sim_path + '_simflow.shp'
        self.drn_sim_mask = self.sim_path + '_outflow.tif'
        self.mean_distances()
        self.mean_outflow()
        
    def mean_distances(self):
        self.obs_to_sim = gpd.read_file(self.pt_obs_flow)
        self.obs_to_sim = self.obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        self.sim_to_obs = gpd.read_file(self.pt_sim_flow)
        self.sim_to_obs = self.sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        self.obs_to_sim_mean = np.nanmean(self.obs_to_sim['distance'])
        self.sim_to_obs_mean = np.nanmean(self.sim_to_obs['distance'])
        return self, os.chdir(self.ws)
    
    def mean_outflow(self):
        self.flux = imageio.imread(self.drn_sim_mask) # m3/m
        self.flux = np.ma.masked_array(self.flux, mask=(self.dem.data==-99999))
        self.cell = self.flux.count()
        self.outflow = (np.nansum(self.flux) / (self.cell * self.dem.pixel**2)) # m/m
        return self, os.chdir(self.ws)
