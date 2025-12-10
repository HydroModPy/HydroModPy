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
import whitebox
import rasterio
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# HydroModPy
from hydromodpy.tools import toolbox, get_logger

logger = get_logger(__name__)

#%% CLASS

class Masstransfer:
    """
    Class for topographically-driven surface runoff of discharge outflows
    from groundwater flow model 
    """
    
    def __init__(self, 
                 geographic: object,
                 raw_rast_name: str, 
                 trace_shp_name: str, 
                 mass_rast_name: str,
                 extraction_folder: str=None,
                 label: str="conc"):
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
        label : str, optional
            Optional tag injected into intermediate filenames to distinguish
            runs (default keeps historical '_conc' suffixes).
        """
        self.geographic = geographic
        self.extraction_folder = extraction_folder
        label_suffix = f"_{label}" if label else ""
               
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
        
        self.raw_pt_path = os.path.join(self.shp_folder, f'_rawpt{label_suffix}_t(xxx).shp')
        self.out_rast_path = os.path.join(self.shp_folder, f'_trace{label_suffix}_t(xxx).tif')
        self.out_pt_path = os.path.join(self.shp_folder, trace_shp_name)
        
        self.load_rast_path = os.path.join(self.shp_folder, f'_load{label_suffix}_t(xxx).tif')
        self.eff_rast_path = os.path.join(self.shp_folder, f'_eff{label_suffix}_t(xxx).tif')
        self.abs_rast_path = os.path.join(self.shp_folder, f'_abs{label_suffix}_t(xxx).tif')
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
        with rasterio.open(self.raw_rast_path) as src:
            im = src.read(1)
        im[im<0] = 0
        toolbox.export_tif(self.watershed_buff_fill_surflow, im, self.load_rast_path, -99999)
        ### Efficiency ###
        with rasterio.open(self.watershed_buff_fill_surflow) as src:
            im = src.read(1)
        im[im>=0] = 1
        toolbox.export_tif(self.watershed_buff_fill_surflow, im, self.eff_rast_path, -99999)
        ### Adsorption ###
        with rasterio.open(self.watershed_buff_fill_surflow) as src:
            im = src.read(1)
        im[im>=0] = 0
        toolbox.export_tif(self.watershed_buff_fill_surflow, im, self.abs_rast_path, -99999)
        ### d8massflux ###
        wbt.d8_mass_flux(self.watershed_buff_fill_surflow,
                         self.load_rast_path, self.eff_rast_path,
                         self.abs_rast_path, self.mass_rast_path)

    #%% TRACE DOWNSLOPE FLOWPATHS

    def trace_downslope(self):
        """
        Generate continuous hydrographic network with downslope flowpaths.
        """
        # Sim to points
        wbt.raster_to_vector_points(self.raw_rast_path, self.raw_pt_path)
        logger.info("raster_to_vector_points: created %s from %s", self.raw_pt_path, self.raw_rast_path)

        # Trace downslope sim
        wbt.trace_downslope_flowpaths(self.raw_pt_path, self.watershed_direc_surflow, self.out_rast_path)
        logger.info("trace_downslope_flowpaths: traced flowpaths to %s", self.out_rast_path)

        # Simflow to points
        wbt.raster_to_vector_points(self.out_rast_path, self.out_pt_path)
        logger.info("raster_to_vector_points: created %s from %s", self.out_pt_path, self.out_rast_path)

        # Extra (disabled by default)
        # wbt.add_point_coordinates_to_table(self.out_pt_path)
        # wbt.extract_raster_values_at_points(self.raw_rast_path, self.out_pt_path)
        logger.debug("Optional extras (add_point_coordinates_to_table, extract_raster_values_at_points) are available but disabled.")
        
        
#%% NOTES
