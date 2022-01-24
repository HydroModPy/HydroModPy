# -*- coding: utf-8 -*-
"""
Created on Mon Oct 25 17:51:53 2021

@author: ronan
"""

import os
import whitebox
import imageio
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

from tools import toolbox

class RoutingAccflux:
    def __init__(self, geographic,
                 raw_rast_name, trace_shp_name, mass_rast_name,
                 extraction_folder=None):

        self.geographic = geographic
        self.extraction_folder = extraction_folder
        
        self.watershed_direc = geographic.watershed_direc
        
        self.watershed_buff_fill = geographic.watershed_buff_fill
        
        self.shp_folder = os.path.join(self.extraction_folder, '_surfaceflow')
        toolbox.create_folder(self.shp_folder)
        
        self.tifs_folder = os.path.join(self.extraction_folder, '_tifs')
        toolbox.create_folder(self.tifs_folder)
        
        self.raw_rast_path = os.path.join(self.tifs_folder, raw_rast_name)
        self.raw_pt_path = os.path.join(self.shp_folder, '_rawpt_t(xxx).shp')
        self.out_rast_path = os.path.join(self.shp_folder, '_trace_t(xxx).tif')
        self.out_pt_path = os.path.join(self.shp_folder, trace_shp_name)
        
        self.load_rast_path = os.path.join(self.shp_folder, '_load_t(xxx).tif')
        self.eff_rast_path = os.path.join(self.shp_folder, '_eff_t(xxx).tif')
        self.abs_rast_path = os.path.join(self.shp_folder, '_abs_t(xxx).tif')
        self.mass_rast_path = os.path.join(self.tifs_folder, mass_rast_name)
        
        self.trace_downslope()
        self.trace_cumulated()

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

    def trace_cumulated(self):
        ### Loading ###
        im = imageio.imread(self.raw_rast_path)
        im[im<0] = 0
        toolbox.export_tif(self.watershed_buff_fill, im, -99999, self.load_rast_path)
        ### Efficiency ###
        im = imageio.imread(self.watershed_buff_fill)
        im[im>=0] = 1
        toolbox.export_tif(self.watershed_buff_fill, im, -99999, self.eff_rast_path)        
        ### Adsorption ###
        im = imageio.imread(self.watershed_buff_fill)
        im[im>=0] = 0
        toolbox.export_tif(self.watershed_buff_fill, im, -99999, self.abs_rast_path)
        ### d8massflux ###
        wbt.d8_mass_flux(self.watershed_buff_fill, self.load_rast_path, self.eff_rast_path, self.abs_rast_path, self.mass_rast_path)
        
