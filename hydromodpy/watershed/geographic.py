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
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from pyproj import Transformer
from geopy.geocoders import Nominatim
import geopy.geocoders
import ssl
import certifi
import shutil
import rasterio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
# wbt.verbose = True

# Root
from os.path import dirname, abspath
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy
from hydromodpy.tools import toolbox, get_logger
from hydromodpy.watershed import initializing
from hydromodpy.watershed.geographic_config import GeographicConfig
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

logger = get_logger(__name__)

#%% FUNCTIONS

def DEM_correcflow_analysis(dem_init_path: str,
                            dem_out_dir_path: str,
                            dem_correc_type: str
                            ) -> dict:
    """
    Generate regional flow rasters from an input DEM.

    Parameters
    ----------
    dem_path : str
        Path to the regional DEM used as hydrologic input.
    reg_path : str
        Folder where regional rasters are written.
    wbt_tools :
        WhiteboxTools instance used to run terrain and flow operations.

    Returns
    -------
    dict
        Dictionary with output paths:
        ``{"fill": ..., "direc": ..., "acc": ...}``.
    """

    if dem_correc_type == 'fill':
        # Depression-corrected DEM.
        correc = os.path.join(dem_out_dir_path, "dem_fill.tif")
        wbt.fill_depressions(dem_init_path, correc)
    if dem_correc_type == 'breach':
        # Depression-corrected DEM.
        correc = os.path.join(dem_out_dir_path, "dem_breach.tif")
        wbt.breach_depressions(dem_init_path, correc)

    # D8 flow-direction raster.
    direc = os.path.join(dem_out_dir_path, "dem_direc.tif")
    wbt.d8_pointer(correc, direc, esri_pntr=False)

    # D8 flow-accumulation raster (log-scaled for visualization and stability).
    acc = os.path.join(dem_out_dir_path, "dem_acc.tif")
    wbt.d8_flow_accumulation(correc, acc, log=True)

    # # Downslope flowpath length raster.
    # down = os.path.join(dem_out_dir_path, "dem_down.tif")
    # wbt.downslope_flowpath_length(direc, down, watersheds=None, weights=None)

    return {
        "correc": correc,
        "direc": direc,
        "acc": acc,
        # "down": down,
        }

# def DEM_hydrological_analysis():

def _ensure_crs(path, crs):
    if crs is None: return
    if path.lower().endswith(".tif"):
        with rasterio.open(path, "r+") as dst:
            dst.crs = crs
    elif path.lower().endswith(".shp"):
        gdf = gpd.read_file(path)
        gdf = gdf.set_crs(crs, allow_override=True)
        gdf.to_file(path)

#%% CLASS

class Geographic:
    """
    Class to initialize the model domain object (watershed).
    """

    def __init__(self,
                 config: GeographicConfig,
                 initializing_object,
                 ):
        """
        Parameters
        ----------
        config : GeographicConfig
            Pydantic config with all geographic parameters.
        initializing_object : Initializing
            Initializing instance providing folder paths.
        """
        logger.info('Extracting geographic data for model area')

        self.stable_folder   = initializing_object.stable_folder
        self.out_dir_path    = initializing_object.catch_folder
        self.catch_def       = config.catch_def
        self.dem_init_path   = config.dem_init_path
        self.x_outlet        = config.x_outlet
        self.y_outlet        = config.y_outlet
        self.snap_dist       = config.snap_dist
        self.buff_area       = config.buff_area
        self.polyg_shp_path  = config.polyg_shp_path
        self.dem_correc_type = config.dem_correc_type
        self._crs_project    = config.crs_project

        self.processing()

        self.info_dem()

    #%% GENERATE FILES

    def processing(self):
        """
        Prepare, initialize and generate files of the model domain from geospatial functions.
        """

        """
        Initial paths
        """
        """
        self.watershed_folder = os.path.join(out_path, watershed_name)
        toolbox.create_folder(self.watershed_folder)

        # Setup simulation log in watershed folder
        from hydromodpy.tools import setup_simulation_log
        setup_simulation_log(self.watershed_folder)

        self.stable_folder = os.path.join(self.watershed_folder, 'results_stable')
        toolbox.create_folder(self.stable_folder)
        """

        # Recall important folders
        self.stable_folder = os.path.join(self.out_dir_path, 'results_stable')
        self.simulations_folder = os.path.join(self.out_dir_path, 'results_simulations')

        # Generate folder where processing files are stored
        self.geographic_path = os.path.join(self.out_dir_path, 'results_stable', 'geographic')
        toolbox.create_folder(self.geographic_path)

        # Generate regional folder
        self.correcflow_path = os.path.join(self.out_dir_path, 'results_stable', 'demcorrecflow')
        toolbox.create_folder(self.correcflow_path)

        """
        Raw init DEM
        """

        self.epsg = rasterio.open(self.dem_init_path).crs.to_epsg()
        if self.epsg != None:
            self.crs_proj = 'EPSG:'+str(self.epsg)
        else:
            self.crs_proj = None

        if hasattr(self, '_crs_project') and self._crs_project is not None:
            self.crs_proj = self._crs_project

        # if isinstance(self.demflow_dir_path, (str))==False:
        DEM_correcflow_analysis_files = DEM_correcflow_analysis(
                                        dem_init_path=self.dem_init_path,
                                        dem_out_dir_path=self.correcflow_path,
                                        dem_correc_type=self.dem_correc_type
                                        )
        correc = DEM_correcflow_analysis_files["correc"]
        direc = DEM_correcflow_analysis_files["direc"]
        acc = DEM_correcflow_analysis_files["acc"]
        # down = DEM_correcflow_analysis_files["down"]
        # else:
        #     correc = os.path.join(self.out_dir_path, 'results_stable', 'demcorrecflow', 'dem_'+self.correc_type+'.tif')
        #     direc = os.path.join(self.out_dir_path, 'results_stable', 'demcorrecflow', 'dem_direc.tif')
        #     acc = os.path.join(self.out_dir_path, 'results_stable', 'demcorrecflow', 'dem_acc.tif')
        #     down = os.path.join(self.out_dir_path, 'results_stable', 'demcorrecflow', 'dem_down.tif')
        _ensure_crs(correc, self.crs_proj)
        _ensure_crs(direc, self.crs_proj)
        _ensure_crs(acc, self.crs_proj)

        """
        Extract watershed from an outlet
        """
        if self.catch_def == "from_outlet_coord":
            # Create outlet shapefile from x and y coordinates
            df = pd.DataFrame({'x': [self.x_outlet], 'y': [self.y_outlet]})
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=self.crs_proj)
            outlet_shp = os.path.join(self.geographic_path, 'outlet.shp')
            gdf.to_file(outlet_shp)
            _ensure_crs(outlet_shp, self.crs_proj)
            # Snap the outlet shapefile from the flow accumulation
            outlet_snap_shp = os.path.join(self.geographic_path, 'outlet_snap.shp')
            wbt.snap_pour_points(outlet_shp, acc, outlet_snap_shp, self.snap_dist)
            _ensure_crs(outlet_snap_shp, self.crs_proj)
            # Generate raster watershed
            self.watershed = os.path.join(self.geographic_path, 'watershed.tif')
            wbt.watershed(direc, outlet_snap_shp, self.watershed, esri_pntr=False)
            _ensure_crs(self.watershed, self.crs_proj)
            # Create shapefile polygon of the watershed
            self.watershed_shp = os.path.join(self.geographic_path, 'watershed.shp')
            wbt.raster_to_vector_polygons(self.watershed, self.watershed_shp)
            _ensure_crs(self.watershed_shp, self.crs_proj)

        if self.catch_def == "from_polyg_shp":
            self.watershed_shp = os.path.join(self.geographic_path, 'watershed.shp')
            polyg_shp_file = gpd.read_file(self.polyg_shp_path)
            # Remove duplicate columns if any exist
            polyg_shp_file = polyg_shp_file.loc[:, ~polyg_shp_file.columns.duplicated()]
            polyg_shp_file.to_file(self.watershed_shp)
            _ensure_crs(self.watershed_shp, self.crs_proj)


        """
        Shapefile operations
        """
        # Create shapefile polyline of the watershed
        self.watershed_contour_shp = os.path.join(self.geographic_path, 'watershed_contour.shp')
        wbt.polygons_to_lines(self.watershed_shp, self.watershed_contour_shp)

        try:
            area = gpd.read_file(self.watershed_shp).AREA[0]/1000000
            self.catch_area = np.abs(area)
        except:
            area = gpd.read_file(self.watershed_shp).area[0]/1000000
            self.catch_area = np.abs(area)
            pass

        """
        Buffer distance operations
        """
        # Normalize initial buffer distance value
        with rasterio.open(self.dem_init_path) as dem_src:
            self.dem_res = abs(dem_src.transform.a)
        if isinstance(self.buff_area,(str))!=True:
            buff_raw = (np.sqrt(float(self.catch_area))) * (float(self.buff_area)/100) * 1000
            buff_raw = int(round(buff_raw))
            dist = np.linspace(0,buff_raw,buff_raw+1)*self.dem_res
            buff_dist = dist[np.abs(dist-buff_raw).argmin()]
        else:
            buff_dist = float(self.buff_area)
        site_polyg = gpd.read_file(self.watershed_shp)
        # Remove duplicate columns if any exist
        site_polyg = site_polyg.loc[:, ~site_polyg.columns.duplicated()]
        site_polyg.to_file(self.watershed_shp)
        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist)
        buffer = os.path.join(self.geographic_path, 'watershed_buff.shp')
        site_polyg.to_file(buffer)
        _ensure_crs(buffer, self.crs_proj)

        """
        Box extent operations
        """
        # Create box extent of the watershed
        self.watershed_box_shp = os.path.join(self.geographic_path, 'watershed_box.shp')
        wbt.minimum_bounding_envelope(self.watershed_shp, self.watershed_box_shp, features=False)
        # Buffer the box extent watershed shapefile polygon
        site_bound = gpd.read_file(self.watershed_box_shp)
        # Remove duplicate columns if any exist
        site_bound = site_bound.loc[:, ~site_bound.columns.duplicated()]
        site_bound.to_file(self.watershed_box_shp)
        _ensure_crs(self.watershed_box_shp, self.crs_proj)
        site_bound['geometry'] = site_bound.geometry.buffer(buff_dist)
        self.box_buff = os.path.join(self.geographic_path, 'watershed_box_buff.shp')
        site_bound.to_file(self.box_buff)
        wbt.minimum_bounding_envelope(self.box_buff, self.box_buff, features=False)
        site_bound = gpd.read_file(self.box_buff)
        # Remove duplicate columns if any exist
        site_bound = site_bound.loc[:, ~site_bound.columns.duplicated()]
        site_bound.to_file(self.box_buff)
        _ensure_crs(self.box_buff, self.crs_proj)

        """
        Clip to reach box extent size
        """
        # Clip raw regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_dem = os.path.join(self.geographic_path, 'watershed_box_buff_dem.tif')
        wbt.clip_raster_to_polygon(self.dem_init_path, self.box_buff, self.watershed_box_buff_dem,
                                   maintain_dimensions=False)
        _ensure_crs(self.watershed_box_buff_dem, self.crs_proj)
        # Correct no data
        wbt.modify_no_data_value(self.watershed_box_buff_dem, new_value=-9999.0)
        # Clip corrected regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_fill = os.path.join(self.geographic_path, 'watershed_box_buff_fill.tif')
        wbt.clip_raster_to_polygon(correc, self.box_buff, self.watershed_box_buff_fill,
                                   maintain_dimensions=False)
        _ensure_crs(self.watershed_box_buff_fill, self.crs_proj)
        # Clip flow direction regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_direc = os.path.join(self.geographic_path, 'watershed_box_buff_direc.tif')
        wbt.clip_raster_to_polygon(direc, self.box_buff, self.watershed_box_buff_direc,
                                   maintain_dimensions=False)
        _ensure_crs(self.watershed_box_buff_direc, self.crs_proj)

        """
        Clip to reach buffer size
        """
        # Clip raw regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_dem = os.path.join(self.geographic_path, 'watershed_buff_dem.tif')
        wbt.clip_raster_to_polygon(self.watershed_box_buff_dem, buffer, self.watershed_buff_dem,
                                   maintain_dimensions=True)
        _ensure_crs(self.watershed_buff_dem, self.crs_proj)
        # Correct no data
        wbt.modify_no_data_value(self.watershed_buff_dem, new_value=-9999)
        # Clip corrected regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_fill = os.path.join(self.geographic_path, 'watershed_buff_fill.tif')
        wbt.clip_raster_to_polygon(correc, buffer, self.watershed_buff_fill,
                                   maintain_dimensions=False)
        _ensure_crs(self.watershed_buff_fill, self.crs_proj)
        # Clip flow direction regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_direc = os.path.join(self.geographic_path, 'watershed_buff_direc.tif')
        wbt.clip_raster_to_polygon(direc, buffer, self.watershed_buff_direc,
                                   maintain_dimensions=False)
        _ensure_crs(self.watershed_buff_direc, self.crs_proj)

        """
        Clip to reach watershed size
        """
        # Clip buffer watershed DEM from watershed shapefile polygon
        self.watershed_dem = os.path.join(self.geographic_path, 'watershed_dem.tif')
        wbt.clip_raster_to_polygon(self.watershed_box_buff_dem, self.watershed_shp, self.watershed_dem,
                                   maintain_dimensions=True)
        _ensure_crs(self.watershed_dem,
                    self.crs_proj)
        # Clip corrected regional DEM from watershed shapefile polygon
        self.watershed_fill = os.path.join(self.geographic_path, 'watershed_fill.tif')
        wbt.clip_raster_to_polygon(correc, self.watershed_shp, self.watershed_fill,
                                   maintain_dimensions=False)
        _ensure_crs(self.watershed_fill, self.crs_proj)
        # Clip flow direction regional DEM from watershed shapefile polygon
        self.watershed_direc = os.path.join(self.geographic_path, 'watershed_direc.tif')
        wbt.clip_raster_to_polygon(direc, self.watershed_shp, self.watershed_direc,
                                   maintain_dimensions=False)
        _ensure_crs(self.watershed_direc, self.crs_proj)

        """
        Create catchment surface contour in raster
        """
        self.watershed_contour_tif = os.path.join(self.geographic_path, 'watershed_contour.tif')
        # Parameter name changed: base → base_raster
        wbt.vector_lines_to_raster(self.watershed_shp,
                                   self.watershed_contour_tif,
                                   base = self.watershed_dem)
        _ensure_crs(self.watershed_contour_tif, self.crs_proj)

        """
        Check grid shapes
        """
        with rasterio.open(self.watershed_box_buff_dem) as src1, \
            rasterio.open(self.watershed_buff_dem) as src2, \
            rasterio.open(self.watershed_dem) as src3:

            print('YES', src1.read(1).shape,src2.read(1).shape,src3.read(1).shape)


            if src1.read(1).shape != src2.read(1).shape != src3.read(1).shape:
                logger.debug('Reshaping rasters to match box buff watershed dimensions')
                print('NO', src1.read(1).shape,src2.read(1).shape,src3.read(1).shape)

                with rasterio.open(self.watershed_box_buff_dem) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_dem, -9999)
                with rasterio.open(self.watershed_box_buff_fill) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_fill, -9999)
                with rasterio.open(self.watershed_box_buff_direc) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_direc, -32768)

                with rasterio.open(self.watershed_box_buff_dem) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_buff_dem, -9999)
                with rasterio.open(self.watershed_box_buff_fill) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_buff_fill, -9999)
                with rasterio.open(self.watershed_box_buff_direc) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_buff_direc, -32768)

                with rasterio.open(self.watershed_box_buff_dem) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_box_buff_dem, -9999)
                with rasterio.open(self.watershed_box_buff_fill) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_box_buff_fill, -9999)
                with rasterio.open(self.watershed_box_buff_direc) as src:
                    toolbox.export_tif(self.watershed_box_buff_dem, src.read(1), self.watershed_box_buff_direc, -32768)

    #%% DEM FEATURES

    def info_dem(self):
        """
        Add and/or modify the projection of generated files.
        """

        # Open DEM used for modeling
        with rasterio.open(self.watershed_box_buff_dem) as box_buff_dem_src:
            self.dem_box_buff_data = box_buff_dem_src.read(1)
        with rasterio.open(self.watershed_buff_dem) as buff_dem_src:
            self.dem_buff_data = buff_dem_src.read(1)
        with rasterio.open(self.watershed_dem) as dem_src:
            self.dem_data = dem_src.read(1)
            self.nodata = dem_src.nodata

        self.geodata = dem_src.transform.to_gdal()

        # # Extract size characteristics
        self.x_pixel = self.dem_box_buff_data.shape[1] # columns
        self.y_pixel = self.dem_box_buff_data.shape[0] # rows

        # # Extract resolution
        self.resolution_x = self.geodata[1] # pixelWidth: positive
        self.resolution_y = self.geodata[5] # pixelHeight: negative
        self.resolution = self.resolution_x

        # Extract bounds size
        self.xmin = self.geodata[0] # originX
        self.ymax = self.geodata[3] # originY
        self.xmax = self.xmin + self.x_pixel * self.resolution_x
        self.ymin = self.ymax + self.y_pixel * self.resolution_y

        # Generate coordinates
        self.x_coord = np.linspace(1,self.x_pixel, self.x_pixel)*(self.resolution_x) + self.xmin
        self.y_coord = self.ymax - np.linspace(1,self.y_pixel, self.y_pixel)*(self.resolution_x)

        # Calculate centroids
        self.centroid = [self.xmin+((self.xmax-self.xmin)/2),self.ymin+((self.ymax-self.ymin)/2)]

        # # Transform centroids to World Geodetic System 1984
        # try:
        #     transformer = Transformer.from_crs(self.crs_proj, "epsg:4326")
        #     self.centroid_long_lat = transformer.transform(self.centroid[0], self.centroid[1])
        #     self.ur_long_lat = transformer.transform(self.xmax,self.ymax)
        #     self.ul_long_lat = transformer.transform(self.xmin,self.ymax)
        #     self.lr_long_lat = transformer.transform(self.xmax,self.ymin)
        #     self.ll_long_lat = transformer.transform(self.xmin,self.ymin)
        #     # Transform to longitude/latitude London Greenwich
        #     self.centroid_long_lat_Greenwich = [self.centroid_long_lat[0], self.centroid_long_lat[1]]
        #     if self.centroid_long_lat_Greenwich[1]<0:
        #         self.centroid_long_lat_Greenwich[1] = self.centroid_long_lat_Greenwich[1] + 360
        # except:
        #     pass
        # try:
        #     locator = Nominatim(user_agent='google')
        #     location = locator.reverse(str(self.centroid_long_lat_Greenwich[0]) +','+str(self.centroid_long_lat_Greenwich[1]), timeout=120)
        #     try:
        #         self.dep_code = int(location.address.split(',')[-2][0:3])
        #     except:
        #         pass
        # except OSError:
        #     # In some cases, a SSL certificate error can occur. The next two
        #     # lines modify the ssl_context
        #     ctx = ssl.create_default_context(cafile=certifi.where())
        #     geopy.geocoders.options.default_ssl_context = ctx
        #     locator = Nominatim(user_agent='google')
        #     location = locator.reverse(str(self.centroid_long_lat_Greenwich[0]) +','+str(self.centroid_long_lat_Greenwich[1]), timeout=120)
        #     self.dep_code = int(location.address.split(',')[-2][0:3])
        # else:
        # # except:
        #     pass

#%% NOTES
