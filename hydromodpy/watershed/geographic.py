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
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

logger = get_logger(__name__)

#%% CLASS

class Geographic:
    """
    Class to initialize the model domain object (watershed).
    """

    def __init__(self,
                 dem_path: str=None,
                 bottom_path: str=None, # path
                 cell_size: int=None,
                 x_outlet: float=None,
                 y_outlet: float=None,
                 snap_dist: int=None,
                 buff_percent: int=None,
                 crs_proj: str=None,
                 out_path: str=None,
                 stable_folder: int=None,
                 simulations_folder: int=None,
                 calibration_folder: int=None,
                 from_lib: str=None,
                 from_dem: list=None,
                 from_shp: list=None,
                 from_xyv: list=None,
                 reg_fold: str=None):
        """
        Parameters
        ----------
        dem_path : str
            Path of the initial Digital Elevation Model.
        bottom_path : str, optional
            Path of a raster representing the bottom elevation. The default is None.
        cell_size:
            Resolution of the DEM. To change the initial resolution
        x_outlet:
            x coordinate of the watershed outlet.
        y_outlet:
            y coordinate of the watershed outlet.
        snap_dist:
            Maximum distance where the outlet can be moved.
        buffer_size:
            buffer distance in percentage of the model domain (value in percent).
        crs_proj : str
            Projection label of the workflow (ex: 'EPSG:2454').
        out_path : str
            Path of the HydroModPy outputs.
        stable_folder : str
            Path of the stable results about the model domain or watershed.
        simulations_folder : str
            Path of the simulation results from modeling operations.
        calibration_folder : str
            Path of the calibration results from modeling operations.
        from_lib : str, optional
            Path of the watershed librairies. If None : method not used. The default is None.
        from_dem : list, optional
            List with two parameters: [path, cell_size]
        from_shp : list, optional
            List of tow parameters: [path, buffer_size]
        from_xyv : list, optional
            List of four parameters: [x, y, snap_distance, buffer_size]
        reg_fold : str, None
            Path of the folder with regional data/results.
            If informed, the regional results will not be created, just loaded from folder.
            The default is None.
        """
        logger.info('Extracting geographic data for model area')

        self.dem_path = dem_path
        self.bottom_path = bottom_path
        self.cell_size = cell_size
        self.x_outlet = x_outlet
        self.y_outlet = y_outlet
        self.snap_dist = snap_dist
        self.buff_percent = buff_percent
        self.crs_proj = crs_proj
        self.out_path = out_path
        self.stable_folder = stable_folder
        self.simulations_folder = simulations_folder
        self.calibration_folder = calibration_folder
        self.from_lib = from_lib
        self.from_dem = from_dem
        self.from_shp = from_shp
        self.from_xyv = from_xyv
        self.reg_fold = reg_fold

        if self.from_dem != None:
            self.model_from_dem()
        else:
            self.processing()

        self.post_processing_dem()

    #%% GENERATE FILES

    def processing(self):
        """
        Prepare, initialize and generate files of the model domain from geospatial functions.
        """

        """
        Initial paths
        """
        # Recall important folders
        self.stable_folder = os.path.join(self.out_path, 'results_stable')
        self.simulations_folder = os.path.join(self.out_path, 'results_simulations')

        # Generate folder where processing files are stored
        self.gis_path = os.path.join(self.out_path, 'results_stable','geographic')
        toolbox.create_folder(self.gis_path)

        # Generate regional folder
        self.reg_path = os.path.join(self.out_path, 'results_stable','regional')
        toolbox.create_folder(self.reg_path)

        """
        Raw regional DEM
        """
        # if isinstance(self.regio_path, (str))==False:
        if self.reg_fold == None:
            # Correction
            fill =  os.path.join(self.reg_path, 'region_fill.tif')
            # if not os.path.exists(fill):
            wbt.breach_depressions(self.dem_path, fill) # wbt.fill_depressions(dem_path, fill) or wbt.breach_depressions(dem_path, fill, 2, 75*8)
            # Flow direction
            direc =  os.path.join(self.reg_path, 'region_direc.tif')
            # if not os.path.exists(direc):
            wbt.d8_pointer(fill, direc, esri_pntr=False)
            # Flow accumulation
            acc =  os.path.join(self.reg_path, 'region_acc.tif')
            # if not os.path.exists(acc):
            wbt.d8_flow_accumulation(fill, acc, log=True)
            # Flow accumulation
            down =  os.path.join(self.reg_path, 'region_down.tif')
            # if not os.path.exists(down):
            wbt.downslope_flowpath_length(
                direc,
                down,
                watersheds=None,
                weights=None,
                esri_pntr=False)
        else:
            hierarch_1 = os.path.join(self.reg_fold, 'region_breach.tif')
            hierarch_2 = os.path.join(self.reg_fold, 'region_breach_sec.tif')
            hierarch_3 = os.path.join(self.reg_fold, 'region_fill.tif')
            hierarch_4 = os.path.join(self.reg_fold, 'region_fill_sec.tif')
            if os.path.exists(hierarch_1):
                fill = hierarch_1
            elif os.path.exists(hierarch_2):
                fill = hierarch_2
            elif os.path.exists(hierarch_3):
                fill = hierarch_3
            elif os.path.exists(hierarch_4):
                fill = hierarch_4
            else:
                fill = None
            direc = os.path.join(self.reg_fold, 'region_direc.tif')
            acc = os.path.join(self.reg_fold, 'region_acc.tif')
            down = os.path.join(self.reg_fold, 'region_down.tif')

        """
        Extract watershed from an outlet
        """
        if (self.from_lib != None) or (self.from_xyv != None):
            # Create outlet shapefile from x and y coordinates
            df = pd.DataFrame({'x': [self.x_outlet], 'y': [self.y_outlet]})
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=self.crs_proj)
            outlet_shp = os.path.join(self.gis_path, 'outlet.shp')
            gdf.to_file(outlet_shp)
            # Snap the outlet shapefile from the flow accumulation
            outlet_snap_shp = os.path.join(self.gis_path, 'outlet_snap.shp')
            wbt.snap_pour_points(outlet_shp, acc, outlet_snap_shp, self.snap_dist)
            # Generate raster watershed
            self.watershed = os.path.join(self.gis_path, 'watershed.tif')
            wbt.watershed(direc, outlet_snap_shp, self.watershed, esri_pntr=False)
            # Create shapefile polygon of the watershed
            self.watershed_shp = os.path.join(self.gis_path, 'watershed.shp')
            wbt.raster_to_vector_polygons(self.watershed, self.watershed_shp)
        if self.from_shp != None:
            self.watershed_shp = os.path.join(self.gis_path, 'watershed.shp')
            shp_file = gpd.read_file(self.from_shp[0])
            # Remove duplicate columns if any exist
            shp_file = shp_file.loc[:, ~shp_file.columns.duplicated()]
            shp_file.to_file(self.watershed_shp)
        wbt.polygon_area(self.watershed_shp)
        # Create shapefile polyline of the watershed
        self.watershed_contour_shp = os.path.join(self.gis_path, 'watershed_contour.shp')
        wbt.polygons_to_lines(self.watershed_shp, self.watershed_contour_shp)
        try:
            area = gpd.read_file(self.watershed_shp).AREA[0]/1000000
            self.area = np.abs(area)
        except:
            area = gpd.read_file(self.watershed_shp).area[0]/1000000
            self.area = np.abs(area)
            pass

        """
        Buffer distance operations
        """
        # Normalize initial buffer distance value
        with rasterio.open(self.dem_path) as dem_src:
            pixel_width = abs(dem_src.transform.a)
        if isinstance(self.buff_percent,(str))!=True:
            buff_raw = (np.sqrt(float(self.area))) * (float(self.buff_percent)/100) * 1000
            buff_raw = int(round(buff_raw))
            dist = np.linspace(0,buff_raw,buff_raw+1)*pixel_width
            buff_dist = dist[np.abs(dist-buff_raw).argmin()]
        else:
            buff_dist = float(self.buff_percent)
        site_polyg = gpd.read_file(self.watershed_shp)
        # Remove duplicate columns if any exist
        site_polyg = site_polyg.loc[:, ~site_polyg.columns.duplicated()]
        site_polyg.to_file(self.watershed_shp)
        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist)
        buffer = os.path.join(self.gis_path, 'buff.shp')
        site_polyg.to_file(buffer)

        """
        Box extent operations
        """
        # Create box extent of the watershed
        self.watershed_box_shp = os.path.join(self.gis_path, 'watershed_box.shp')
        wbt.minimum_bounding_envelope(self.watershed_shp, self.watershed_box_shp, features=False)
        # Buffer the box extent watershed shapefile polygon
        site_bound = gpd.read_file(self.watershed_box_shp)
        # Remove duplicate columns if any exist
        site_bound = site_bound.loc[:, ~site_bound.columns.duplicated()]
        site_bound.to_file(self.watershed_box_shp)
        site_bound['geometry'] = site_bound.geometry.buffer(buff_dist)
        self.box_buff = os.path.join(self.gis_path, 'box_buff.shp')
        site_bound.to_file(self.box_buff)
        wbt.minimum_bounding_envelope(self.box_buff, self.box_buff, features=False)
        site_bound = gpd.read_file(self.box_buff)
        # Remove duplicate columns if any exist
        site_bound = site_bound.loc[:, ~site_bound.columns.duplicated()]
        site_bound.to_file(self.box_buff)

        """
        Clip to reach buffer size
        """
        # Clip raw regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_dem = os.path.join(self.gis_path, 'watershed_buff_dem.tif')
        wbt.clip_raster_to_polygon(self.dem_path, buffer, self.watershed_buff_dem,
                                   maintain_dimensions=False)
        # Correct no data
        wbt.modify_no_data_value(self.watershed_buff_dem, new_value='-99999.0')
        # Clip corrected regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_fill = os.path.join(self.gis_path, 'watershed_buff_fill.tif')
        wbt.clip_raster_to_polygon(fill, buffer, self.watershed_buff_fill,
                                   maintain_dimensions=False)
        # Clip flow direction regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_direc = os.path.join(self.gis_path, 'watershed_buff_direc.tif')
        wbt.clip_raster_to_polygon(direc, buffer, self.watershed_buff_direc,
                                   maintain_dimensions=False)
        # Clip bottom
        if self.bottom_path != None :
            self.watershed_buff_bottom = os.path.join(self.gis_path, 'watershed_buff_bottom.tif')
            wbt.clip_raster_to_polygon(self.bottom_path, buffer, self.watershed_buff_bottom,
                                       maintain_dimensions=False)

        """
        Clip to reach watershed size
        """
        # Clip buffer watershed DEM from watershed shapefile polygon
        self.watershed_dem = os.path.join(self.gis_path, 'watershed_dem.tif')
        wbt.clip_raster_to_polygon(self.watershed_buff_dem, self.watershed_shp, self.watershed_dem,
                                   maintain_dimensions=True)
        # Clip corrected regional DEM from watershed shapefile polygon
        self.watershed_fill = os.path.join(self.gis_path, 'watershed_fill.tif')
        wbt.clip_raster_to_polygon(fill, self.watershed_shp, self.watershed_fill,
                                   maintain_dimensions=False)
        # Clip flow direction regional DEM from watershed shapefile polygon
        self.watershed_direc = os.path.join(self.gis_path, 'watershed_direc.tif')
        wbt.clip_raster_to_polygon(direc, self.watershed_shp, self.watershed_direc,
                                   maintain_dimensions=False)
        # Clip bottom
        if self.bottom_path != None :
            self.watershed_bottom = os.path.join(self.gis_path, 'watershed_bottom.tif')
            wbt.clip_raster_to_polygon(self.bottom_path, self.watershed_shp, self.watershed_bottom,
                                       maintain_dimensions=False)
        wbt.slope(self.watershed_dem,
                  os.path.join(self.gis_path, 'watershed_slope.tif'),
                  units="percent")
        with rasterio.open(os.path.join(self.gis_path, 'watershed_slope.tif')) as src:
            slope = src.read(1)
        self.slope = np.nanmean(slope[slope>=0])
        # Create contour
        self.watershed_contour_tif = os.path.join(self.gis_path, 'watershed_contour.tif')
        wbt.vector_lines_to_raster(self.watershed_shp,
                                   self.watershed_contour_tif,
                                   base = self.watershed_dem)

        """
        Clip to reach box extent size
        """
        # Clip raw regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_dem = os.path.join(self.gis_path, 'watershed_box_buff_dem.tif')
        wbt.clip_raster_to_polygon(self.dem_path, self.box_buff, self.watershed_box_buff_dem,
                                   maintain_dimensions=False)
        # Correct no data
        wbt.modify_no_data_value(self.watershed_box_buff_dem, new_value='-99999.0')
        # Clip corrected regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_fill = os.path.join(self.gis_path, 'watershed_box_buff_fill.tif')
        wbt.clip_raster_to_polygon(fill, self.box_buff, self.watershed_box_buff_fill,
                                   maintain_dimensions=False)
        # Clip flow direction regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_direc = os.path.join(self.gis_path, 'watershed_box_buff_direc.tif')
        wbt.clip_raster_to_polygon(direc, self.box_buff, self.watershed_box_buff_direc,
                                   maintain_dimensions=False)
        if self.bottom_path != None :
            self.watershed_box_bottom = os.path.join(self.gis_path, 'watershed_box_buff_bottom.tif')
            wbt.clip_raster_to_polygon(self.bottom_path, self.box_buff, self.watershed_box_bottom,
                                       maintain_dimensions=False)

        with rasterio.open(self.watershed_box_buff_dem) as src1, rasterio.open(self.watershed_buff_dem) as src2:
            if src1.read(1).shape != src2.read(1).shape:
                logger.debug('Reshaping box buffered rasters to match watershed dimensions')
                with rasterio.open(self.watershed_box_buff_dem) as src:
                    toolbox.export_tif(self.watershed_buff_dem, src.read(1), self.watershed_box_buff_dem, -99999)
                with rasterio.open(self.watershed_box_buff_fill) as src:
                    toolbox.export_tif(self.watershed_buff_dem, src.read(1), self.watershed_box_buff_fill, -99999)
                with rasterio.open(self.watershed_box_buff_direc) as src:
                    toolbox.export_tif(self.watershed_buff_dem, src.read(1), self.watershed_box_buff_direc, -32768)
                if self.bottom_path != None :
                    with rasterio.open(self.watershed_box_buff_bottom) as src:
                        toolbox.export_tif(self.watershed_buff_dem, src.read(1), self.watershed_box_buff_bottom, -99999)

        """
        Create depressions raster
        """
        try:
            self.depressions = os.path.join(self.gis_path, 'watershed_depressions.tif')
            wbt.sink(self.watershed_box_buff_dem, self.depressions)
        except:
            pass

    #%% DEM FEATURES

    def post_processing_dem(self):
        """
        Add and/or modify the projection of generated files.
        """

        # Open DEM used for modeling
        with rasterio.open(self.watershed_buff_dem) as dem_src:
            self.dem_data = dem_src.read(1)
            self.geodata = dem_src.transform.to_gdal()
            dem_crs = dem_src.crs
        with rasterio.open(self.watershed_box_buff_dem) as dem_box_src:
            self.dem_box_data = dem_box_src.read(1)
        with rasterio.open(self.watershed_dem) as src:
            # Read the data into a numpy array
            self.dem_clip = src.read(1)
            self.nodata = src.nodata
        # Open DEM depressions
        try:
            with rasterio.open(self.depressions) as dem_dep:
                self.depressions_data = dem_dep.read(1)
        except Exception:
            pass
        # Extract the coordinate system
        if dem_crs:
            epsg_code = dem_crs.to_epsg()
            crs = f"EPSG:{epsg_code}" if epsg_code else dem_crs.to_string()
        else:
            crs = None
        # Extract size characteristics
        self.x_pixel = self.dem_box_data.shape[1] # columns
        self.y_pixel = self.dem_box_data.shape[0] # rows
        # Extract resolution
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
        # Transform centroids to World Geodetic System 1984
        try:
            transformer = Transformer.from_crs(self.crs_proj, "epsg:4326")
            self.centroid_long_lat = transformer.transform(self.centroid[0], self.centroid[1])
            self.ur_long_lat = transformer.transform(self.xmax,self.ymax)
            self.ul_long_lat = transformer.transform(self.xmin,self.ymax)
            self.lr_long_lat = transformer.transform(self.xmax,self.ymin)
            self.ll_long_lat = transformer.transform(self.xmin,self.ymin)
            # Transform to longitude/latitude London Greenwich
            self.centroid_long_lat_Greenwich = [self.centroid_long_lat[0], self.centroid_long_lat[1]]
            if self.centroid_long_lat_Greenwich[1]<0:
                self.centroid_long_lat_Greenwich[1] = self.centroid_long_lat_Greenwich[1] + 360
        except:
            pass
        try:
            locator = Nominatim(user_agent='google')
            location = locator.reverse(str(self.centroid_long_lat_Greenwich[0]) +','+str(self.centroid_long_lat_Greenwich[1]), timeout=120)
            try:
                self.dep_code = int(location.address.split(',')[-2][0:3])
            except:
                pass
        except OSError:
            # In some cases, a SSL certificate error can occur. The next two
            # lines modify the ssl_context
            ctx = ssl.create_default_context(cafile=certifi.where())
            geopy.geocoders.options.default_ssl_context = ctx
            locator = Nominatim(user_agent='google')
            location = locator.reverse(str(self.centroid_long_lat_Greenwich[0]) +','+str(self.centroid_long_lat_Greenwich[1]), timeout=120)
            self.dep_code = int(location.address.split(',')[-2][0:3])
        else:
        # except:
            pass

    #%% XYZ FILE TO DEM

    def model_from_dem(self):
        """
        Function activated if the model domain is directly defined by a DEM.
        Allow to build conceptual model from a conceptual raster.
        """

        # Paths
        # print(self.out_path)
        self.gis_path = os.path.join(self.out_path, 'results_stable/geographic/')
        toolbox.create_folder(self.gis_path)
        # Generate tif from xyz file
        if (self.dem_path[-3:]=='txt'):
            x = pd.read_csv(self.dem_path, delim_whitespace=True, header=None)
            x.to_csv(self.gis_path+'transform_xyz'+'.csv', sep=';', index=False)
            wbt.csv_points_to_vector(self.gis_path+'transform_xyz'+'.csv',
                                     self.gis_path+'transform_xyz'+'.shp',
                                     xfield=0, yfield=1, epsg=2154)
            self.watershed_raw = os.path.join(self.gis_path, 'watershed_raw.tif')
            wbt.vector_points_to_raster(os.path.join(self.gis_path, 'transform_xyz'+'.shp'),
                                        self.watershed_raw,
                                        field=2,
                                        assign="last",
                                        nodata=True,
                                        cell_size=self.cell_size,
                                        base=None)
            # Create the watershed dem
            self.watershed_dem = os.path.join(self.gis_path, 'watershed_dem.tif')
            shutil.copyfile(self.watershed_raw, self.watershed_dem)
        else:
            # Find crs
            with rasterio.open(self.dem_path) as dem_src:
                src_crs = dem_src.crs
            if src_crs:
                epsg_code = src_crs.to_epsg()
                self.crs = f"EPSG:{epsg_code}" if epsg_code else src_crs.to_string()
            else:
                self.crs = None
            # Copy tif
            self.watershed_raw = os.path.join(self.gis_path, 'watershed_raw.tif')
            shutil.copyfile(self.dem_path, self.watershed_raw)
            # Proj layer
            self.watershed_dem = os.path.join(self.gis_path, 'watershed_dem.tif')
            shutil.copyfile(self.watershed_raw, self.watershed_dem)
        # No data
        # wbt.modify_no_data_value(self.watershed_dem, new_value='-99999.0')
        # Buff dem
        self.watershed_buff_dem = self.gis_path + 'watershed_buff_dem.tif'
        shutil.copyfile(self.watershed_dem, self.watershed_buff_dem)
        # Buff box dem
        self.watershed_box_buff_dem = os.path.join(self.gis_path, 'watershed_box_buff_dem.tif')
        shutil.copyfile(self.watershed_dem, self.watershed_box_buff_dem)
        # Correction
        self.watershed_fill = os.path.join(self.gis_path, 'watershed_fill.tif')
        wbt.breach_depressions(self.watershed_dem, self.watershed_fill)
        # Flow direction
        self.watershed_direc = os.path.join(self.gis_path, 'watershed_direc.tif')
        wbt.d8_pointer(self.watershed_fill, self.watershed_direc, esri_pntr=False)
        # Flow accumulation
        self.watershed_acc = os.path.join(self.gis_path, 'watershed_acc.tif')
        wbt.d8_flow_accumulation(self.watershed_fill, self.watershed_acc, log=True)

        self.watershed_buff_fill = os.path.join(self.gis_path, 'watershed_buff_fill.tif')
        shutil.copyfile(self.watershed_fill, self.watershed_buff_fill)

#%% NOTES
