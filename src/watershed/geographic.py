# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% LIBRAIRIES

# Python
import sys
import os
import numpy as np
import pandas as pd
import geopandas as gpd
from osgeo import gdal, osr # or import gdal
import imageio
from pyproj import Transformer
from geopy.geocoders import Nominatim
import shutil
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Root
from os.path import dirname, abspath
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy
from tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS

class Geographic:
    
    #%% INIT
    
    def __init__(self,
                 dem_path,
                 bottom_path,
                 cell_size,
                 x_outlet,
                 y_outlet,
                 snap_dist,
                 buff_percent,
                 crs_proj,
                 out_path,
                 from_lib,
                 from_dem,
                 from_shp,
                 from_xyv):

        print('Extract geography of the model area')
        
        self.dem_path = dem_path
        self.bottom_path = bottom_path
        self.cell_size = cell_size
        self.x_outlet = x_outlet
        self.y_outlet = y_outlet
        self.snap_dist = snap_dist
        self.buff_percent = buff_percent
        self.crs_proj = crs_proj
        self.out_path = out_path
        self.from_lib = from_lib
        self.from_dem = from_dem
        self.from_shp = from_shp
        self.from_xyv = from_xyv
        
        if self.from_dem != None:
            self.model_from_dem(dem_path, cell_size, out_path)
        else:
            self.processing(dem_path,
                            bottom_path,
                            cell_size,
                            x_outlet,
                            y_outlet,
                            snap_dist,
                            buff_percent,
                            crs_proj,
                            out_path)
        
        self.post_processing_dem()
    
    #%% GENERATE FILES
    
    def processing(self,
                   dem_path,
                   bottom_path,
                   cell_size,
                   x_outlet,
                   y_outlet,
                   snap_dist,
                   buff_percent,
                   crs_proj,
                   out_path):
        
        # Recall important folders
        self.stable_folder = os.path.join(out_path, 'results_stable/')
        self.simulations_folder = os.path.join(out_path, 'results_simulations/')
        
        # Generate regional folder
        self.reg_path = os.path.join(out_path, 'results_stable/regional/')
        
        # Generate folder where processing files are stored
        self.gis_path = os.path.join(out_path, 'results_stable/geographic/')
        toolbox.create_folder(self.gis_path)
        
        # Generate regional folder
        self.reg_path = os.path.join(out_path, 'results_stable/regional/')
        toolbox.create_folder(self.reg_path)
        
        """
        Raw regional DEM
        """
        # Correction
        fill =  os.path.join(self.reg_path, 'region_fill.tif')
        # if not os.path.exists(fill):
        wbt.breach_depressions(dem_path, fill) # wbt.fill_depressions(dem_path, fill) or wbt.breach_depressions(dem_path, fill, 2, 75*8)
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
        # Correct no data
        wbt.modify_no_data_value(dem_path, new_value='-99999.0')
        
        """
        Extract watershed from an outlet
        """
        if (self.from_lib != None) | (self.from_xyv != None):
            # Create outlet shapefile from x and y coordinates
            df = pd.DataFrame({'x': [x_outlet], 'y': [y_outlet]})
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=crs_proj)
            outlet_shp = self.gis_path + 'outlet.shp'
            gdf.to_file(outlet_shp)
            # Snap the outlet shapefile from the flow accumulation
            outlet_snap_shp = self.gis_path + 'outlet_snap.shp'
            wbt.snap_pour_points(outlet_shp, acc, outlet_snap_shp, snap_dist)
            # Generate raster watershed
            self.watershed = self.gis_path + 'watershed.tif'
            wbt.watershed(direc, outlet_snap_shp, self.watershed, esri_pntr=False)
            # Create shapefile polygon of the watershed
            self.watershed_shp = self.gis_path + 'watershed.shp'
            wbt.raster_to_vector_polygons(self.watershed, self.watershed_shp)
        if self.from_shp != None:
            self.watershed_shp = self.gis_path + 'watershed.shp'
            shp_file = gpd.read_file(self.from_shp[0])
            shp_file.to_file(self.watershed_shp)
        wbt.polygon_area(self.watershed_shp)
        # Create shapefile polyline of the watershed
        self.watershed_contour_shp = self.gis_path + 'watershed_contour.shp'
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
        dem = gdal.Open(dem_path)
        geodata = dem.GetGeoTransform()
        buff_raw = (np.sqrt(float(self.area))) * (float(buff_percent)/100) * 1000
        buff_raw = int(round(buff_raw))
        dist = np.linspace(0,buff_raw,buff_raw+1)*np.abs(geodata[1])
        buff_dist = dist[np.abs(dist-buff_raw).argmin()]
        # Buffer the watershed shapefile polygon
        site_polyg = gpd.read_file(self.watershed_shp)
        site_polyg.to_file(self.watershed_shp)
        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist)
        buffer = self.gis_path + 'buff.shp'
        site_polyg.to_file(buffer)

        """
        Box extent operations
        """
        # Create box extent of the watershed
        self.watershed_box_shp = self.gis_path + 'watershed_box.shp'
        wbt.minimum_bounding_envelope(self.watershed_shp, self.watershed_box_shp, features=False)
        # Buffer the box extent watershed shapefile polygon
        site_bound = gpd.read_file(self.watershed_box_shp)
        site_bound.to_file(self.watershed_box_shp)
        site_bound['geometry'] = site_bound.geometry.buffer(buff_dist)
        box_buffer = self.gis_path + 'box_buff.shp'
        site_bound.to_file(box_buffer)
        wbt.minimum_bounding_envelope(box_buffer, box_buffer, features=False)
        site_bound = gpd.read_file(box_buffer)
        site_bound.to_file(box_buffer)
        
        """
        Clip to reach buffer size
        """
        # Clip raw regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_dem = self.gis_path + 'watershed_buff_dem.tif'
        wbt.clip_raster_to_polygon(dem_path, buffer, self.watershed_buff_dem,
                                   maintain_dimensions=False)
        # Clip corrected regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_fill = self.gis_path + 'watershed_buff_fill.tif'
        wbt.clip_raster_to_polygon(fill, buffer, self.watershed_buff_fill,
                                   maintain_dimensions=False)
        # Clip flow direction regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_direc = self.gis_path + 'watershed_buff_direc.tif'
        wbt.clip_raster_to_polygon(direc, buffer, self.watershed_buff_direc,
                                   maintain_dimensions=False)
        # Clip bottom
        if self.bottom_path != None :
            self.watershed_buff_bottom = self.gis_path + 'watershed_buff_bottom.tif'
            wbt.clip_raster_to_polygon(self.bottom_path, buffer, self.watershed_buff_bottom,
                                       maintain_dimensions=False)
        
        """
        Clip to reach watershed size
        """
        # Clip buffer watershed DEM from watershed shapefile polygon
        self.watershed_dem = self.gis_path + 'watershed_dem.tif'
        wbt.clip_raster_to_polygon(self.watershed_buff_dem, self.watershed_shp, self.watershed_dem, 
                                   maintain_dimensions=True)
        # Clip corrected regional DEM from watershed shapefile polygon
        self.watershed_fill = self.gis_path + 'watershed_fill.tif'
        wbt.clip_raster_to_polygon(fill, self.watershed_shp, self.watershed_fill,
                                   maintain_dimensions=False)
        # Clip flow direction regional DEM from watershed shapefile polygon
        self.watershed_direc = self.gis_path + 'watershed_direc.tif'
        wbt.clip_raster_to_polygon(direc, self.watershed_shp, self.watershed_direc,
                                   maintain_dimensions=False)
        #○ Clip bottom
        if self.bottom_path != None :
            self.watershed_bottom = self.gis_path + 'watershed_bottom.tif'
            wbt.clip_raster_to_polygon(self.bottom_path, self.watershed_shp, self.watershed_bottom,
                                       maintain_dimensions=False)
        wbt.slope(self.watershed_dem,
                  self.gis_path + 'watershed_slope.tif',
                  units="percent")
        slope = imageio.imread(self.gis_path + 'watershed_slope.tif')
        self.slope = np.nanmean(slope[slope>=0])
        
        """
        Clip to reach box extent size
        """
        # Clip raw regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_dem = self.gis_path + 'watershed_box_buff_dem.tif'
        wbt.clip_raster_to_polygon(dem_path, box_buffer, self.watershed_box_buff_dem,
                                   maintain_dimensions=False)
        # Clip corrected regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_fill = self.gis_path + 'watershed_box_buff_fill.tif'
        wbt.clip_raster_to_polygon(fill, box_buffer, self.watershed_box_buff_fill,
                                   maintain_dimensions=False)
        # Clip flow direction regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_direc = self.gis_path + 'watershed_box_buff_direc.tif'
        wbt.clip_raster_to_polygon(direc, box_buffer, self.watershed_box_buff_direc,
                                   maintain_dimensions=False)
        if self.bottom_path != None :
            self.watershed_box_bottom = self.gis_path + 'watershed_box_buff_bottom.tif'
            wbt.clip_raster_to_polygon(self.bottom_path, box_buffer, self.watershed_box_bottom,
                                       maintain_dimensions=False)
        
        self.watershed_contour_tif = self.gis_path + 'watershed_contour.tif'
        wbt.vector_lines_to_raster(self.watershed_shp,
                                   self.watershed_contour_tif,
                                   base = self.watershed_dem)
        
        """
        Create depressions raster
        """
        try:
            self.depressions = self.gis_path + 'depressions.tif'
            wbt.sink(self.watershed_box_buff_dem, self.depressions)
        except:
            pass
    
    #%% DEM FEATURES
    
    def post_processing_dem(self):

        # Open DEM used for modeling
        dem = gdal.Open(self.watershed_buff_dem)
        self.dem_data = dem.GetRasterBand(1).ReadAsArray()
        self.geodata = dem.GetGeoTransform()
        dem_box = gdal.Open(self.watershed_box_buff_dem)
        self.dem_box_data = dem_box.GetRasterBand(1).ReadAsArray()
        bv = gdal.Open(self.watershed_dem)
        self.dem_clip = bv.GetRasterBand(1).ReadAsArray()
        # Open DEM depressions
        try:
            dem_dep = gdal.Open(self.depressions)
            self.depressions_data = dem_dep.GetRasterBand(1).ReadAsArray()
        except:
            pass
        # Extract the coordinate system
        proj = osr.SpatialReference(wkt=dem.GetProjection())
        crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1)) 
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
            transformer = Transformer.from_crs("epsg:2154", "epsg:4326")
            self.centroid_long_lat = transformer.transform(self.centroid[0], self.centroid[1])
            self.ur_long_lat = transformer.transform(self.xmax,self.ymax)
            self.ul_long_lat = transformer.transform(self.xmin,self.ymax) 
            self.ll_long_lat = transformer.transform(self.xmax,self.ymin)
            self.lr_long_lat = transformer.transform(self.xmin,self.ymin)
            # Transform to longitude/latitude London Greenwich
            self.centroid_long_lat_Greenwich = [self.centroid_long_lat[0], self.centroid_long_lat[1]]
            if self.centroid_long_lat_Greenwich[1]<0:
                self.centroid_long_lat_Greenwich[1] = self.centroid_long_lat_Greenwich[1] + 360
        except:
            pass
        try:
            locator = Nominatim(user_agent='google')
            location = locator.reverse(str(self.centroid_long_lat_Greenwich[0]) +','+str(self.centroid_long_lat_Greenwich[1]), timeout=120)
            self.dep_code = int(location.address.split(',')[-2][0:3])
        except:
            pass
        
    #%% XYZ FILE TO DEM
    
    def model_from_dem(self, dem_path, cell_size, out_path):
        # Paths
        print(out_path)
        self.gis_path = os.path.join(out_path, 'results_stable/geographic/')
        toolbox.create_folder(self.gis_path)
        # Generate tif from xyz file
        if (dem_path[-3:]=='txt'):
            x = pd.read_csv(dem_path, delim_whitespace=True, header=None)
            x.to_csv(self.gis_path+'transform_xyz'+'.csv', sep=';', index=False)
            wbt.csv_points_to_vector(self.gis_path+'transform_xyz'+'.csv', 
                                     self.gis_path+'transform_xyz'+'.shp', 
                                     xfield=0, yfield=1, epsg=2154)
            self.watershed_raw = self.gis_path + 'watershed_raw.tif'
            wbt.vector_points_to_raster(self.gis_path+'transform_xyz'+'.shp', 
                                        self.watershed_raw, 
                                        field=2, 
                                        assign="last", 
                                        nodata=True, 
                                        cell_size=cell_size, 
                                        base=None)        
            # Create the watershed dem
            self.watershed_dem = self.gis_path + 'watershed_dem.tif'
            shutil.copyfile(self.watershed_raw, self.watershed_dem)
        else:
            # Find crs
            dem = gdal.Open(dem_path)
            proj = osr.SpatialReference(wkt=dem.GetProjection())
            self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
            print(self.crs)
            # Copy tif
            self.watershed_raw = self.gis_path + 'watershed_raw.tif'
            shutil.copyfile(dem_path, self.watershed_raw)
            # Proj layer
            self.watershed_dem = self.gis_path + 'watershed_dem.tif'
            shutil.copyfile(self.watershed_raw, self.watershed_dem)
        # No data
        wbt.modify_no_data_value(self.watershed_dem, new_value='-99999.0')  
        # Buff dem
        self.watershed_buff_dem = self.gis_path + 'watershed_buff_dem.tif'
        shutil.copyfile(self.watershed_dem, self.watershed_buff_dem)
        # Buff box dem
        self.watershed_box_buff_dem = self.gis_path + 'watershed_box_buff_dem.tif'
        shutil.copyfile(self.watershed_dem, self.watershed_box_buff_dem)
        # Correction
        self.watershed_fill = self.gis_path + 'watershed_fill.tif'
        wbt.breach_depressions(self.watershed_dem, self.watershed_fill)
        # Flow direction
        self.watershed_direc = self.gis_path + 'watershed_direc.tif'
        wbt.d8_pointer(self.watershed_fill, self.watershed_direc, esri_pntr=False)
        # Flow accumulation
        self.watershed_acc = self.gis_path + 'watershed_acc.tif'
        wbt.d8_flow_accumulation(self.watershed_fill, self.watershed_acc, log=True)
        
        self.watershed_buff_fill = self.gis_path + 'watershed_buff_fill.tif'
        shutil.copyfile(self.watershed_fill, self.watershed_buff_fill)  
        
#%% NOTES
