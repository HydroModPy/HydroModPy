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
from hydromodpy.tools import get_logger
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

logger = get_logger(__name__)

#%% CLASS

class Geology:
    """
    Add geology data in the watershed object.
    """
        
    def __init__(self, out_path: str, geographic: object, geo_path: str, landsea=None,
                 types_obs='GEO1M.shp', fields_obs='CODE_LEG'):
        """
        Class to clip and extract geology caracteristics from a specific lithology map at the France scale.
        Source of data: BRGM.
        
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs. 
        geographic : object
            Variable object of the model domain (watershed).
        geo_path : str
            Path of the folder with geology data.
        landsea : bool
            If different None. Activate funcitons linked to sea geospatial processing. The default is None.
        types_obs : str, optional
            Label of the geological map shapefile at the France scale. The default is 'GEO1M.shp'.
        fields_obs : TYPE, optional
            Column field label of the geological map shapefile. The default is 'CODE_LEG'.
        """
        logger.info("Extracting geology data from %s", geo_path)
        
        data_folder = os.path.join(out_path,'results_stable/geology/')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
                
        watershed_shp = os.path.join(data_folder,'watershed.shp')

        self.geol_file =  os.path.join(geo_path, types_obs)
        self.field = fields_obs
        self.structure_dem_path =  os.path.join(data_folder, 'GeoStructure.tif')
        self.structure_clip =  os.path.join(data_folder, 'GeoStructure_clip.tif')
        
        # Be careful, column T_M_num not exist in default self.geol_file
        self.landsea = landsea
        if self.landsea != None:
                d_sea_dem_path =  os.path.join(data_folder,'Land_Sea.tif')
                land_sea_clip = os.path.join(data_folder, 'Land_Sea_clip.tif')
                
        self.generate_structure_dem(data_folder, geographic)
        self.geology_array(data_folder)
        
        # Problem with this function (sizes of arrays)
        # self.geology_elevation(geographic)
    
    #%% FUNCTIONS
    
    def generate_structure_dem(self, data_folder, geographic):
        """
        Parameters
        ----------
        data_folder : path
            Results stable path.
        geographic : object
            Variable object of the model domain (watershed).

        Returns
        -------
        self
            Add some variable in Geology class self object.
        """
        wbt.vector_polygons_to_raster(self.geol_file, self.structure_dem_path , field=self.field, nodata=None, base=geographic.watershed_buff_dem)
        wbt.clip_raster_to_polygon(self.structure_dem_path, geographic.watershed_shp, self.structure_clip)
        if self.landsea != None:
                wbt.vector_polygons_to_raster(self.geol_file, data_folder + 'Land_Sea.tif', field="T_M_num", nodata=None, base=geographic.watershed_buff_dem)
                wbt.clip_raster_to_polygon(data_folder + 'Land_Sea.tif', geographic.watershed_shp, data_folder + 'Land_Sea_clip.tif')
        
        return self

    def geology_array(self, data_folder):
        """
        Parameters
        ----------
        data_folder : path
            Results stable path for geology.

        Returns
        -------
        self
            Add some variable in Geology class self object.
        """
        with rasterio.open(self.structure_dem_path) as src:
            dem_data = src.read(1)
        if self.landsea != None:
                with rasterio.open(data_folder + 'Land_Sea.tif') as dem_T_M:
                        dem_data_T_M = dem_T_M.read(1)
                dem_data = dem_data.astype(float, copy=False)
                dem_data[dem_data_T_M==0] = 1 # Condidering that the part imerged by the sea is a superficial formation
        self.geology_array = dem_data.astype(int)
        self.geology_code = np.intersect1d(self.geology_array, self.geology_array)

        with rasterio.open(self.structure_dem_path) as src_clip:
            dem_data_clip = src_clip.read(1).astype(float)
        if self.landsea != None:
                with rasterio.open(data_folder + 'Land_Sea_clip.tif') as dem_T_M_clip:
                        dem_data_T_M_clip = dem_T_M_clip.read(1)
                dem_data_clip[dem_data_T_M_clip==0] = 1 # Condidering that the part imerged by the sea is a superficial formation
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

    def geology_elevation(self, geographic):
        """
        Parameters
        ----------
        geographic : object
            Variable object of the model domain (watershed).

        Returns
        -------
        self
            Add some variable in Geology class self object.
        """
        self.geology_elevation = np.ones(len(self.geology_code))
        for i in range(0,len(self.geology_code)):
            self.geology_elevation[i]= np.min(geographic.dem_data[self.geology_array==self.geology_code[i]])

        #idxs = self.geology_elevation.argsort()
        #self.geology_elevation = self.geology_elevation[idxs[:]]
        #self.geology_code = self.geology_code[idxs[:]]
        
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
