# -*- coding: utf-8 -*-
"""
Created on Mon Oct 25 17:51:53 2021

@author: ronan
"""

import geopandas as gpd
import numpy as np
import os
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

from tools import file_adds

class SurfaceFlow:
    def __init__(self, geographic,
                 raw_rast_name, raw_pt_name, out_rast_name, out_pt_name,
                 extraction_folder=None):

        self.geographic = geographic
        self.extraction_folder = extraction_folder

        self.watershed_shp = geographic.watershed_shp
        self.watershed_fill = geographic.watershed_fill
        self.watershed_direc = geographic.watershed_direc
        
        self.shp_folder = os.path.join(self.extraction_folder, '_surfaceflow')
        file_adds.create_folder(self.shp_folder)
        
        self.raw_rast_path = os.path.join(self.extraction_folder, raw_rast_name)
        self.raw_pt_path = os.path.join(self.shp_folder, raw_pt_name)
        self.out_rast_path = os.path.join(self.shp_folder, out_rast_name)
        self.out_pt_path = os.path.join(self.shp_folder, out_pt_name)

        self.trace_downslope()

    def trace_downslope(self):
        # Sim to points
        wbt.raster_to_vector_points(self.raw_rast_path, self.raw_pt_path)
        # Trace downslope sim
        wbt.trace_downslope_flowpaths(self.raw_pt_path, self.watershed_direc, self.out_rast_path)
        # Simflow to points
        wbt.raster_to_vector_points(self.out_rast_path, self.out_pt_path)
        # Extra
        wbt.add_point_coordinates_to_table(self.out_pt_path)
        wbt.extract_raster_values_at_points(self.raw_rast_path, self.out_pt_path)
