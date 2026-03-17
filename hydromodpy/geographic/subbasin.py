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
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import glob
import shutil
from hydromodpy.backends import get_whitebox_backend

# Root
from os.path import dirname, abspath
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy
from hydromodpy.support.tools import toolbox, get_logger
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

logger = get_logger(__name__)

#%% CLASS

class Subbasin:
    """
    Class to extract results in some subbasins inside the model domain (watershed).
    """

    def __init__(self,
                 geographic: object,
                 hydrometry: object,
                 intermittency: object,
                 sub_snap_dist: int,
                 add_path: str = None,
                 out_path: str=os.path.dirname(os.path.dirname(__file__))+'\\output\\'):
        """
        Parameters
        ----------
        geographic : object
            Variable object of the model domain (watershed).
        hydrometry : object, optional
            Variable object of the model domain (watershed).
        intermittency : object, optional
            Variable object of the model domain (watershed).
        add_path : str, optional
            Path folder with manual data list. Default is None.
        sub_snap_dist : int
            Maximum distance where the subbasin outlet can be moved.
        out_path : str
            Path of the HydroModPy outputs.
        """
        logger.info('Extracting subbasin definitions for watershed')
        self._backend = get_whitebox_backend()

        self.sub_snap_dist = sub_snap_dist

        self.subbasin_path = os.path.join(out_path, 'results_stable/subbasin/')
        if not os.path.exists(self.subbasin_path):
            toolbox.create_folder(self.subbasin_path)

        self.adddata_path = os.path.join(out_path, 'results_stable/add_data/')
        if not os.path.exists(self.adddata_path):
            toolbox.create_folder(self.adddata_path)

        try:
            code_bh = hydrometry.code_bh
            x_coord = hydrometry.x_coord
            y_coord = hydrometry.y_coord
            for i in range(len(x_coord)):
                station_name = f'hydrometry_{code_bh[i]}' if code_bh[i] else f'hydrometry_default_{i + 1}'
                if not code_bh[i]:
                    logger.warning('Hydrometry code missing at index %d; using generated name', i)
                sub_path = os.path.join(self.subbasin_path, station_name)
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path, sub_snap_dist)
        except Exception as e:
            logger.debug('No hydrometry subbasin or problem: %s', e)
            pass

        try:
            if hasattr(intermittency, 'points'):
                # New LoadResult-based intermittency
                for rec in intermittency.points:
                    if rec.location is None:
                        continue
                    onde_name = f'intermittency_{rec.station_id}'
                    sub_path = os.path.join(self.subbasin_path, onde_name)
                    self.extract_interest_zones(geographic, rec.location.x, rec.location.y, sub_path, sub_snap_dist)
        except Exception as e:
            logger.debug('No intermittency subbasin or problem: %s', e)
            pass

        try:
            code_sub, x_coord, y_coord = self.add_coord_manual(add_path)
            for i in range(len(code_sub)):
                sub_path = os.path.join(self.subbasin_path, 'subbasin_'+code_sub[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path, sub_snap_dist)
        except Exception as e:
            logger.debug('No personal subbasins or problem: %s', e)
            pass

    #%% SUB-CATCHMENT FROM STATIONS

    # Extract sub-catchment from existing stations : hydrometry or intermittency

    def extract_interest_zones(self, geographic, X, Y, outpath, sub_snap_dist):
        """
        Generate subassin from XY outlet with geospatial tools.

        Parameters
        ----------
        X : float
            X coordinate of the outlet.
        Y : float
            Y coordinate of the outlet..
        """
        # Path of subbasin
        if os.path.exists(outpath):
            shutil.rmtree(outpath)
        toolbox.create_folder(outpath)
        # Coordinates
        outpath = outpath + '/'
        df = pd.DataFrame({'x': [X], 'y': [Y]})
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=geographic.crs_proj)
        outlet_shp = outpath + 'outlet.shp'
        gdf.to_file(outlet_shp)
        # Snap the outlet shapefile from the flow accumulation
        outlet_snap_shp = outpath + 'outlet_snap.shp'
        self._backend.snap_pour_points(outlet_shp,
                             os.path.join(geographic.correcflow_path, 'dem_acc.tif'),
                             outlet_snap_shp,
                             sub_snap_dist
                             # geographic.snap_dist
                             )
        logger.debug('Using regional accumulation from: %s',
                    os.path.join(geographic.correcflow_path, 'dem_acc.tif'))
        # Generate raster watershed
        watershed = outpath + 'watershed.tif'
        self._backend.watershed(
            os.path.join(geographic.correcflow_path, 'dem_direc.tif'),
            outlet_snap_shp,
            watershed,
            esri_pntr=False,
        )

        # Create shapefile polygon of the watershed
        watershed_shp = outpath + 'watershed.shp'
        logger.debug('Creating watershed shapefile: %s', watershed_shp)
        self._backend.raster_to_vector_polygons(watershed, watershed_shp)
        shp = gpd.read_file(watershed_shp)
        shp.set_crs(geographic.crs_proj, inplace=True, allow_override=True)
        shp.to_file(watershed_shp)
        self._backend.polygon_area(watershed_shp)
        area = gpd.read_file(watershed_shp).AREA[0]/1000000
        area = np.abs(area)
        # Create shapefile polyline of the watershed
        watershed_contour_shp = outpath + 'watershed_contour.shp'
        self._backend.polygons_to_lines(watershed_shp, watershed_contour_shp)
        # Clip buffer watershed DEM from watershed shapefile polygon
        watershed_dem = outpath + 'watershed_dem.tif'
        self._backend.clip_raster_to_polygon(
            geographic.watershed_buff_dem,
            watershed_shp,
            watershed_dem,
            maintain_dimensions=True,
        )

    #%% SUB-CATCHMENT FROM XY POINT

    # From a .csv file with x, y coordinates representing the outlet desired sub-catchments

    def add_coord_manual(self, add_path):
        """
        Check files in folder and extract 'code_sub','x_outlet','y_outlet'
        """
        path_coord = glob.glob(str(Path(add_path) / '*'))[0]
        logger.debug('Loading coordinates from: %s', path_coord)
        sub_list = pd.read_csv(path_coord, sep=';')
        code_sub = sub_list['code_sub'].to_list()
        x_coord = sub_list['x_outlet'].to_list()
        y_coord = sub_list['y_outlet'].to_list()
        return code_sub, x_coord, y_coord

#%% NOTES
