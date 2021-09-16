# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 20:10:52 2021

@author: Alexandre Gauvain
"""

import geopandas as gpd
import numpy as np
import os
from os.path import dirname, abspath
from osgeo import gdal, osr
import pandas as pd
from pyproj import Transformer
import sys

df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

from tools import file_adds
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)


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
    generate_files(dem_path, x, y, snap_dist, buff_dist, out_path)
        creates files to extract watershed from regional DEM
    load_files(dem_path)
        loads files to 
    """
    def __init__(self, dem_path, x, y, snap_dist=150, buff_dist=1000,
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\'):
        print('Extraction des données géographiques')
        gis_path = out_path + '/data/geographic/'
        self.watershed_shp = gis_path + 'watershed.shp'
        self.watershed_box_shp = gis_path + 'watershed_box.shp'
        self.watershed_fill = gis_path + 'watershed_fill.tif'
        self.watershed_direc = gis_path + 'watershed_direc.tif'
        self.watershed_buff_dem = gis_path + 'watershed_buff_dem.tif'
        self.watershed_box_buff_dem = gis_path + 'watershed_box_buff_dem.tif'
        
        
        self.dem_data = None
        self.dem_box_data = None
        self.geodata = None
        self.resolution = None
        self.x_pixel = None
        self.y_pixel = None
        self.crs = None
        self.xmin = None
        self.xmax = None
        self.ymin = None
        self.ymax = None
        self.x_coord = None
        self.y_coord = None
        self.centroid = None
        
        self.processing_wbt(dem_path, x, y, snap_dist, buff_dist, out_path, gis_path)
        self.post_processing_dem()

    def processing_wbt(self, dem_path, x, y, snap_dist, buff_dist, out_path, gis_path):
        """
        Parameters
        ----------
        dem_path : TYPE
            DESCRIPTION.
        x : TYPE
            DESCRIPTION.
        y : TYPE
            DESCRIPTION.
        snap_dist : TYPE
            DESCRIPTION.
        buff_dist : TYPE
            DESCRIPTION.
        out_path : TYPE
            DESCRIPTION.
        gis_path : TYPE
            DESCRIPTION.

        Returns
        -------
        None.

        """
        # whitebox tools uses the intermediary files that will be specified as follows
        fill = gis_path + 'region_fill.tif'
        direc = gis_path + 'region_direc.tif'
        acc = gis_path + 'region_acc.tif'
        outlet_shp = gis_path + 'outlet.shp'
        outlet_snap_shp = gis_path + 'outlet_snap.shp'
        watershed = gis_path + 'watershed.tif'
        watershed_contour_shp = gis_path + 'watershed_contour.shp'        
        watershed_dem = gis_path + 'watershed_dem.tif'
        buffer = gis_path + 'buff.shp'
        watershed_buff_fill = gis_path + 'watershed_buff_fill.tif'
        watershed_buff_direc = gis_path + 'watershed_buff_direc.tif'
        watershed_box_buff_fill = gis_path + 'watershed_box_buff_fill.tif'
        watershed_box_buff_direc = gis_path + 'watershed_box_buff_direc.tif'
        
        #if working directory doesn't exist, creates it
        file_adds.create_folder(gis_path)
        
        # 1. Load and geopatial treatment of regional DEM
        dem = gdal.Open(dem_path) # Open regional DEM
        proj = osr.SpatialReference(wkt=dem.GetProjection()) # Get projection system
        crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1)) # Get CRS 
        geodata = dem.GetGeoTransform() # Get geospatial informations
        #wbt.breach_depressions(dem_path,fill,2,75*8)
        wbt.fill_depressions(dem_path, fill)
        wbt.d8_pointer(fill, direc, esri_pntr=False)
        wbt.d8_flow_accumulation(fill, acc, log=True)
        
        # 2. Create outlet from watershed accumulation
        df = pd.DataFrame({'x': [x], 'y': [y]})
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=crs)
        gdf.to_file(outlet_shp)
        wbt.snap_pour_points(outlet_shp, acc, outlet_snap_shp, snap_dist)
        
        # 3. Clip watershed from regional DEM with outlet
        wbt.watershed(direc, outlet_snap_shp, watershed, esri_pntr=False) # create watershed dem
        wbt.raster_to_vector_polygons(watershed, self.watershed_shp) # create watershed polygon
        wbt.polygons_to_lines(self.watershed_shp, watershed_contour_shp) # create watershed contour
        
        # 4. Create watershed buffered
        site_polyg = gpd.read_file(self.watershed_shp) # Load watershed dem
        site_polyg.to_file(self.watershed_shp) # save watershed dem
        dist = np.linspace(0,buff_dist,buff_dist+1)*np.abs(geodata[1]) # translate buffer distance to buffer pixel
        buff_dist = dist[np.abs(dist-buff_dist).argmin()] # translate buffer distance to buffer pixel
        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist) # add buffer to watershed boundaries
        site_polyg.to_file(buffer) # save buffered watershed
        
        # 5. Create buffered watershed files
        wbt.clip_raster_to_polygon(dem_path,buffer,self.watershed_buff_dem) # create watershed buffered DEM
        wbt.clip_raster_to_polygon(fill,buffer,watershed_buff_fill) # creat watershed buffred filled depressions
        wbt.clip_raster_to_polygon(direc,buffer,watershed_buff_direc) # create watershed buffered flow direction
        
        # 6. Create watershed files
        wbt.clip_raster_to_polygon(self.watershed_buff_dem, self.watershed_shp,
                                   watershed_dem, maintain_dimensions=True) # create watershed DEM 
        wbt.clip_raster_to_polygon(fill,self.watershed_shp,self.watershed_fill) # create watershef filled depressions
        wbt.clip_raster_to_polygon(direc,self.watershed_shp,self.watershed_direc) # create watershed flow direction
        
        # 7. Create watershed files with box boundaries
        wbt.minimum_bounding_envelope(self.watershed_shp,self.watershed_box_shp, features=False) # create box boundaries
        site_polyg = gpd.read_file(self.watershed_box_shp) # load box shapefile
        site_polyg.to_file(self.watershed_box_shp) # save box shapefile because crs
        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist) # add buffer to the box
        site_polyg.to_file(buffer) # save box buffered
        wbt.minimum_bounding_envelope(buffer,buffer, features=False) # recreate buffer files
        site_polyg = gpd.read_file(buffer) # load buffer shapefile
        site_polyg.to_file(buffer) # save buffer shapefile
        wbt.clip_raster_to_polygon(dem_path,buffer,self.watershed_box_buff_dem) # create box watershed DEM
        wbt.clip_raster_to_polygon(fill,buffer,watershed_box_buff_fill) # create box fill depression
        wbt.clip_raster_to_polygon(direc,buffer,watershed_box_buff_direc) # creat box flow direction
        

    def post_processing_dem(self):
        """
        
        
        Returns
        -------
        None.

        """
        dem = gdal.Open(self.watershed_buff_dem)
        self.dem_data = dem.GetRasterBand(1).ReadAsArray()
        dem = gdal.Open(self.watershed_box_buff_dem)
        self.dem_box_data = dem.GetRasterBand(1).ReadAsArray()
        self.geodata = dem.GetGeoTransform()
        self.resolution = abs(self.geodata[1])
        self.x_pixel = self.dem_data.shape[1]
        self.y_pixel = self.dem_data.shape[0]

        proj = osr.SpatialReference(wkt=dem.GetProjection())
        self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1)) 
        self.xmin = self.geodata[0]
        self.xmax = self.geodata[0] + self.dem_data.shape[1] * self.geodata[1]
        self.ymin = self.geodata[3] + self.dem_data.shape[0] * self.geodata[5]
        self.ymax = self.geodata[3]

        self.x_coord = np.linspace(1,self.x_pixel, self.x_pixel)*(self.resolution) + self.xmin
        self.y_coord = self.ymax - np.linspace(1,self.y_pixel, self.y_pixel)*(self.resolution)

        self.centroid = [self.xmin+((self.xmax-self.xmin)/2),self.ymin+((self.ymax-self.ymin)/2)]
        transformer = Transformer.from_crs("epsg:2154", "epsg:4326")
        self.centroid_long_lat = transformer.transform(self.centroid[0], self.centroid[1])
        self.centroid_long_lat_Greenwich = [self.centroid_long_lat[0], self.centroid_long_lat[1]]
        if self.centroid_long_lat_Greenwich[1]<0:
            self.centroid_long_lat_Greenwich[1] = self.centroid_long_lat_Greenwich[1] + 360
