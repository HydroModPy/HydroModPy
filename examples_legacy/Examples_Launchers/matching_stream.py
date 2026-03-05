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
import sys
import os
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
from hydromodpy.tools import toolbox
from hydromodpy.simulation.workspace import Workspace
from hydromodpy.geographic import Geographic
from hydromodpy.watershed import Hydrography

class MatchingStreams:
        """

        Class for the calibration based on river occurency

        Attributes
        ----------

        Methods
        ----------

        """

        def __init__(self,
                    geographic: Geographic,
                    hydrography: Hydrography,
                    initializing: Workspace,
                    iteration_label=None,
                    from_calib=True):

            self.geographic = geographic
            self.hydrography = hydrography
            if from_calib==True:
                self.calibration_folder = initializing.calibration_folder
            else:
                self.calibration_folder = initializing.simulations_folder
            self.iteration_label = iteration_label

            self.watershed_shp = geographic.watershed_shp
            self.watershed_fill = geographic.watershed_fill
            self.watershed_direc = geographic.watershed_direc

            self.prepare_files()
            self.sim_to_obs()
            self.obs_to_sim()
            # self.get_indicator()

        def prepare_files(self):
            #files are necessary for whiteboxtool
            self.results_folder=os.path.join(self.calibration_folder, self.iteration_label, '_postprocess')
            toolbox.create_folder(self.results_folder)
            # New folder results
            self.dichotomy_folder = os.path.join(self.calibration_folder, self.iteration_label, '_matchingstreams')
            toolbox.create_folder(self.dichotomy_folder)

            # Observed buff data
            self.buff_tif_obs = self.hydrography.tif_streams
            # Mask observed
            self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
            toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)
            # Obs to points
            self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
            wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
            self.pt_obsf = os.path.join(self.dichotomy_folder, 'obs_ptf.shp')
            wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
            # Trace downslope obs
            self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
            wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)

            # Mask simulated
            tif_sim = os.path.join(self.results_folder,'_rasters','seepage_areas_t(0).tif')
            self.tif_sim = os.path.join(self.dichotomy_folder,'sim.tif')
            toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, False)
            # Sim to points
            self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
            wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)
            self.pt_simf = os.path.join(self.dichotomy_folder, 'sim_ptf.shp')
            wbt.raster_to_vector_points(self.tif_sim, self.pt_simf)
            # Trace downslope sim
            self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
            wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)

        def sim_to_obs(self):
            # Simflow to points
            self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
            wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
            self.pt_sim_flowf = os.path.join(self.dichotomy_folder, 'simflowf.shp')
            wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)

            # Distance of dem to obs
            self.dist_dem_obs = os.path.join(self.dichotomy_folder, 'dist_dem_obs.tif')
            wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)

            # Distance of dem to obsflow
            self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, 'dist_dem_obsflow.tif')
            wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_dem_obsflow)

            # Sim to Obs and Obsflow
            wbt.add_point_coordinates_to_table(self.pt_sim)
            wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
            wbt.add_point_coordinates_to_table(self.pt_simf)
            wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)
            # Simflow to Obs and Obsflow
            wbt.add_point_coordinates_to_table(self.pt_sim_flow)
            wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
            wbt.add_point_coordinates_to_table(self.pt_sim_flowf)
            wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)

        def obs_to_sim(self):
            # Simflow to points
            self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
            wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
            self.pt_obs_flowf = os.path.join(self.dichotomy_folder, 'obsflowf.shp')
            wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flowf)

            # Distance of dem to sim
            self.dist_dem_sim = os.path.join(self.dichotomy_folder, 'dist_dem_sim.tif')
            wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_sim, self.dist_dem_sim)
            # Distance of dem to simflow
            self.dist_dem_simflow = os.path.join(self.dichotomy_folder, 'dist_dem_simflow.tif')
            wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_dem_simflow)

            # Obs to Sim and Simflow
            wbt.add_point_coordinates_to_table(self.pt_obs)
            wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs)
            wbt.add_point_coordinates_to_table(self.pt_obsf)
            wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obsf)
            # Obsflow to Sim and Simflow
            wbt.add_point_coordinates_to_table(self.pt_obs_flow)
            wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs_flow)
            wbt.add_point_coordinates_to_table(self.pt_obs_flowf)
            wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obs_flowf)
