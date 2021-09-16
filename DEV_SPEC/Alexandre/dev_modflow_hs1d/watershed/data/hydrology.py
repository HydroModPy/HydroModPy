# -*- coding: utf-8 -*-

import os
import sys
import geopandas as gpd
import pandas as pd
import numpy as np
from osgeo import gdal, osr
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
# def my_callback(value):
#     my_callback = 0
# wbt.set_default_callback(my_callback)

class Hydrology:
    def __init__(self,out_path, type_obs, geographic, hydro_path):
        print("Extraction des données hydrologiques")
        data_folder = out_path + '/data/hydrology/'
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
                
        watershed_shp = geographic.watershed_box_shp
        watershed_dem = geographic.watershed_box_buff_dem
        
        sections = hydro_path + '/' + 'sections.shp'
        streams =  hydro_path + '/' + 'streams.shp'
        
        self.clip_observed(type_obs, watershed_shp, sections, streams, data_folder, watershed_dem)
        
    def clip_observed(self, type_obs, watershed_shp, sections, streams, data_folder, watershed_dem):
        if type_obs == 'streams':
            clip_streams = data_folder + 'streams.shp'
            wbt.clip(streams, watershed_shp, clip_streams)
            tif_streams = data_folder + 'streams.tif'
            wbt.vector_lines_to_raster(clip_streams, tif_streams, field="FID", base=watershed_dem)
            pt_streams = data_folder + 'streams_pt.shp'
            wbt.raster_to_vector_points(tif_streams, pt_streams)
            
            dem_streams = gdal.Open(tif_streams)
            self.streams_array = dem_streams.GetRasterBand(1).ReadAsArray()
            self.streams_array[self.streams_array<0] = np.nan
            
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
        return self