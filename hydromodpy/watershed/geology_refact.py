# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
import os
import numpy as np
import rasterio
import whitebox
import pandas as pd
import geopandas as gpd

from typing import Optional, Union, List # TT [user] --> Currently installed typing-3.7.4.3
from hydromodpy.tools import get_logger
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

logger = get_logger(__name__)

#%% CLASS

class Geology:
    """
    Load geographic data from different sources 
    """
        
    def __init__(self, 
                 result_data_path : str, # class initialization --> exemple 12 
                 geographic : object, # maybe changed
                 geol_data_source: str,
                 geol_field_name : Optional[str] = None, 
                 longitude : Optional[int] = 0,  
                 latitude : Optional[int] = 1,  
                 crs : Optional[int] = 4326 
    ):
        """
        Parameters
        ----------
        result_data_path : str
            Path of the folder for geology output in the HydroModPy results.
        geographic : object
            Variable object of the model domain (catchment).
        geol_data_source : str
            Path of the data source for geology. It can be a shapefile (source : BRGM or other) or a CSV file.
        geol_field_name : str
            Field label of the geological data source. 
                For example, geological field it is 'CODE_LEG' for BRGM shapefile.
        longitude : int
            Column's number for longitude in CSV (optional, default: 0, the first column).
        latitude : int
            Column's number for latitude in CSV (optional, default: 1, the second column).
        crs : int
            crs code for coordinate system (optional, default: 4326 for WGS 84).
        """
        # logger.info("Extracting geology data from %s", geol_data_source)
        
        self.geol_output_folder = os.path.join(result_data_path,'geology')
        if not os.path.exists(self.geol_output_folder):
                os.makedirs(self.geol_output_folder)
                
        self.geographic = geographic
        self.geol_data_source = geol_data_source
        self.geol_field_name = geol_field_name
        self.longitude = longitude
        self.latitude = latitude
        self.crs = crs
        self.structure_dem_path =  os.path.join(self.geol_output_folder, 'GeoStructure.tif')
        self.structure_clip =  os.path.join(self.geol_output_folder, 'GeoStructure_clip.tif')
        
        self._read_geological_data()
        self._generate_structure_dem()
        self._geology_array()
        
    #%% FUNCTIONS
    def _read_geological_data(self):
        """
        Read geological data from file based on its extension.
        Supports .shp (shapefile), .csv (comma-separated values) and .tif or .tiff (raster) files.
        -------
        self
            Stores the geological data in self.geology_data attribute.
        """
        # Get file extension (last 4 characters or more if needed)
        file_extension = os.path.splitext(self.geol_data_source)[1].lower()
        
        try:
            if file_extension == '.shp':
                # Read shapefile using GeoPandas
                self.geol_data = gpd.read_file(self.geol_data_source)
                logger.info(f"Shapefile loaded: {self.geol_data_source}")
                
            elif file_extension == '.csv':
                # Read CSV file and convert to shapefile
                geol_data = os.path.join(self.geol_output_folder, 'geology.shp')
                wbt.csv_points_to_vector(i = self.geol_data_source, 
                                         output = geol_data, 
                                         x_field = self.longitude, 
                                         y_field = self.latitude, 
                                         epsg = self.crs) # The others fields in the CSV file will be added as attributes in the shapefile
                self.geol_data = gpd.read_file(geol_data) 
                logger.info(f"CSV file loaded and converted to shapefile: {self.geol_data_source}")
                
            elif file_extension == '.tif' or file_extension == '.tiff':
                self.geol_field_name = 'VALUE' #!Vérifier si c'est bien le nom du champ pris par défaut dans les rasters
                geol_data = os.path.join(self.geol_output_folder, 'geology.shp')
                wbt.raster_to_vector_polygons(i=self.geol_data_source, output = geol_data)
                self.geol_data = gpd.read_file(geol_data)
                logger.info(f"Raster file load and converted to shapefile: {self.geol_data_source}")
                
            else:
                raise ValueError(f"Unsupported file format: {file_extension}. "
                               f"Supported formats are .shp, .csv, and .tif or .tiff")
                
        except Exception as e:
            logger.error(f"Error reading geological data from {self.geol_data_source}: {str(e)}")
            raise
        
        return self
    
    def _generate_structure_dem(self):
        """
        Generate a DEM of geological structure from the geological data source.
        -------
        self
            Creates a raster file of geological structure in the geology output folder.
        """
        wbt.vector_polygons_to_raster(i=self.geol_data, 
                                      output=self.structure_dem_path, 
                                      field=self.geol_field_name, 
                                      nodata=None, 
                                      base=self.geographic.box_buff)
        
        wbt.clip_raster_to_polygon(i=self.structure_dem_path, 
                                   polygon=self.geographic.box_buff, 
                                   output=self.structure_clip)
        self.structure_clip
        return self

    def _geology_array(self):
        """
        Create a 2D array of geological structure from the generated DEM.
        -------
        self
            Stores the geological structure array in self.geology_array attribute.
        """

        with rasterio.open(self.structure_clip) as structure_clip:
            self.geol_array_clip = structure_clip.read(1).astype(str)
        self.geol_code_clip = np.unique(self.geol_array_clip)
        self.geol_code = self.geol_code_clip[self.geol_code_clip>=0]
        return self

    # def geo_to_K(self, K_geo_values):
    #     """
    #     Parameters
    #     ----------
    #     K_geo_values : list
    #         List of K values according to geology code number.

    #     Returns
    #     -------
    #     self
    #         Add some variable in Geology class self object.
    #     """
    #     self.K_array = self.geol_array
    #     for i in range(0,len(self.geol_code)):
    #         self.K_array[self.geol_array==self.geol_code[i]] = K_geo_values[i]
    #     """
    #     geology_array: 2D arrays - code of geology entities
    #     K_geo_values: 1D array (same size that geology code variable)
    #         correspondence between geology codes and hydraulique conductivity values 
    #     """  
        
    #     return self

#%% NOTES
        