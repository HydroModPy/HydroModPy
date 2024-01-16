# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
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
import whitebox
import imageio
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# HydroModPy
from tools import toolbox

#%% CLASS

class Downslope:
    """
    Class for topographically-driven surface runoff of discharge outflows
    from groundwater flow model 
    """
    
    def __init__(self, 
                 geographic,
                 raw_rast_name, 
                 trace_shp_name, 
                 mass_rast_name,
                 extraction_folder=None):
        """
        Parameters
        ----------
        geographic : object
            Variable object of the model domain (watershed).
        raw_rast_name : str
            Name of the inital raster dicharge outflow simulated, e.g. 'outflow_drain.tif.
        trace_shp_name : str
            Name of the shapefile points generated from raw_rast_name.
        mass_rast_name : TYPE
            Name of the generated flow accumulated raster.
        extraction_folder : str, optional
            Path of the model simulation results. The default is None.
        """
        self.geographic = geographic
        self.extraction_folder = extraction_folder
               
        self.watershed_direc_surflow = geographic.watershed_direc
        self.watershed_buff_fill_surflow = geographic.watershed_buff_fill
        
        try:
            self.watershed_direc_surflow = geographic.watershed_box_buff_direc # geographic.watershed_direc
            self.watershed_buff_fill_surflow = geographic.watershed_box_buff_fill # geographic.watershed_buff_fill
        except:
            pass
        
        #### CHANGE HARD DISK ####
        # self.watershed_direc_surflow = self.watershed_direc_surflow.replace('G','I',1)
        # self.watershed_buff_fill_surflow = self.watershed_buff_fill_surflow.replace('G','I',1)
        
        self.shp_folder = os.path.join(self.extraction_folder, '_temporary')
        toolbox.create_folder(self.shp_folder)
        
        self.tifs_folder = os.path.join(self.extraction_folder, '_rasters')
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
        """
        Mass flux of discharge outflows according to the DEM.
        Need to have DEM, flux, efficiency and adsorption rasters.
        """
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
        wbt.d8_mass_flux(self.watershed_buff_fill_surflow,
                         self.load_rast_path, self.eff_rast_path,
                         self.abs_rast_path, self.mass_rast_path)

    #%% TRACE DOWNSLOPE FLOWPATHS

    def trace_downslope(self):
        """
        Generate continuous hydrogrpahic network with downslope flowpaths.
        """
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
