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
from typing import Union, List # TT [user] --> Currently installed typing-3.7.4.3
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
                 result_data_path : str, #! path for data results
                 geographic : object, #! The name of this object should be changed
                 geological_data_source: str,
                 fields_names : str | List[str] ,
                 ):
        """
        Parameters
        ----------
        result_data_path : str
            Path of the folder for geology output in the HydroModPy results.
        geographic : object
            Variable object of the model domain (catchment).
        geological_data_source : str
            Path of the data source for geology. It can be a shapefile (source : BRGM or other) or a CSV file.
        fields_names : str or list 
            Fields labels of the geological data source. 
                For example, geological field it is 'CODE_LEG' for BRGM shapefile.
        """
        # logger.info("Extracting geology data from %s", geological_data_source)
        
        self.geol_output_folder = os.path.join(result_data_path,'geology')
        if not os.path.exists(self.geol_output_folder):
                os.makedirs(self.geol_output_folder)
                
        self.geographic = geographic
        self.geol_data_source = geological_data_source
        self.fields_names = fields_names
        
        self.generate_structure_dem()
        self.geology_array()
        
        self.structure_dem_path =  os.path.join(self.geol_output_folder, 'GeoStructure.tif')
        self.structure_clip =  os.path.join(self.geol_output_folder, 'GeoStructure_clip.tif')
    #%% FUNCTIONS
    
    def __generate_structure_dem(self):
        """
        Parameters
        ----------
        geol_output_folder : path
            Results stable path.
        geographic : object
            Variable object of the model domain (catchment).

        Returns
        -------
        self
            Add some variable in Geology class self object.
        """
        wbt.vector_polygons_to_raster(self.geol_data_source, self.structure_dem_path , field=self.fields_names, nodata=None, base=self.geographic.watershed_buff_dem)
        wbt.clip_raster_to_polygon(self.structure_dem_path, self.geographic.watershed_shp, self.structure_clip)
        return self

    def __geology_array(self):
        """
        Parameters
        ----------
        geol_output_folder : path
            Results stable path for geology.

        Returns
        -------
        self
            Add some variable in Geology class self object.
        """
        with rasterio.open(self.structure_dem_path) as src:
            dem_data = src.read(1)
        self.geology_array = dem_data.astype(int)
        self.geology_code = np.intersect1d(self.geology_array, self.geology_array)

        with rasterio.open(self.structure_dem_path) as src_clip:
            dem_data_clip = src_clip.read(1).astype(float)
        dem_data_clip[dem_data_clip<0]= np.nan
        self.geology_array_clip = dem_data_clip.astype(int)

        #self.geology_array[self.geology_array<=100] = int(1)
        #self.geology_array_clip[self.geology_array_clip<=100] = int(1)

        self.geology_code_clip = np.intersect1d(self.geology_array_clip, self.geology_array_clip)
        self.geology_code = self.geology_code_clip[self.geology_code_clip>=0]

        """
        # Double geology
        self.geology_code = [int(1),int(2)]
        for i in self.geology_code:
            if i ==1:
                self.geology_array[self.geology_array<=100] = int(i)
                self.geology_array_clip[self.geology_array_clip<=100] = int(i)
        """
        
        return self

    def geo_to_K(self, K_geo_values):
        """
        Parameters
        ----------
        K_geo_values : list
            List of K values according to geology code number.

        Returns
        -------
        self
            Add some variable in Geology class self object.
        """
        self.K_array = self.geology_array
        for i in range(0,len(self.geology_code)):
            self.K_array[self.geology_array==self.geology_code[i]] = K_geo_values[i]
        """
        geology_array: 2D arrays - code of geology entities
        K_geo_values: 1D array (same size that geology code variable)
            correspondence between geology codes and hydraulique conductivity values 
        """  
        
        return self

#%% NOTES
        