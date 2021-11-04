# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 20:10:52 2021

@author: Alexandre Gauvain
"""

# Modules
import geopandas as gpd
import numpy as np
import os
from osgeo import gdal, osr
import pandas as pd
from pyproj import Transformer
import whitebox
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.verbose = False

# HydroModPy modules
from tools import file_adds

class Geographic:
    """
    class Geographic used to clip the watershed from regional DEM

    Attributes
    ----------
    watershed_shp: str
        path of watershed shapefile
    watershed_box_shp: str
        path of watershed shapefile (boundaries box)
    watershed_fill: str
        path of watershed filled
    watershed_dir: str
        path of watershed flow direction
    
    Methods
    -------
    processing(dem_path, x, y, snap_dist, buff_dist, out_path)
        creates files to extract watershed from regional DEM
    post_processing_dem(dem_path)
        loads files to 
    """
    
    def __init__(self, dem_path, x, y, snap_dist=150, buff_dist=1000,
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\'):
        print('Extraction des données géographiques')
        
        self.processing(dem_path, x, y, snap_dist, buff_dist, out_path)
        self.post_processing_dem()

    def processing(self, dem_path, x, y, snap_dist, buff_dist, out_path):
        # Generate folder where processing files are stored
        gis_path = os.path.join(out_path, 'results_stable/geographic/')
        file_adds.create_folder(gis_path)
        
        """
        Raw regional DEM
        """
        # Open
        dem = gdal.Open(dem_path)
        geodata = dem.GetGeoTransform()
        # Correction
        fill = gis_path + 'region_fill.tif'
        wbt.fill_depressions(dem_path, fill) # or # wbt.breach_depressions(dem_path, fill, 2, 75*8)
        # Flow direction
        direc = gis_path + 'region_direc.tif'
        wbt.d8_pointer(fill, direc, esri_pntr=False)
        # Flow accumulation
        acc = gis_path + 'region_acc.tif'
        wbt.d8_flow_accumulation(fill, acc, log=True)
        
        """
        Extract watershed from an outlet
        """
        # Extract the coordinate system
        proj = osr.SpatialReference(wkt=dem.GetProjection())
        crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
        # Create outlet shapefile from x and y coordinates
        df = pd.DataFrame({'x': [x], 'y': [y]})
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=crs)
        outlet_shp = gis_path + 'outlet.shp'
        gdf.to_file(outlet_shp)
        # Snap the outlet shapefile from the flow accumulation
        outlet_snap_shp = gis_path + 'outlet_snap.shp'
        wbt.snap_pour_points(outlet_shp, acc, outlet_snap_shp, snap_dist)
        # Generate raster watershed
        watershed = gis_path + 'watershed.tif'
        wbt.watershed(direc, outlet_snap_shp, watershed, esri_pntr=False)
        # Create shapefile polygon of the watershed
        self.watershed_shp = gis_path + 'watershed.shp'
        wbt.raster_to_vector_polygons(watershed, self.watershed_shp)
        # Create shapefile polyline of the watershed
        self.watershed_contour_shp = gis_path + 'watershed_contour.shp'    
        wbt.polygons_to_lines(self.watershed_shp, self.watershed_contour_shp)
        
        """
        Buffer distance operations
        """
        # Normalize initial buffer distance value
        dist = np.linspace(0,buff_dist,buff_dist+1)*np.abs(geodata[1])
        buff_dist = dist[np.abs(dist-buff_dist).argmin()]
        # Buffer the watershed shapefile polygon
        site_polyg = gpd.read_file(self.watershed_shp)
        site_polyg.to_file(self.watershed_shp)
        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist)
        buffer = gis_path + 'buff.shp'
        site_polyg.to_file(buffer)

        """
        Box extent operations
        """
        # Create box extent of the watershed
        self.watershed_box_shp = gis_path + 'watershed_box.shp'
        wbt.minimum_bounding_envelope(self.watershed_shp, self.watershed_box_shp, features=False)
        # Buffer the box extent watershed shapefile polygon
        site_bound = gpd.read_file(self.watershed_box_shp)
        site_bound.to_file(self.watershed_box_shp)
        site_bound['geometry'] = site_bound.geometry.buffer(buff_dist)
        box_buffer = gis_path + 'box_buff.shp'
        site_bound.to_file(box_buffer)
        wbt.minimum_bounding_envelope(box_buffer, box_buffer, features=False)
        site_bound = gpd.read_file(box_buffer)
        site_bound.to_file(box_buffer)
        
        """
        Clip to reach buffer size
        """
        # Clip raw regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_dem = gis_path + 'watershed_buff_dem.tif'
        wbt.clip_raster_to_polygon(dem_path, buffer, self.watershed_buff_dem)
        # Clip corrected regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_fill = gis_path + 'watershed_buff_fill.tif'
        wbt.clip_raster_to_polygon(fill, buffer, self.watershed_buff_fill)
        # Clip flow direction regional DEM from buffer watershed shapefile polygon
        watershed_buff_direc = gis_path + 'watershed_buff_direc.tif'
        wbt.clip_raster_to_polygon(direc, buffer, watershed_buff_direc)
        
        """
        Clip to reach watershed size
        """
        # Clip buffer watershed DEM from watershed shapefile polygon
        self.watershed_dem = gis_path + 'watershed_dem.tif'
        wbt.clip_raster_to_polygon(self.watershed_buff_dem, self.watershed_shp, self.watershed_dem, maintain_dimensions=True)
        # Clip corrected regional DEM from watershed shapefile polygon
        self.watershed_fill = gis_path + 'watershed_fill.tif'
        wbt.clip_raster_to_polygon(fill, self.watershed_shp, self.watershed_fill)
        # Clip flow direction regional DEM from watershed shapefile polygon
        self.watershed_direc = gis_path + 'watershed_direc.tif'
        wbt.clip_raster_to_polygon(direc, self.watershed_shp, self.watershed_direc)
        
        """
        Clip to reach box extent size
        """
        # Clip raw regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_dem = gis_path + 'watershed_box_buff_dem.tif'
        wbt.clip_raster_to_polygon(dem_path, box_buffer, self.watershed_box_buff_dem)
        # Clip corrected regional DEM from buffer box extent watershed shapefile polygon
        watershed_box_buff_fill = gis_path + 'watershed_box_buff_fill.tif'
        wbt.clip_raster_to_polygon(fill, box_buffer, watershed_box_buff_fill)
        # Clip flow direction regional DEM from buffer box extent watershed shapefile polygon
        watershed_box_buff_direc = gis_path + 'watershed_box_buff_direc.tif'
        wbt.clip_raster_to_polygon(direc, box_buffer, watershed_box_buff_direc)
        
        """
        Create depressions raster
        """
        try:
            self.depressions = gis_path + 'depressions.tif'
            wbt.sink(self.watershed_box_buff_dem, self.depressions)
        except:
            pass
        
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
        dem_dep = gdal.Open(self.depressions)
        self.depressions_data = dem_dep.GetRasterBand(1).ReadAsArray()
        # Extract the coordinate system
        proj = osr.SpatialReference(wkt=dem.GetProjection())
        self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1)) 
        # Extract size characteristics
        self.x_pixel = self.dem_data.shape[1] # columns
        self.y_pixel = self.dem_data.shape[0] # rows
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
            # Transform to longitude/latitude London Greenwich
            self.centroid_long_lat_Greenwich = [self.centroid_long_lat[0], self.centroid_long_lat[1]]
            if self.centroid_long_lat_Greenwich[1]<0:
                self.centroid_long_lat_Greenwich[1] = self.centroid_long_lat_Greenwich[1] + 360
        except:
            pass
