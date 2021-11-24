# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 14:52:56 2021

@author: Alexandre Gauvain
"""

import os
import geopandas as gpd
import numpy as np
from osgeo import gdal
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

class Hydrology:
    def __init__(self, out_path, type_obs, geographic, hydro_path):
        print("Extraction des données hydrologiques")
        data_folder = out_path + '/results_stable/hydrology/'
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        
        # watershed_shp = geographic.watershed_box_shp
        # watershed_dem = geographic.watershed_box_buff_dem
        
        watershed_shp = geographic.watershed_shp
        watershed_dem = geographic.watershed_dem
        
        sections = hydro_path + '/' + 'sections_fr.shp'
        streams =  hydro_path + '/' + 'streams_fr.shp'
        zh_digit = hydro_path + '/' + 'zh_digit.shp'
        stream_digit = hydro_path + '/' + 'stream_digit.shp'
        
        self.clip_observed(type_obs, watershed_shp, sections, streams, data_folder, watershed_dem)
        try:
            self.clip_zh(zh_digit, data_folder, watershed_shp, watershed_dem)
        except:
            pass
        try:
            self.clip_stream(stream_digit, data_folder, watershed_shp, watershed_dem)
        except:
            pass
        
    def clip_observed(self, type_obs, watershed_shp, sections, streams, data_folder, watershed_dem):
        # if type_obs == 'streams':
        self.streams = data_folder + 'streams.shp'
        wbt.clip(streams, watershed_shp, self.streams)
        tif_streams = data_folder + 'streams.tif'
        wbt.vector_lines_to_raster(self.streams, tif_streams, field="FID", base=watershed_dem)
        pt_streams = data_folder + 'streams_pt.shp'
        wbt.raster_to_vector_points(tif_streams, pt_streams)
    
        dem_streams = gdal.Open(tif_streams)
        self.streams_array = dem_streams.GetRasterBand(1).ReadAsArray()
        self.streams_array[self.streams_array<0] = np.nan
        
        # if type_obs == 'sections':    
        clip_sections = data_folder + 'sections.shp'
        wbt.clip(sections, watershed_shp, clip_sections)
        tif_sections = data_folder + 'sections.tif'
        wbt.vector_lines_to_raster(clip_sections, tif_sections, field="Persistanc", base=watershed_dem)
        pt_sections = data_folder + 'sections_pt.shp'
        wbt.raster_to_vector_points(tif_sections, pt_sections)
            
        if type_obs == 'persistent':    
            clip_sections = data_folder + 'sections.shp'
            wbt.clip(sections, watershed_shp, clip_sections)
            clip_sections_persist = gpd.read_file(clip_sections)
            clip_sections_persist = clip_sections_persist[clip_sections_persist['Persistanc'] == '4']
            clip_persistent = data_folder + 'persistent.shp'
            clip_sections_persist.to_file(clip_persistent)
            tif_persistent = data_folder + 'persistent.tif'
            wbt.vector_lines_to_raster(clip_persistent, tif_persistent, field="Persistanc", base=watershed_dem)
            pt_persistent = data_folder + 'persistent_pt.shp'
            wbt.raster_to_vector_points(tif_persistent, pt_persistent)
            
        if type_obs == 'intermittent':    
            clip_sections = data_folder + 'sections.shp'
            wbt.clip(sections, watershed_shp, clip_sections)
            clip_sections_intermit = gpd.read_file(clip_sections)
            clip_sections_intermit = clip_sections_intermit[clip_sections_intermit['Persistanc'] == '3']
            clip_intermittent = data_folder + 'intermittent.shp'
            clip_sections_intermit.to_file(clip_intermittent)
            tif_intermittent = data_folder + 'intermittent.tif'
            wbt.vector_lines_to_raster(clip_intermittent, tif_intermittent, field="Persistanc", base=watershed_dem)
            pt_intermittent = data_folder + 'intermittent_pt.shp'
            wbt.raster_to_vector_points(tif_intermittent, pt_intermittent)
    
    def clip_zh(self, zh_digit, data_folder, watershed_shp, watershed_dem):
        try:
            clip_zh = data_folder + 'zh_digit.shp'
            wbt.clip(zh_digit, watershed_shp, clip_zh)
            tif_zh = data_folder + 'zh_digit.tif'
            wbt.vector_polygons_to_raster(clip_zh, tif_zh, field="FID", base=watershed_dem)
            pt_zh = data_folder + 'zh_digit_pt.shp'
            wbt.raster_to_vector_points(tif_zh, pt_zh)
        except:
            print('There is no wetlands in data')
    
    def clip_stream(self, stream_digit, data_folder, watershed_shp, watershed_dem):
        try:
            clip_stream = data_folder + 'stream_digit.shp'
            wbt.clip(stream_digit, watershed_shp, clip_stream)
            tif_stream = data_folder + 'stream_digit.tif'
            wbt.vector_lines_to_raster(clip_stream, tif_stream, field="FID", base=watershed_dem)
            pt_stream = data_folder + 'stream_digit_pt.shp'
            wbt.raster_to_vector_points(tif_stream, pt_stream)
        except:
            print('There is no streams in data')