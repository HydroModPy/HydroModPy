# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% LIBRAIRIES

# Python
import os
import pandas as pd
import geopandas as gpd
import numpy as np
from osgeo import gdal
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% CLASS

class Hydrography:
    
    #%% INIT
    
    def __init__(self, out_path, types_obs, fields_obs, geographic, hydro_path):
        
        print("Extract hydrography from specific data")
        
        data_folder = out_path + '/results_stable/hydrology/'
        if not os.path.exists(data_folder):
            os.makedirs(data_folder)
        
        self.hydro_path = hydro_path 
        
        watershed_shp = geographic.watershed_shp # watershed_shp = geographic.watershed_box_shp
        watershed_dem = geographic.watershed_dem # watershed_dem = geographic.watershed_box_buff_dem

        for type_obs, field_obs in zip(types_obs, fields_obs):
            try:
                self.clip_observed(type_obs, field_obs, hydro_path, data_folder, watershed_shp, watershed_dem)
            except ValueError as e:
                print(e)
                pass
    
    #%% FUNCTIONS
    
    def clip_observed(self, type_obs, field_obs, hydro_path, data_folder, watershed_shp, watershed_dem):
        
        streams = hydro_path + '/' +  type_obs +'.shp'
        self.streams = data_folder + type_obs +'.shp'
        
        # First clip of the shape file at the watershed scale (classical GIS function performed here in geopandas)
        streams_file = gpd.read_file(streams)
        watshd_file = gpd.read_file(watershed_shp)
        file_clipped = gpd.clip(streams_file, watshd_file) # wbt.clip(streams, watershed_shp, self.streams)
        
        # Saves clipped file to the reuslts file structure
        file_clipped.to_file(self.streams)
        
        # Transforms shapefile to raster file (.tif format)
        shp_base = gpd.read_file(self.streams)
        shp_type = shp_base.geometry.type[0] # forma = forma.geom_type[0]
        self.tif_streams = data_folder + type_obs + '.tif'
        shp_base[field_obs] = pd.to_numeric(shp_base[field_obs])
        shp_base.to_file(self.streams)
        
        if (shp_type == 'MultiPolygon') | (shp_type == 'Polygon'): # if shp_type == 'LineString':
            # print(shp_type)
            # e.g. wetlands and ponds
            wbt.dissolve(self.streams, self.streams)
            wbt.vector_polygons_to_raster(self.streams, self.tif_streams, field=field_obs, base=watershed_dem)
        if (shp_type == 'MultiLineString') | (shp_type == 'LineString') | (shp_type == 'Line'):
            # print(shp_type)
            # e.g. streams
            wbt.vector_lines_to_raster(self.streams, self.tif_streams,
                                       # field=field_obs,
                                       base=watershed_dem)
        if (shp_type == 'Point') | (shp_type == 'MultiPoint') :
            # print(shp_type)
            # e.g. landslides, sources, wells
            wbt.vector_points_to_raster(self.streams, self.tif_streams, field=field_obs, base=watershed_dem)
        
        wbt.set_nodata_value(
                    self.tif_streams, 
                    self.tif_streams, 
                    back_value=-32768)
        
        dem_streams = gdal.Open(self.tif_streams)
        self.streams_array = dem_streams.GetRasterBand(1).ReadAsArray()
        self.streams_array = self.streams_array.astype(float)
        self.streams_array[self.streams_array<0] = np.nan
                
        pt_streams = data_folder + type_obs + '_pt.shp'
        wbt.raster_to_vector_points(self.tif_streams, pt_streams)
        
#%% NOTES
