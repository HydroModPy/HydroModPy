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

from typing import Optional, Union, List #Currently installed typing-3.7.4.3
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
                 result_data_path : str, 
                 geographic : object,
                 geol_data_source: str,
                 geol_field_name : Optional[str] = None, 
                 longitude : Optional[int] = None,  
                 latitude : Optional[int] = None,  
                 crs : Optional[int] = None
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
            Column's number for longitude in CSV (optional).
        latitude : int
            Column's number for latitude in CSV (optional).
        crs : int
            crs code for coordinate system in CSV (optional).
        """
        # logger.info("Extracting geology data from %s", geol_data_source)
        
        self.geol_output_folder = os.path.join(result_data_path,'geology')
        if not os.path.exists(self.geol_output_folder):
                os.makedirs(self.geol_output_folder)
                
        self.geographic = geographic
        self.geol_data_source = geol_data_source
        self.geol_field_name = geol_field_name #! Only needed for methods in comments
        self.longitude = longitude
        self.latitude = latitude
        self.crs = crs
        
        # self.check_projection()
        self.read_and_clip_geological_data()
        
    #%% FUNCTIONS
        
    # def check_projection(self):
    #     if self.crs == self.geographic.crs_project: #! check the name of the global crs to ensure it is the same as the one used in the geological data source
    #         logger.info("Projection of geological data is consistent with the model domain.")
    #     else:
    #         logger.error(f"Error checking projection of geological data: {str(e)}")
    #         raise
        
    def read_and_clip_geological_data(self):
        """
        Read geological data from file based on its extension.
        Supports .shp (shapefile), .csv (comma-separated values) and .tif or .tiff (raster) files.
        -------
        self
            Stores the geological data in self.geol_data attribute.
        """
        # Get file extension (last 4 characters or more if needed)
        file_extension = os.path.splitext(self.geol_data_source)[1].lower()
            
        if file_extension == '.shp':
            # Read shapefile using GeoPandas
            geol_data = gpd.read_file(self.geol_data_source)
            mask_gdf = gpd.read_file(self.geographic.box_buff)
            self.geol_data = gpd.clip(gdf=geol_data, mask=mask_gdf) 
            logger.info(f"Shapefile loaded and clipped: {self.geol_data_source}")
            
        elif file_extension == '.csv':
            # Read CSV file using Pandas
            geol_data = pd.read_csv(self.geol_data_source)
            geol_data = gpd.GeoDataFrame(geol_data, 
                            geometry=gpd.points_from_xy(x = geol_data.iloc[:, self.longitude], 
                                                        y = geol_data.iloc[:, self.latitude], 
                                                        crs = self.crs)
                            )
            mask_gdf = gpd.read_file(self.geographic.box_buff)
            self.geol_data = gpd.clip(gdf=geol_data, mask=mask_gdf) 
            logger.info(f"CSV file loaded and clipped: {self.geol_data_source}")

        elif file_extension in ('.tif', '.tiff'):
            self.geol_data = os.path.join(self.geol_output_folder, 'geol_clip.tif')
            wbt.clip_raster_to_polygon(i=self.geol_data_source, 
                                    polygon=self.geographic.box_buff, 
                                    output=self.geol_data)
            logger.info(f"Raster file loaded and clipped: {self.geol_data_source}")
        else :
            raise ValueError(f"Unsupported file format: {file_extension}. "
                            f"Supported formats are .shp, .csv, and .tif or .tiff") 
    
        return self

    # def read_geological_data_and_transform_in_shp(self):
    #     """
    #     Read geological data from file based on its extension.
    #     Supports .shp (shapefile), .csv (comma-separated values) and .tif or .tiff (raster) files.
    #     -------
    #     self
    #         Stores the geological data in self.geol_data attribute.
    #     """
    #     # Get file extension (last 4 characters or more if needed)
    #     file_extension = os.path.splitext(self.geol_data_source)[1].lower()
        
    #     try:
    #         if file_extension == '.shp':
    #             # Read shapefile using GeoPandas
    #             self.geol_data = gpd.read_file(self.geol_data_source)
    #             logger.info(f"Shapefile loaded: {self.geol_data_source}")

    #         elif file_extension == '.csv':
    #             # Read CSV file and convert to shapefile
    #             geol_data = os.path.join(self.geol_output_folder, 'geology.shp')
    #             wbt.csv_points_to_vector(i = self.geol_data_source, 
    #                                      output = geol_data, 
    #                                      x_field = self.longitude, 
    #                                      y_field = self.latitude, 
    #                                      epsg = self.crs) # The others fields in the CSV file will be added as attributes in the shapefile
    #             self.geol_data = gpd.read_file(geol_data) 
    #             logger.info(f"CSV file loaded and converted to shapefile: {self.geol_data_source}")
                
    #         elif file_extension == '.tif' or file_extension == '.tiff':
    #             self.geol_field_name = 'VALUE' #!Vérifier si c'est bien le nom du champ pris par défaut dans les rasters
    #             geol_data = os.path.join(self.geol_output_folder, 'geology.shp')
    #             wbt.raster_to_vector_polygons(i=self.geol_data_source, output = geol_data)
    #             self.geol_data = gpd.read_file(geol_data)
    #             logger.info(f"Raster file load and converted to shapefile: {self.geol_data_source}")
                
    #         else:
    #             raise ValueError(f"Unsupported file format: {file_extension}. "
    #                            f"Supported formats are .shp, .csv, and .tif or .tiff")
                
    #     except Exception as e:
    #         logger.error(f"Error reading geological data from {self.geol_data_source}: {str(e)}")
    #         raise
        
    #     return self
    
    # def geology_array(self):
    #     """
    #     Create a 2D array of geological structure from the generated DEM.
    #     -------
    #     self
    #         Stores the geological structure array in self.geology_array attribute.
    #     """

    #     with rasterio.open(self.structure_clip) as structure_clip:
    #         self.geol_array_clip = structure_clip.read(1).astype(str)
    #     self.geol_code_clip = np.unique(self.geol_array_clip)
    #     self.geol_code = self.geol_code_clip[self.geol_code_clip>=0]
    #     return self

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