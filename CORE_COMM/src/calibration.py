# -*- coding: utf-8 -*-

import os
import sys
import geopandas as gpd
import pandas as pd
import numpy as np
import imageio
import topography
from IPython.core.debugger import set_trace as st
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
    def __init__(self, watershed='name', type_obs='streams', data_path=os.path.dirname(os.getcwd())+'\\data\\',
                 out_path=os.path.dirname(os.getcwd())+'\\output\\'):
        
        self.ws = os.getcwd()
        self.watershed = watershed
        self.type_obs = type_obs
        self.data_path = data_path
        self.out_path = out_path
        
        self.out_fold = self.out_path + self.watershed + '/'
        
        self.gis_path = self.out_fold + '/gis/'
        self.obs_path = self.out_fold + '/obs/'
        if not os.path.exists(self.obs_path):
            os.makedirs(self.obs_path)
                
        self.watershed_shp = self.gis_path + 'watershed.shp'
        self.watershed_fill = self.gis_path + 'watershed_fill.tif'
        
        self.sections = self.data_path + 'sections.shp'
        self.streams = self.data_path + 'streams.shp'
        
        self.clip_observed()
        
    def clip_observed(self):
        if self.type_obs == 'streams':
            self.clip_streams = self.obs_path + 'streams.shp'
            wbt.clip(self.streams, self.watershed_shp, self.clip_streams)
            self.tif_streams = self.obs_path + 'streams.tif'
            wbt.vector_lines_to_raster(self.clip_streams, self.tif_streams, field="FID", base=self.watershed_fill)
            self.pt_streams = self.obs_path + 'streams_pt.shp'
            wbt.raster_to_vector_points(self.tif_streams, self.pt_streams)
        if self.type_obs == 'persistent':    
            self.clip_sections = self.obs_path + 'sections.shp'
            wbt.clip(self.sections, self.watershed_shp, self.clip_sections)
            self.clip_sections_persist = gpd.read_file(self.clip_sections)
            self.clip_sections_persist = self.clip_sections_persist[self.clip_sections_persist['Persistanc'] == '4']
            self.clip_persistent = self.obs_path + 'persistent.shp'
            self.clip_sections_persist.to_file(self.clip_persistent)
            self.tif_persistent = self.obs_path + 'persistent.tif'
            wbt.vector_lines_to_raster(self.clip_persistent, self.tif_persistent, field="Persistanc", base=self.dem_path)
            self.pt_persistent = self.obs_path + 'persistent_pt.shp'
            wbt.raster_to_vector_points(self.tif_persistent, self.pt_persistent)
        return self, os.chdir(self.ws)

class generate_distances:
    def __init__(self, watershed='name', type_obs='streams', type_time='s', sim_id='identify', data_path = os.path.dirname(os.getcwd())+'\\data\\',
                 out_path=os.path.dirname(os.getcwd())+'\\output\\'):
        
        self.ws = os.getcwd()
        self.watershed = watershed
        self.type_obs = type_obs
        self.sim_id = sim_id
        self.data_path = data_path
        self.out_path = out_path
        
        self.out_fold = self.out_path + self.watershed + '/'
        
        self.gis_path = self.out_fold + '/gis/'
        self.obs_path = self.out_fold + '/obs/'
        if not os.path.exists(self.obs_path):
            os.makedirs(self.obs_path)
        
        self.sim_fold = self.out_fold + self.sim_id + '/'
        
        self.not_path = self.out_fold + 'notneed\\'
        if not os.path.exists(self.not_path):
            os.makedirs(self.not_path)
            
        self.watershed_shp = self.gis_path + 'watershed.shp'
        self.watershed_fill = self.gis_path + 'watershed_fill.tif'
        self.watershed_direc = self.gis_path + 'watershed_direc.tif'
        
        self.tif_obs = self.obs_path + 'streams.tif'
        self.pt_obs = self.obs_path + 'streams_pt.shp'
        self.tif_persist = self.obs_path + 'persistent.tif'
        self.pt_persist = self.obs_path + 'persistent_pt.shp'
        
        self.seep_sim = self.sim_fold + 'seepage.tif'
        self.seep_sim_mask = self.sim_fold + 'mask_seepage.tif'
        self.drn_sim = self.sim_fold + 'outflow.tif'
        self.drn_sim_mask = self.sim_fold + 'mask_outflow.tif'
        self.wt_sim = self.sim_fold + 'watertable.tif'
        self.wt_sim_mask = self.sim_fold + 'mask_watertable.tif'

        if self.type_obs == 'streams':
            self.obs_flow = self.sim_fold + 'obsflow.tif'
            wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
        if self.type_obs == 'persistent':
            self.obs_flow = self.sim_fold + 'obsflow.tif'
            wbt.trace_downslope_flowpaths(self.pt_persistent, self.watershed_direc, self.obs_flow)
        
        self.clip_sim()
        self.sim_to_obs()
        self.obs_to_sim()

    def clip_sim(self):
        wbt.clip_raster_to_polygon(self.seep_sim, self.watershed_shp, self.seep_sim_mask)
        wbt.clip_raster_to_polygon(self.drn_sim, self.watershed_shp, self.drn_sim_mask)
        wbt.clip_raster_to_polygon(self.wt_sim, self.watershed_shp, self.wt_sim_mask)
        return self, os.chdir(self.ws)

    def sim_to_obs(self):
        if self.type_obs == 'streams':
            self.dist_sim_obs = self.sim_fold + 'dist_sim_obs.tif'
            wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_sim_obs)  #tif_obs
        if self.type_obs == 'persistent':
            self.dist_sim_obs = self.sim_fold + 'dist_sim_obs.tif'
            wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_sim_obs) #tif_persistent   
        self.sim_shp = self.sim_fold + 'sim.shp'
        wbt.raster_to_vector_points(self.seep_sim_mask, self.sim_shp)
        self.sim_flow = self.sim_fold + 'simflow.tif'
        wbt.trace_downslope_flowpaths(self.sim_shp, self.watershed_direc, self.sim_flow)
        self.pt_sim_flow = self.sim_fold + 'simflow.shp'
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_sim_obs, self.pt_sim_flow)
        return self, os.chdir(self.ws)
                
    def obs_to_sim(self):
        self.dist_obs_sim = self.sim_fold + 'dist_obs_sim.tif'
        wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_obs_sim)                
        self.pt_obs_flow = self.sim_fold + 'obsflow.shp'
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_obs_sim, self.pt_obs_flow)
        return self, os.chdir(self.ws)

class store_dataframe:
    def __init__(self, watershed='name', type_obs='streams', type_time='s', sim_id='identify',
                 out_path=os.path.dirname(os.getcwd())+'\\output\\'):
        self.ws = os.getcwd()
        self.watershed = watershed
        self.type_time = type_time
        self.sim_id = sim_id
        self.out_path = out_path
        
        self.out_fold = self.out_path + self.watershed + '\\'
        
        self.gis_path = self.out_fold + '/gis/'
        self.obs_path = self.out_fold + '/obs/'

        self.sim_fold = self.out_fold + self.sim_id + '\\'

        self.watershed_fill = self.gis_path + 'watershed_fill.tif'
        self.dem = topography.dem(self.watershed_fill)
        
        self.pt_obs_flow = self.sim_fold + 'obsflow.shp'
        self.pt_sim_flow = self.sim_fold + 'simflow.shp'
        
        self.drn_sim_mask = self.sim_fold + 'mask_outflow.tif'
        
        self.mean_distances()
        self.mean_outflow()
        
    def mean_distances(self):
        self.obs_to_sim = gpd.read_file(self.pt_obs_flow)
        self.obs_to_sim = self.obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        self.obs_to_sim = self.obs_to_sim[self.obs_to_sim['distance'] >= 0]
        self.obs_to_sim_mean = np.nanmean(self.obs_to_sim['distance'])
        self.sim_to_obs = gpd.read_file(self.pt_sim_flow)
        self.sim_to_obs = self.sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        self.sim_to_obs = self.sim_to_obs[self.sim_to_obs['distance'] >= 0]
        self.sim_to_obs_mean = np.nanmean(self.sim_to_obs['distance'])
        return self, os.chdir(self.ws)
    
    def mean_outflow(self):
        self.flux = imageio.imread(self.drn_sim_mask) # L/T
        self.flux = np.ma.masked_array(self.flux, mask=(self.dem.data==-99999))
        self.cell = self.flux.count()
        self.outflow = (np.nansum(self.flux) / (self.cell * self.dem.pixel**2)) # M/T
        return self, os.chdir(self.ws)

class store_dataframe_het:
    def __init__(self, geology, watershed='name', type_obs='streams', type_time='s', sim_id='identify',
                 out_path=os.path.dirname(os.getcwd())+'\\output\\', ):
        self.ws = os.getcwd()
        self.watershed = watershed
        self.type_time = type_time
        self.sim_id = sim_id
        self.out_path = out_path
        self.geology = geology
        
        self.out_fold = self.out_path + self.watershed + '\\'
        
        self.gis_path = self.out_fold + '/gis/'
        self.obs_path = self.out_fold + '/obs/'

        self.sim_fold = self.out_fold + self.sim_id + '\\'

        self.watershed_fill = self.gis_path + 'watershed_fill.tif'
        self.dem = topography.dem(self.watershed_fill)
        
        self.pt_obs_flow = self.sim_fold + 'obsflow.shp'
        self.pt_sim_flow = self.sim_fold + 'simflow.shp'

        self.dist_obs_sim = self.sim_fold + 'dist_obs_sim.tif'
        self.dist_sim_obs = self.sim_fold + 'dist_sim_obs.tif'
        self.obs_flow = self.sim_fold + 'obsflow.tif'
        self.sim_flow = self.sim_fold + 'simflow.tif'
        
        self.drn_sim_mask = self.sim_fold + 'mask_outflow.tif'
        
        self.mean_distances()
        self.mean_outflow()
        
    def mean_distances(self):
        obs_sim_dist = imageio.imread(self.dist_obs_sim)
        sim_obs_dist = imageio.imread(self.dist_sim_obs)
        obs = imageio.imread(self.obs_flow)
        sim = imageio.imread(self.sim_flow)
        obs_dist = np.zeros(np.shape(obs))*np.nan
        sim_dist = np.zeros(np.shape(sim))*np.nan
        obs_dist[obs>=0] = obs_sim_dist[obs>=0]
        sim_dist[sim>=0] = sim_obs_dist[sim>=0]
        sim_dist[sim_dist<0] = 0
        self.mean_dist_code = pd.DataFrame()
        compt = 0
        for i in range (0, len(self.geology.geology_code)):
            self.mean_dist_code.loc[compt,'code'] = int(self.geology.geology_code[i])
            self.mean_dist_code.loc[compt,'obs_to_sim'] = np.nanmean(obs_dist[self.geology.geology_array_clip==self.geology.geology_code[i]])
            self.mean_dist_code.loc[compt,'sim_to_obs'] = np.nanmean(sim_dist[self.geology.geology_array_clip==self.geology.geology_code[i]])
            compt += 1
        '''
        self.mean_dist_code.loc[compt+1,'code'] = 'all'
        self.mean_dist_code.loc[compt+1,'obs_to_sim'] = np.nanmean(obs_dist)
        self.mean_dist_code.loc[compt+1,'sim_to_obs'] = np.nanmean(sim_dist)
        '''
        self.mean_dist_code.loc[:,'ratio_dist']=self.mean_dist_code.loc[:,'sim_to_obs']/self.mean_dist_code.loc[:,'obs_to_sim'] 
        self.mean_dist_code = self.mean_dist_code.replace(np.nan, -9999)
        
        '''self.obs_to_sim = gpd.read_file(self.pt_obs_flow)
                                self.obs_to_sim = self.obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
                                self.obs_to_sim = self.obs_to_sim[self.obs_to_sim['distance'] >= 0]
                                self.obs_to_sim_mean = np.nanmean(self.obs_to_sim['distance'])
                                self.sim_to_obs = gpd.read_file(self.pt_sim_flow)
                                self.sim_to_obs = self.sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
                                self.sim_to_obs = self.sim_to_obs[self.sim_to_obs['distance'] >= 0]
                                self.sim_to_obs_mean = np.nanmean(self.sim_to_obs['distance'])'''
        return self, os.chdir(self.ws)
    
    def mean_outflow(self):
        self.flux = imageio.imread(self.drn_sim_mask) # L/T
        self.flux = np.ma.masked_array(self.flux, mask=(self.dem.data==-99999))
        self.cell = self.flux.count()
        self.outflow = (np.nansum(self.flux) / (self.cell * self.dem.pixel**2)) # M/T
        return self, os.chdir(self.ws)