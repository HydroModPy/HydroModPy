# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

import os
import whitebox
import imageio
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

from tools import toolbox

#%% CLASS

class RoutingAccflux:
    
    #%% INIT

    def __init__(self, geographic,
                 raw_rast_name, trace_shp_name, mass_rast_name,
                 extraction_folder=None):

        self.geographic = geographic
        self.extraction_folder = extraction_folder
               
        self.watershed_direc_surflow = geographic.watershed_direc
        self.watershed_buff_fill_surflow = geographic.watershed_buff_fill
        
        try:
            self.watershed_direc_surflow = geographic.watershed_box_buff_direc # geographic.watershed_direc
            self.watershed_buff_fill_surflow = geographic.watershed_box_buff_fill # geographic.watershed_buff_fill
        except:
            pass

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
        
        # self.trace_downslope()
        # self.trace_cumulated()

    #%% MASS FLUX FROM OUTFLOW

    def trace_cumulated(self):
        ### Loading ###
        im = imageio.imread(self.raw_rast_path)
        im[im<0] = 0
        toolbox.export_tif(self.watershed_buff_fill_surflow, im, -99999, self.load_rast_path)
        ### Efficiency ###
        im = imageio.imread(self.watershed_buff_fill_surflow)
        im[im>=0] = 1
        toolbox.export_tif(self.watershed_buff_fill_surflow, im, -99999, self.eff_rast_path)        
        ### Adsorption ###
        im = imageio.imread(self.watershed_buff_fill_surflow)
        im[im>=0] = 0
        toolbox.export_tif(self.watershed_buff_fill_surflow, im, -99999, self.abs_rast_path)
        ### d8massflux ###
        wbt.d8_mass_flux(self.watershed_buff_fill_surflow, self.load_rast_path, self.eff_rast_path, self.abs_rast_path, self.mass_rast_path)

    #%% TRACE DOWNSLOPE FLOWPATHS

    def trace_downslope(self):
        # Sim to points
        wbt.raster_to_vector_points(self.raw_rast_path, self.raw_pt_path)
        # print('raster_to_vector_points')
        # # Trace downslope sim
        wbt.trace_downslope_flowpaths(self.raw_pt_path, self.watershed_direc_surflow, self.out_rast_path)
        # print('trace_downslope_flowpaths')
        # # # Simflow to points
        wbt.raster_to_vector_points(self.out_rast_path, self.out_pt_path)
        # print('raster_to_vector_points')
        # # Extra
        # wbt.add_point_coordinates_to_table(self.out_pt_path)
        # wbt.extract_raster_values_at_points(self.raw_rast_path, self.out_pt_path)
        # print('extract_raster_values_at_points')
        
#%% NOTES

